"""
D-Bus BLE GATT transport — connects to HiWatch devices via BlueZ D-Bus API.

Replaces ``BleakClient`` where Bleak cannot discover the device (e.g. when
it is already bonded via classic Bluetooth and not actively advertising).

Usage::

    transport = DBusGATTTransport("66:22:AA:00:42:78")
    await transport.connect()
    await transport.write(packet.data)
    response = await transport.wait_for_notification(timeout=5.0)
    await transport.disconnect()
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from dbus_fast import Message, MessageType
from dbus_fast.aio import MessageBus
from dbus_fast.constants import BusType

logger = logging.getLogger(__name__)

BLUEZ_SERVICE = "org.bluez"
DEVICE_IFACE = "org.bluez.Device1"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHAR_IFACE = "org.bluez.GattCharacteristic1"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
OM_IFACE = "org.freedesktop.DBus.ObjectManager"

# Characteristic UUIDs we are looking for
WRITE_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9d"
NOTIFY_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9d"


class DBusGATTError(Exception):
    """D-Bus GATT operation failed."""


class DBusGATTTransport:
    """
    D-Bus based BLE GATT transport for HiWatch devices.

    Provides connect/write/wait_for_notification/disconnect lifecycle
    matching ``WatchConnection`` semantics.
    """

    def __init__(self, mac_address: str) -> None:
        self._mac = mac_address
        self._bus: Optional[MessageBus] = None
        self._dev_path: Optional[str] = None
        self._write_path: Optional[str] = None
        self._notify_path: Optional[str] = None
        self._connected = False
        self._notification_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._signal_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self, timeout: float = 15.0) -> None:
        """Connect to the device and resolve GATT service paths."""
        if self._connected:
            return

        logger.info("Connecting to %s via D-Bus...", self._mac)
        self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()

        # --- Find device in BlueZ object tree ---
        self._dev_path = await self._find_device()
        if not self._dev_path:
            raise DBusGATTError(f"Device {self._mac} not found in BlueZ tree. Pair first: bluetoothctl pair {self._mac}")

        logger.info("Device path: %s", self._dev_path)

        # --- Establish BLE GATT connection ---
        # BlueZ Device1.Connect() connects via BR/EDR on dual-mode devices,
        # which does NOT expose the GATT ATT bearer needed for characteristic
        # read/write.  Pair() instead: it connects + initiates LE pairing +
        # discovers services in one call, making GATT D-Bus objects available.
        already_resolved = await self._get_prop("ServicesResolved")
        already_connected = await self._get_prop("Connected")

        needs_reconnect = not (already_connected and already_resolved)

        if needs_reconnect:
            logger.info("Connecting and pairing via Device1.Pair() ...")
            try:
                await asyncio.wait_for(
                    self._call(self._dev_path, DEVICE_IFACE, "Pair"),
                    timeout=30.0,
                )
                logger.info("Pair() returned OK")
            except asyncio.TimeoutError:
                raise DBusGATTError("Pair() timed out — check watch is in range and not in a call")
            except Exception as e:
                raise DBusGATTError(f"Pair() failed: {e}")

            # Wait for services to resolve after pairing
            for attempt in range(10):
                resolved = await self._get_prop("ServicesResolved")
                connected = await self._get_prop("Connected")
                if resolved and connected:
                    logger.info("Services resolved and connected")
                    break
                logger.info("Waiting for services to resolve (attempt %d)...", attempt + 1)
                await asyncio.sleep(2)
            else:
                logger.warning("Services may not be fully resolved — continuing anyway")
        else:
            logger.info("Already connected with resolved services")

        # --- Discover GATT characteristic paths ---
        found = await self._discover_gatt_chars()
        if not found:
            raise DBusGATTError(
                f"GATT characteristics not found after pairing. "
                f"The watch may need to be in pairing mode. "
                f"Try manually: bluetoothctl remove {self._mac} && "
                f"bluetoothctl pair {self._mac}"
            )

        logger.info("Write char: %s", self._write_path)
        logger.info("Notify char: %s", self._notify_path)

        # --- Enable notifications ---
        try:
            await self._call(self._notify_path, GATT_CHAR_IFACE, "StartNotify")
            logger.info("Notifications enabled")
        except Exception as e:
            logger.warning("StartNotify: %s", e)

        # --- Start signal listener for notifications ---
        self._signal_task = asyncio.create_task(self._signal_listener())

        self._connected = True
        logger.info("D-Bus transport connected")

    async def disconnect(self) -> None:
        """Disconnect and clean up."""
        if self._signal_task:
            self._signal_task.cancel()
            self._signal_task = None

        if self._notify_path and self._bus:
            try:
                await self._call(self._notify_path, GATT_CHAR_IFACE, "StopNotify")
            except Exception:
                pass

        if self._dev_path and self._bus:
            try:
                await self._call(self._dev_path, DEVICE_IFACE, "Disconnect")
            except Exception:
                pass

        if self._bus:
            self._bus.disconnect()
            self._bus = None

        self._connected = False

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    async def write(self, data: bytes, *, response: bool = True) -> None:
        """Write bytes to the GATT write characteristic.

        Parameters
        ----------
        response:
            ``True`` (default) = write-with-response (ATT Write Request).
            ``False`` = write-without-response (ATT Write Command), set by
            passing ``{"type": Variant("s", "command")}`` in options.
        """
        if not self._connected or not self._write_path:
            raise DBusGATTError("Not connected")

        options: dict = {}
        if not response:
            from dbus_fast import Variant
            options["type"] = Variant("s", "command")

        msg = Message(
            destination=BLUEZ_SERVICE,
            path=self._write_path,
            interface=GATT_CHAR_IFACE,
            member="WriteValue",
            signature="aya{sv}",
            body=[bytearray(data), options],
        )
        reply = await self._bus.call(msg)
        if reply.message_type == MessageType.ERROR:
            raise DBusGATTError(f"WriteValue failed: {reply.body}")

    async def wait_for_notification(self, timeout: float = 5.0) -> Optional[bytes]:
        """Wait for a single notification from the watch."""
        try:
            data = await asyncio.wait_for(
                self._notification_queue.get(),
                timeout=timeout,
            )
            return data
        except asyncio.TimeoutError:
            return None

    # ------------------------------------------------------------------
    # Internal — D-Bus helpers
    # ------------------------------------------------------------------

    async def _call(self, path: str, iface: str, member: str,
                     sig: Optional[str] = None, body: Optional[list] = None) -> Message:
        """Make a D-Bus method call and return the reply."""
        msg = Message(
            destination=BLUEZ_SERVICE,
            path=path,
            interface=iface,
            member=member,
        )
        if sig is not None:
            msg.signature = sig
        if body is not None:
            msg.body = body
        reply = await self._bus.call(msg)
        if reply.message_type == MessageType.ERROR:
            raise DBusGATTError(f"{member}: {reply.body}")
        return reply

    async def _get_prop(self, prop_name: str):
        """Read a Device1 property."""
        try:
            reply = await self._call(
                self._dev_path, PROPS_IFACE, "Get",
                "ss", [DEVICE_IFACE, prop_name],
            )
            return reply.body[0].value
        except Exception:
            return None

    async def _find_device(self) -> Optional[str]:
        """Find the device path in the BlueZ object tree by MAC."""
        reply = await self._call("/", OM_IFACE, "GetManagedObjects")
        objects = reply.body[0]

        target_mac = self._mac.lower().replace(":", "_")
        for path, ifaces in objects.items():
            if DEVICE_IFACE in ifaces:
                # Match on path (dev_XX_XX_...) — avoids Variant access quirks
                if target_mac in path.lower():
                    return path
        return None

    async def _find_char_by_uuid(self, target_uuid: str) -> Optional[str]:
        """Find a GATT characteristic path by UUID under our device."""
        if not self._dev_path:
            return None

        reply = await self._call("/", OM_IFACE, "GetManagedObjects")
        objects = reply.body[0]

        target_uuid_lower = target_uuid.lower()
        for path, ifaces in objects.items():
            if GATT_CHAR_IFACE in ifaces and path.startswith(self._dev_path):
                ch = ifaces[GATT_CHAR_IFACE]
                uuid_v = ch.get("UUID")
                if uuid_v is None:
                    continue
                ch_uuid = str(uuid_v.value).lower()
                if ch_uuid == target_uuid_lower:
                    return path
        return None

    async def _signal_listener(self) -> None:
        """Listen for PropertiesChanged signals (notifications)."""
        if not self._bus:
            return

        # Subscribe to all PropertiesChanged signals
        rule = "interface='org.freedesktop.DBus.Properties',type='signal'"
        try:
            await self._call(
                "/org/freedesktop/DBus", "org.freedesktop.DBus", "AddMatch",
                "s", [rule],
            )
        except Exception:
            pass

        while True:
            try:
                msg = await self._bus.wait_for_message()
                if msg.interface == PROPS_IFACE and msg.member == "PropertiesChanged":
                    iface_name, changed, invalidated = msg.body
                    if iface_name == GATT_CHAR_IFACE and "Value" in changed:
                        data = bytes(changed["Value"].value)
                        self._notification_queue.put_nowait(data)
            except asyncio.CancelledError:
                break
            except Exception:
                break

    async def _discover_gatt_chars(self) -> bool:
        """Retry GATT characteristic lookup until found or timeout.

        Returns ``True`` if both write and notify chars were found.
        """
        for attempt in range(8):
            self._write_path = await self._find_char_by_uuid(WRITE_CHAR_UUID)
            self._notify_path = await self._find_char_by_uuid(NOTIFY_CHAR_UUID)
            if self._write_path and self._notify_path:
                return True
            logger.info("GATT char lookup attempt %d — waiting...", attempt + 1)
            await asyncio.sleep(1.0)
        return False

    async def _run_bluetoothctl_pair(self) -> None:
        """Run ``bluetoothctl pair`` to force a BLE LE connection.

        The pairing process establishes an LE ATT bearer, making the
        GATT characteristic D-Bus objects available for I/O.

        Note: the device must already be discovered (visible in
        ``bluetoothctl devices``) for ``pair <mac>`` to work.
        """
        import subprocess

        logger.info("Re-pairing with %s via bluetoothctl (may need confirmation on watch)...", self._mac)
        pair_proc = await asyncio.create_subprocess_exec(
            "bluetoothctl", "pair", self._mac,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(pair_proc.communicate(), timeout=25.0)
            output = stdout.decode() if stdout else ""
            logger.info("bluetoothctl pair output: %s", output[:200].strip())
        except asyncio.TimeoutError:
            pair_proc.kill()
            logger.warning("bluetoothctl pair timed out — watch may need to be in pairing mode")

        # Update device path after re-pair (it may have changed)
        self._dev_path = await self._find_device()

    async def __aenter__(self) -> DBusGATTTransport:
        await self.connect()
        return self

    async def __aexit__(self, *args) -> None:
        await self.disconnect()
