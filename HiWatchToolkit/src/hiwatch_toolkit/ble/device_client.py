"""
High-level device client — queries watch info, sends commands, parses responses.

Wraps ``WatchConnection`` with the HiWatch-specific command protocol and
standard GATT characteristic reads (battery, firmware, device name, etc.).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from ..protocol.commands import (
    build_dial_read_info,
    build_set_time,
)
from ..protocol.constants import (
    BATTERY_LEVEL_CHAR_UUID,
    FIRMWARE_REVISION_CHAR_UUID,
    SOFTWARE_REVISION_CHAR_UUID,
    DEVICE_NAME_CHAR_UUID,
    MANUFACTURER_NAME_CHAR_UUID,
    MODEL_NUMBER_CHAR_UUID,
    RESP_ACK_BASE,
)
from ..protocol.packet import Packet
from .connection import WatchConnection, ConnectionState

logger = logging.getLogger(__name__)

# Maximum retries for time synchronisation
_TIME_SYNC_MAX_RETRIES = 3
_TIME_SYNC_TIMEOUT = 5.0


@dataclass
class DeviceInfo:
    """Parsed device information."""

    # — GATT reads —
    battery: int = 0
    """Battery level 0–100 (0 = unknown / read failed)."""

    firmware_version: str = ""
    """Firmware version string (read from ``FIRMWARE_REVISION_CHAR``)."""

    software_revision: str = ""
    """Software revision / device function flags string."""

    device_name: str = ""
    """Device name string."""

    manufacturer_name: str = ""
    """Manufacturer name string."""

    model_number: str = ""
    """Model number string."""

    # — Custom protocol reads (dial info) —
    width: int = 0
    height: int = 0
    algorithm: int = 0
    config: int = 0


class WatchDeviceClient:
    """
    Talks to a HiWatch Pro device using the BLE protocol.

    Usage::

        client = WatchDeviceClient(device)
        await client.connect()
        info = await client.read_device_info()
        print(info.battery)
        ok = await client.sync_time()
        await client.disconnect()
    """

    def __init__(self, device: BLEDevice) -> None:
        self._conn = WatchConnection(device)
        self._notification_handler = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._conn.is_connected

    @property
    def connection(self) -> WatchConnection:
        return self._conn

    async def connect(self, timeout: float = 10.0) -> None:
        await self._conn.connect(timeout=timeout)

    async def disconnect(self) -> None:
        await self._conn.disconnect()

    async def __aenter__(self) -> WatchDeviceClient:
        await self.connect()
        return self

    async def __aexit__(self, *args) -> None:
        await self.disconnect()

    # ------------------------------------------------------------------
    # Device info — GATT characteristic reads
    # ------------------------------------------------------------------

    async def read_device_info(self) -> DeviceInfo:
        """Read all available device information.

        Performs the following reads (all failures are logged and
        silently skipped — never crashes):

        1. GATT characteristic reads (battery, firmware, device name, …)
        2. Custom protocol query for dial info (resolution, algorithm)

        Returns
        -------
        A fully populated :class:`DeviceInfo` — missing fields keep
        their default values.
        """
        info = DeviceInfo()

        # --- GATT reads (all gracefully handle failure) ---
        info.battery = await self._read_battery_level()
        info.firmware_version = await self._read_gatt_string(
            FIRMWARE_REVISION_CHAR_UUID, "Firmware Revision",
        )
        info.software_revision = await self._read_gatt_string(
            SOFTWARE_REVISION_CHAR_UUID, "Software Revision",
        )
        info.device_name = await self._read_gatt_string(
            DEVICE_NAME_CHAR_UUID, "Device Name",
        )
        info.manufacturer_name = await self._read_gatt_string(
            MANUFACTURER_NAME_CHAR_UUID, "Manufacturer Name",
        )
        info.model_number = await self._read_gatt_string(
            MODEL_NUMBER_CHAR_UUID, "Model Number",
        )

        # --- Custom protocol: dial info (resolution, algorithm) ---
        try:
            raw = await self._send_and_wait(build_dial_read_info())
            parsed = Packet.parse_response(bytes(raw))
            if parsed["is_valid"]:
                payload = parsed["payload"]
                if len(payload) >= 8:
                    info.width = int.from_bytes(payload[0:2], "little")
                    info.height = int.from_bytes(payload[2:4], "little")
                    if len(payload) >= 5:
                        info.algorithm = payload[4]
                    if len(payload) >= 9:
                        info.config = int.from_bytes(payload[5:9], "little")
        except Exception as exc:
            logger.warning("Failed to read dial info: %s", exc)

        return info

    # ------------------------------------------------------------------
    # Time synchronisation  (with retry + ACK decoding)
    # ------------------------------------------------------------------

    async def sync_time(
        self,
        max_retries: int = _TIME_SYNC_MAX_RETRIES,
        timeout: float = _TIME_SYNC_TIMEOUT,
    ) -> bool:
        """Send the current system time to the watch.

        Follows the same protocol as ``SDKCmdMannager.synchronTime()``.
        The watch replies with an ACK (response code ``1000 + N``).

        Parameters
        ----------
        max_retries:
            Number of attempts before giving up (default 3).
        timeout:
            Seconds to wait for the ACK per attempt (default 5).

        Returns
        -------
        ``True`` if the watch acknowledged the time sync.
        """
        for attempt in range(1, max_retries + 1):
            try:
                pkt = build_set_time()
                await self._conn.write(pkt.data)

                response = await self._conn.wait_for_notification(timeout=timeout)
                if response is None:
                    logger.warning(
                        "Time sync attempt %d/%d: timeout",
                        attempt,
                        max_retries,
                    )
                    continue

                # Parse response and check for ACK
                if self._is_ack(response):
                    logger.info("Time sync ACK received (attempt %d)", attempt)
                    return True

                # Response came but wasn't an ACK — log code and retry
                code = self._extract_response_code(response)
                logger.warning(
                    "Time sync attempt %d/%d: response code=%s",
                    attempt,
                    max_retries,
                    code,
                )

            except Exception as exc:
                logger.warning(
                    "Time sync attempt %d/%d failed: %s",
                    attempt,
                    max_retries,
                    exc,
                )

        logger.error("Time sync failed after %d attempts", max_retries)
        return False

    # ------------------------------------------------------------------
    # Raw command helpers
    # ------------------------------------------------------------------

    async def send_packet(self, packet: Packet) -> None:
        """Send a protocol packet to the watch."""
        await self._conn.write(packet.data)

    async def send_and_wait(
        self,
        packet: Packet,
        timeout: float = 5.0,
    ) -> Optional[bytearray]:
        """Send a packet and wait for the next notification."""
        await self._conn.write(packet.data)
        return await self._conn.wait_for_notification(timeout=timeout)

    async def _send_and_wait(
        self,
        packet: Packet,
        timeout: float = 5.0,
    ) -> bytearray:
        """Internal version that raises on timeout."""
        result = await self.send_and_wait(packet, timeout=timeout)
        if result is None:
            raise TimeoutError("No response from watch")
        return result

    def set_notification_handler(self, handler):
        """Set a callback for every BLE notification."""
        self._conn.set_notification_handler(handler)

    # ------------------------------------------------------------------
    # Internal — GATT read helpers
    # ------------------------------------------------------------------

    async def _read_battery_level(self) -> int:
        """Read the battery level via GATT. Returns 0 on failure."""
        try:
            value = await self._conn.read_characteristic(
                BATTERY_LEVEL_CHAR_UUID,
                label="Battery Level",
            )
            if value and len(value) >= 1:
                return value[0]
        except Exception as exc:
            logger.debug("Battery read failed: %s", exc)
        return 0

    async def _read_gatt_string(self, uuid: str, label: str) -> str:
        """Read a GATT characteristic that contains an ASCII/UTF-8 string.

        Returns empty string on any failure.
        """
        try:
            value = await self._conn.read_characteristic(uuid, label=label)
            if value:
                return value.decode("utf-8", errors="replace").strip("\x00").strip()
        except Exception as exc:
            logger.debug("GATT string read failed (%s): %s", label, exc)
        return ""

    # ------------------------------------------------------------------
    # Internal — ACK / response decoding
    # ------------------------------------------------------------------

    @staticmethod
    def _is_ack(response: bytearray) -> bool:
        """Check whether a raw notification is an ACK (response >= 1000)."""
        try:
            parsed = Packet.parse_response(bytes(response))
            if not parsed["is_valid"]:
                return False
            payload = parsed["payload"]
            if len(payload) >= 1:
                code = payload[0]
                return code >= RESP_ACK_BASE
            return False
        except Exception:
            return False

    @staticmethod
    def _extract_response_code(response: bytearray) -> str:
        """Extract a human-readable response code string from a notification."""
        try:
            parsed = Packet.parse_response(bytes(response))
            if parsed["is_valid"]:
                payload = parsed["payload"]
                if len(payload) >= 1:
                    code = payload[0]
                    if code >= RESP_ACK_BASE:
                        return f"ACK_{code - RESP_ACK_BASE}"
                    return f"CODE_{code}"
                return "EMPTY_PAYLOAD"
            return f"MALFORMED: {parsed.get('error', 'unknown')}"
        except Exception as exc:
            return f"PARSE_ERROR: {exc}"
