"""
BLE device scanner — discovers HiWatch Pro devices.

Filters by:
- Advertised name matching patterns ("HiWatch", "Watch", "Pro")
- Service UUID matching the UART service (``6e400001-...``)
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from ..protocol.constants import UART_SERVICE_UUID


@dataclass
class WatchDeviceInfo:
    """Discovered watch device."""

    name: str
    """Advertised BLE name."""

    address: str
    """MAC address (or D地址 on Android)."""

    rssi: int
    """Signal strength in dBm (from advertisement data)."""

    device: BLEDevice = field(repr=False)
    """Underlying ``Bleak`` device object."""

    @property
    def display_name(self) -> str:
        return f"{self.name} ({self.address})"


class WatchScanner:
    """
    Scans for HiWatch Pro BLE devices.

    Usage::

        scanner = WatchScanner()
        devices = await scanner.scan(timeout=5.0)
        for d in devices:
            print(d.display_name, d.rssi)
    """

    # Name patterns the watch advertises under
    _NAME_PATTERNS: List[re.Pattern] = [
        re.compile(r"HiWatch", re.IGNORECASE),
        re.compile(r"Watch", re.IGNORECASE),
        re.compile(r"Ultra", re.IGNORECASE),
        re.compile(r"Smart.*Watch", re.IGNORECASE),
        re.compile(r"iwo", re.IGNORECASE),
        re.compile(r"fitpro", re.IGNORECASE),
        re.compile(r"band", re.IGNORECASE),
    ]

    def __init__(self) -> None:
        self._found: List[WatchDeviceInfo] = []

    # ------------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------------

    async def scan(self, timeout: float = 5.0) -> List[WatchDeviceInfo]:
        """Scan for ``timeout`` seconds and return discovered devices."""

        def _callback(device: BLEDevice, adv: AdvertisementData) -> None:
            if self._is_watch(device, adv):
                # Update or append
                rssi_val: int = adv.rssi if adv.rssi is not None else -100
                for i, existing in enumerate(self._found):
                    if existing.address == device.address:
                        self._found[i] = WatchDeviceInfo(
                            name=device.name or adv.local_name or "Unknown",
                            address=device.address,
                            rssi=rssi_val,
                            device=device,
                        )
                        return
                self._found.append(
                    WatchDeviceInfo(
                        name=device.name or adv.local_name or "Unknown",
                        address=device.address,
                        rssi=rssi_val,
                        device=device,
                    )
                )

        self._found.clear()
        scanner = BleakScanner(detection_callback=_callback)
        await scanner.start()
        await asyncio.sleep(timeout)
        await scanner.stop()

        return list(self._found)

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    @classmethod
    def _is_watch(cls, device: BLEDevice, adv: AdvertisementData) -> bool:
        """Heuristic to detect hiwatch devices."""
        name = (device.name or adv.local_name or "").lower()
        if not name:
            return False

        # Check name pattern
        for pat in cls._NAME_PATTERNS:
            if pat.search(name):
                return True

        # Check service UUID
        if UART_SERVICE_UUID.lower() in [s.lower() for s in adv.service_uuids]:
            return True

        return False

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @staticmethod
    async def scan_one(timeout: float = 5.0) -> Optional[WatchDeviceInfo]:
        """Scan and return the first device found (or ``None``)."""
        scanner = WatchScanner()
        devices = await scanner.scan(timeout)
        return devices[0] if devices else None
