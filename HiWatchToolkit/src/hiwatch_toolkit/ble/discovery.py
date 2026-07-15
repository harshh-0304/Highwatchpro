"""
BLE service discovery — connect to a device and enumerate every service,
characteristic, and descriptor.

Produces a structured dictionary that can be logged to the UI for
debugging and verification of known UUIDs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.backends.service import BleakGATTServiceCollection

logger = logging.getLogger(__name__)


@dataclass
class CharInfo:
    """Discovered characteristic."""

    uuid: str
    handle: int
    properties: list[str]
    service_uuid: str


@dataclass
class ServiceInfo:
    """Discovered GATT service."""

    uuid: str
    handle: int
    characteristics: list[CharInfo] = field(default_factory=list)


class WatchServiceDiscovery:
    """Connects to a watch and discovers all GATT services/characteristics.

    Usage (standalone)::

        discovery = WatchServiceDiscovery(device)
        services = await discovery.discover()
        await discovery.disconnect()

        for svc in services:
            print(f"Service: {svc.uuid}")
            for ch in svc.characteristics:
                print(f"  Char {ch.uuid}  {ch.properties}")
    """

    # Known service UUID patterns for description
    _KNOWN_SERVICES: dict[str, str] = {
        "6E400001-B5A3-F393-E0A9-E50E24DCCA9D": "UART RX/TX (HiWatch)",
        "00001810-0000-1000-8000-00805F9B34FB": "Dial Update",
        "6E40FF01-B5A3-F393-E0A9-E50E24DCCA9E": "OTA Firmware",
        "00001800-0000-1000-8000-00805F9B34FB": "Generic Access",
        "00001801-0000-1000-8000-00805F9B34FB": "Generic Attribute",
        "0000180A-0000-1000-8000-00805F9B34FB": "Device Information",
        "0000180F-0000-1000-8000-00805F9B34FB": "Battery Service",
    }

    # Known characteristic UUIDs
    _KNOWN_CHARS: dict[str, str] = {
        "6E400002-B5A3-F393-E0A9-E50E24DCCA9D": "UART Write",
        "6E400003-B5A3-F393-E0A9-E50E24DCCA9D": "UART Notify",
        "00002A30-0000-1000-8000-00805F9B34FB": "Dial Control Point",
        "6E40FF02-B5A3-F393-E0A9-E50E24DCCA9E": "OTA Write",
        "6E40FF03-B5A3-F393-E0A9-E50E24DCCA9E": "OTA Notify",
        "00002A00-0000-1000-8000-00805F9B34FB": "Device Name",
        "00002A19-0000-1000-8000-00805F9B34FB": "Battery Level",
        "00002A25-0000-1000-8000-00805F9B34FB": "Serial Number",
        "00002A26-0000-1000-8000-00805F9B34FB": "Firmware Revision",
        "00002A27-0000-1000-8000-00805F9B34FB": "Hardware Revision",
        "00002A28-0000-1000-8000-00805F9B34FB": "Software Revision",
        "00002A29-0000-1000-8000-00805F9B34FB": "Manufacturer Name",
    }

    def __init__(self, device: BLEDevice) -> None:
        self._device = device
        self._client: Optional[BleakClient] = None
        self._services: list[ServiceInfo] = []
        self._service_count: int = 0
        self._char_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def services(self) -> list[ServiceInfo]:
        """Discovered services (populated after :meth:`discover`)."""
        return list(self._services)

    @property
    def service_count(self) -> int:
        return self._service_count

    @property
    def char_count(self) -> int:
        return self._char_count

    async def discover(self, timeout: float = 10.0) -> list[ServiceInfo]:
        """Connect to the device and enumerate all GATT services.

        Returns
        -------
        List of :class:`ServiceInfo` with all discovered characteristics.
        """
        self._client = BleakClient(self._device)
        await self._client.connect(timeout=timeout)
        logger.info("Connected to %s for service discovery", self._device.address)

        # Access services (discovered automatically by the backend during connect)
        services: BleakGATTServiceCollection = self._client.services

        self._services.clear()
        self._service_count = 0
        self._char_count = 0

        for svc_handle, svc in services.services.items():
            svc_uuid = str(svc.uuid).upper()
            svc_desc = self._KNOWN_SERVICES.get(svc_uuid, "")
            self._service_count += 1

            char_list: list[CharInfo] = []
            for char in svc.characteristics:
                char_uuid = str(char.uuid).upper()
                char_desc = self._KNOWN_CHARS.get(char_uuid, "")
                props = sorted(char.properties)
                self._char_count += 1

                char_list.append(
                    CharInfo(
                        uuid=char_uuid,
                        handle=char.handle,
                        properties=props,
                        service_uuid=svc_uuid,
                    )
                )

            self._services.append(
                ServiceInfo(
                    uuid=svc_uuid,
                    handle=svc_handle,
                    characteristics=char_list,
                )
            )

        self._log_discovery()
        return self._services

    async def disconnect(self) -> None:
        """Disconnect from the device."""
        if self._client and self._client.is_connected:
            await self._client.disconnect()
            logger.info("Disconnected from %s", self._device.address)

    # ------------------------------------------------------------------
    # Format helpers
    # ------------------------------------------------------------------

    def format_service_table(self) -> str:
        """Return a human-readable string of all discovered services."""
        lines: list[str] = []
        lines.append(f"Service Discovery: {self._device.name} ({self._device.address})")
        lines.append(f"Total: {self._service_count} service(s), {self._char_count} characteristic(s)")
        lines.append("")

        for svc in self._services:
            svc_desc = self._KNOWN_SERVICES.get(svc.uuid, "")
            tag = f"  // {svc_desc}" if svc_desc else ""
            lines.append(f"Service  {svc.uuid}  (handle=0x{svc.handle:04X}){tag}")

            for ch in svc.characteristics:
                ch_desc = self._KNOWN_CHARS.get(ch.uuid, "")
                props = " + ".join(p.upper().replace("-", "_") for p in ch.properties)
                tag2 = f"  // {ch_desc}" if ch_desc else ""
                lines.append(
                    f"  Char  {ch.uuid}  "
                    f"handle=0x{ch.handle:04X}  "
                    f"[{props}]{tag2}"
                )
            lines.append("")

        return "\n".join(lines)

    def _log_discovery(self) -> None:
        """Log the discovery results at INFO level."""
        logger.info("=== Service Discovery: %s ===", self._device.name)
        logger.info("Found %d service(s), %d characteristic(s)",
                     self._service_count, self._char_count)
        for svc in self._services:
            svc_desc = self._KNOWN_SERVICES.get(svc.uuid, "")
            logger.info("  Service %s%s", svc.uuid, f" ({svc_desc})" if svc_desc else "")
            for ch in svc.characteristics:
                ch_desc = self._KNOWN_CHARS.get(ch.uuid, "")
                props = ", ".join(ch.properties)
                logger.info("    Char %s [%s]%s",
                            ch.uuid, props, f"  ({ch_desc})" if ch_desc else "")
