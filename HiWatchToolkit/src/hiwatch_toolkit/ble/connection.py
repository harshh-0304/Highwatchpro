"""
BLE connection lifecycle — connect, disconnect, MTU, notification handling.

Wraps a single ``BleakClient`` and exposes an async context manager API.
"""

from __future__ import annotations

import asyncio
import logging
from enum import Enum, auto
from typing import Callable, Optional

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak.backends.service import BleakGATTServiceCollection

from ..protocol.constants import (
    UART_SERVICE,
    UART_WRITE_CHAR,
    UART_NOTIFY_CHAR,
    UART_NOTIFY_CCCD,
    DIAL_SERVICE,
    DIAL_CHAR,
)
from ..protocol.packet import Packet
from ..utils.bytes import Bytes

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    DISCONNECTING = auto()


NotificationCallback = Callable[[bytearray], None]


class WatchConnection:
    """
    Manages a BLE connection to the watch.

    Usage::

        conn = WatchConnection(device)
        async with conn:
            await conn.write(b'...')
            data = await conn.wait_for_notification(timeout=5)
    """

    def __init__(self, device: BLEDevice) -> None:
        self._device = device
        self._client: Optional[BleakClient] = None
        self._state = ConnectionState.DISCONNECTED
        self._notification_queue: asyncio.Queue[bytearray] = asyncio.Queue()
        self._notification_handler: Optional[NotificationCallback] = None
        self._write_char = UART_WRITE_CHAR
        self._notify_char = UART_NOTIFY_CHAR
        self._mtu: int = 23  # BLE default
        self._service_map: dict[str, list[dict]] = {}
        """Discovered services: {uuid: [{uuid, handle, properties}]}."""
        self._write_logger: Optional[Callable[[bytearray], None]] = None
        """Optional callback invoked with every outgoing payload before write."""
        self._gatt_read_logger: Optional[Callable[[str, str, Optional[bytearray]], None]] = None
        """Optional callback invoked after every GATT characteristic read."""

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def is_connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED and self._client is not None and self._client.is_connected

    @property
    def device(self) -> BLEDevice:
        return self._device

    @property
    def mtu(self) -> int:
        return self._mtu

    @property
    def max_write_size(self) -> int:
        """Maximum bytes per write (MTU - 3)."""
        return max(self._mtu - 3, 20)

    @property
    def service_map(self) -> dict[str, list[dict]]:
        """Discovered GATT services: ``{uuid: [{char_uuid, handle, properties}]}``."""
        return dict(self._service_map)

    @property
    def write_char_uuid(self) -> str:
        """UUID of the located write characteristic."""
        return str(self._write_char)

    @property
    def notify_char_uuid(self) -> str:
        """UUID of the located notify characteristic."""
        return str(self._notify_char)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self, timeout: float = 10.0) -> None:
        """Establish the BLE connection and discover services."""
        if self.is_connected:
            return
        self._state = ConnectionState.CONNECTING

        try:
            self._client = BleakClient(self._device, disconnected_callback=self._on_disconnect)
            await self._client.connect(timeout=timeout)

            # Read negotiated MTU size — Bleak exposes this via the
            # ``mtu_size`` property after connection.  No explicit
            # ``read_mtu()`` method exists in bleak ≥0.21.
            try:
                self._mtu = self._client.mtu_size
                if self._mtu < 23:
                    self._mtu = 23
            except Exception:
                self._mtu = 23

            logger.info("Connected to %s (MTU=%d)", self._device.address, self._mtu)

            # Services are discovered automatically by the backend during
            # ``connect()``.  Access them via the ``services`` property.
            # If they are not yet populated, the property getter raises
            # ``BleakError``, which we catch and fall back to the
            # hardcoded known UUIDs.
            try:
                services: BleakGATTServiceCollection = self._client.services
                self._build_service_map(services)
                # Auto-locate write and notify characteristics
                self._auto_locate_chars()
            except BleakError:
                logger.warning("Service discovery incomplete — using known UUIDs")
                self._service_map = {}
                if self._client.services.get_service(DIAL_SERVICE):
                    self._write_char = DIAL_CHAR
                    self._notify_char = DIAL_CHAR

            # Enable notifications on the notify characteristic
            await self._client.start_notify(self._notify_char, self._on_notification)

            self._state = ConnectionState.CONNECTED

        except (BleakError, asyncio.TimeoutError, Exception) as exc:
            self._state = ConnectionState.DISCONNECTED
            logger.error("Connection failed: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Service discovery helpers
    # ------------------------------------------------------------------

    def _build_service_map(self, services: BleakGATTServiceCollection) -> None:
        """Populate ``_service_map`` from the discovered GATT services."""
        self._service_map.clear()
        for svc in services.services.values():
            uuid_str = str(svc.uuid).upper()
            char_list: list[dict] = []
            for char in svc.characteristics:
                char_list.append({
                    "uuid": str(char.uuid).upper(),
                    "handle": char.handle,
                    "properties": list(char.properties),
                })
            self._service_map[uuid_str] = char_list

    def _auto_locate_chars(self) -> None:
        """Auto-locate write and notify characteristics from the service map.

        Priority order:
        1. Exact known UUIDs (UART service)
        2. Dial service (some firmware versions)
        3. First characteristic with write/notify properties found
        """
        located_write = None
        located_notify = None

        # Phase 1: look at every discovered characteristic
        for uuid_str, chars in self._service_map.items():
            for c in chars:
                cuuid = c["uuid"]
                props = c["properties"]

                # Check for known write UUIDs
                if cuuid == str(UART_WRITE_CHAR).upper():
                    located_write = cuuid
                if cuuid == str(UART_NOTIFY_CHAR).upper():
                    located_notify = cuuid
                if cuuid == str(DIAL_CHAR).upper():
                    if located_write is None:
                        located_write = cuuid
                    if located_notify is None:
                        located_notify = cuuid

                # Fallback: pick first characteristic with write property
                if located_write is None and ("write" in props or "write-without-response" in props):
                    located_write = cuuid
                # Fallback: pick first characteristic with notify/indicate
                if located_notify is None and ("notify" in props or "indicate" in props):
                    located_notify = cuuid

        if located_write:
            self._write_char = located_write
        if located_notify:
            self._notify_char = located_notify

        logger.info(
            "Located: write=%s notify=%s",
            self._write_char,
            self._notify_char,
        )

    async def disconnect(self) -> None:
        """Gracefully disconnect."""
        if self._client is None or not self._client.is_connected:
            self._state = ConnectionState.DISCONNECTED
            return

        self._state = ConnectionState.DISCONNECTING
        try:
            await self._client.stop_notify(self._notify_char)
            await self._client.disconnect()
        except Exception as exc:
            logger.warning("Disconnect error: %s", exc)
        finally:
            self._client = None
            self._state = ConnectionState.DISCONNECTED
            logger.info("Disconnected")

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    async def write(self, data: bytes) -> None:
        """Write bytes to the write characteristic.

        If a write-logger callback is registered (via
        :meth:`set_write_logger`), it is invoked with the raw bytes
        before the write — used by the packet debugger for TX logging.
        """
        if not self.is_connected or self._client is None:
            raise BleakError("Not connected")

        if self._write_logger:
            self._write_logger(bytearray(data))

        await self._client.write_gatt_char(
            self._write_char,
            bytearray(data),
            response=True,  # write-with-response for reliability
        )

    async def read_notifications(
        self,
        timeout: float = 5.0,
        max_messages: int = 1,
    ) -> list[bytearray]:
        """Read pending notifications (up to ``max_messages``)."""
        messages: list[bytearray] = []
        deadline = asyncio.get_event_loop().time() + timeout

        while len(messages) < max_messages:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                msg = await asyncio.wait_for(
                    self._notification_queue.get(),
                    timeout=remaining,
                )
                messages.append(msg)
            except asyncio.TimeoutError:
                break

        return messages

    async def wait_for_notification(self, timeout: float = 5.0) -> Optional[bytearray]:
        """Wait for a single notification."""
        msgs = await self.read_notifications(timeout=timeout, max_messages=1)
        return msgs[0] if msgs else None

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> WatchConnection:
        await self.connect()
        return self

    async def __aexit__(self, *args) -> None:
        await self.disconnect()

    # ------------------------------------------------------------------
    # Internal callbacks
    # ------------------------------------------------------------------

    def _on_notification(self, sender: object, data: bytearray) -> None:
        """Bleak notification callback.

        ``sender`` is a ``BleakGATTCharacteristic`` in bleak ≥0.21
        (was ``int`` in earlier versions).  We only use ``data``.
        """
        self._notification_queue.put_nowait(data)
        if self._notification_handler:
            self._notification_handler(data)

    def _on_disconnect(self, client: BleakClient) -> None:
        """Bleak disconnect callback."""
        logger.info("Device disconnected: %s", self._device.address)
        self._state = ConnectionState.DISCONNECTED

    def set_notification_handler(self, handler: Optional[NotificationCallback]) -> None:
        """Set an optional callback for every incoming notification."""
        self._notification_handler = handler

    async def read_characteristic(
        self,
        uuid: str,
        label: str = "",
    ) -> Optional[bytearray]:
        """Read the value of a GATT characteristic by UUID.

        Parameters
        ----------
        uuid:
            Full UUID string of the characteristic to read (e.g.
            ``"00002a19-0000-1000-8000-00805f9b34fb"``).
        label:
            Human-readable label for logging (e.g. ``"Battery Level"``).

        Returns
        -------
        The raw bytearray value, or ``None`` if the characteristic was not
        found in the service map or the read failed.

        The read event is logged through the write-logger callback (``TX``
        synthetic packet) and on success a synthetic ``RX`` notification
        is emitted so the session recorder captures every transaction.
        """
        if not self.is_connected or self._client is None:
            logger.warning("read_characteristic(%s): not connected", label or uuid)
            return None

        # Build a synthetic protocol packet for the read request (TX)
        uuid_bytes = uuid.encode("ascii")
        tx_pkt = Packet.with_payload(0xFD, 0x01, uuid_bytes)
        if self._write_logger:
            self._write_logger(bytearray(tx_pkt.data))

        try:
            value: bytearray = await self._client.read_gatt_char(uuid)
            if value and self._notification_handler:
                # Forward as a synthetic RX notification
                rx_pkt = Packet.with_payload(0xFD, 0x02, bytes(value))
                self._notification_handler(bytearray(rx_pkt.data))
            if self._gatt_read_logger:
                self._gatt_read_logger(uuid, label, value)
            return value
        except Exception as exc:
            logger.warning("read_characteristic(%s): %s", label or uuid, exc)
            if self._gatt_read_logger:
                self._gatt_read_logger(uuid, label, None)
            return None

    def set_gatt_read_logger(
        self,
        callback: Optional[Callable[[str, str, Optional[bytearray]], None]],
    ) -> None:
        """Register a callback for GATT characteristic read results.

        The callback receives ``(uuid, label, value_or_None)`` for every
        completed GATT read.
        """
        self._gatt_read_logger = callback

    def set_write_logger(self, callback: Optional[Callable[[bytearray], None]]) -> None:
        """Set an optional callback invoked with every outgoing payload before write.

        Used by the packet debugger to log TX packets.
        """
        self._write_logger = callback
