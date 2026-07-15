"""
Protocol constants matching ``Profile.java`` and ``SendData.java``.

All values are derived directly from the decompiled HiWatch Pro Android
application to ensure bit-exact protocol compatibility.
"""

from __future__ import annotations

import uuid as _uuid

# ======================================================================
# Packet envelope
# ======================================================================

PACKET_HEADER: int = 0xCD
"""Leading byte of every packet sent to the watch."""

PROTOCOL_VERSION: int = 0x01
"""Version byte (always 1 in the app)."""

# ======================================================================
# Main command IDs  (Profile.PBSmartBandCommandId)
# ======================================================================

CMD_SETTING: int = 0x12  # 18
"""Main command: Settings (time, alarms, user info, etc.)."""

CMD_SPORT: int = 0x15  # 21
"""Main command: Sport / activity data."""

CMD_DIAL_UPDATE: int = 0x1F  # 31
"""Main command: Watch face (dial) update transfer."""

CMD_DIAL_READ: int = 0x20  # 32
"""Main command: Read dial info / status from watch."""

CMD_FILE: int = 0x22  # 34
"""Main command: Generic file transfer."""

CMD_FILE_RESPONSE: int = 0x23  # 35
"""Main command: File transfer response status."""

CMD_VOICE_CHAT: int = 0x24  # 36
"""Main command: Voice chat data."""

CMD_DEVICE_CONTROL: int = 0x1C  # 28
"""Main command: Device control (camera, find phone, etc.)."""

# ======================================================================
# Dial update sub-commands  (PBSmartBandCommandIdDialUpdateKeyId)
# ======================================================================

DIAL_FILE: int = 0x01
"""Sub-command: Upload a file chunk during dial update."""

DIAL_START: int = 0x02
"""Sub-command: Start dial update transfer."""

DIAL_FINISH: int = 0x03
"""Sub-command: Finish / finalize dial update."""

# ======================================================================
# Dial read sub-commands  (PBSmartBandCommandIdDialReadKeyId)
# ======================================================================

DIAL_READ_STATUS: int = 0x01
"""Sub-command: Read dial update status / progress."""

DIAL_READ_INFO: int = 0x02
"""Sub-command: Read dial info (resolution, algorithm, config)."""

DIAL_DEVICE_GET: int = 0x03
"""Sub-command: Get device control response."""

# ======================================================================
# Setting sub-commands  (PBSmartBandCommandIdSettingKeyId)
# ======================================================================

SETTING_SYNC_TIME: int = 0x01
"""Sub-command: Synchronise phone time to watch."""

SETTING_ENTER_OTA: int = 0x19  # 25
"""Sub-command: Enter OTA firmware-upgrade mode."""

# ======================================================================
# Watch response codes  (parsed in WatchThemeTools.response())
# ======================================================================

RESP_ACK_BASE: int = 1000
"""Base ACK: watch acknowledges packet ``N`` when response == 1000 + N."""

RESP_CHECK_FAILED: int = 1
"""Checksum error – chunk needs to be resent."""

RESP_SUCCESS: int = 2
"""Transfer completed successfully."""

RESP_BATTERY_LOW: int = 3
"""Battery too low to perform dial update."""

RESP_CHARGE_REQUIRED: int = 4
"""Device is currently charging — cannot update."""

RESP_OUT_OF_MEMORY: int = 5
"""Insufficient memory on watch."""

# ======================================================================
# BLE UUIDs  (from Profile.java / strings)
# ======================================================================

UART_SERVICE_UUID: str = "6e400801-b5a3-f393-e0a9-e50e24dcca9d"
"""Primary UART-like BLE service for command/response.

Note: The Android APK's ``Profile.java`` hard-codes ``6e400001``, but the
Ultra3 watch actually advertises ``6e400801``. Both variants use the same
write/notify characteristic UUIDs (6e400002/6e400003).
"""

UART_WRITE_CHAR_UUID: str = "6e400002-b5a3-f393-e0a9-e50e24dcca9d"
"""Write characteristic (phone → watch)."""

UART_NOTIFY_CHAR_UUID: str = "6e400003-b5a3-f393-e0a9-e50e24dcca9d"
"""Notify characteristic (watch → phone)."""

UART_NOTIFY_CCCD_UUID: str = "00002902-0000-1000-8000-00805f9b34fb"
"""CCCD for enabling notifications on the notify characteristic."""

UART_WRITE_ALIPAY_CHAR_UUID: str = "6e400005-b5a3-f393-e0a9-e50e24dcca9d"
"""Secondary write characteristic (AliPay)."""

OTA_SERVICE_UUID: str = "6E40FF01-B5A3-F393-E0A9-E50E24DCCA9E"
"""BLE service used during OTA firmware upgrade mode."""

OTA_WRITE_CHAR_UUID: str = "6E40FF02-B5A3-F393-E0A9-E50E24DCCA9E"
"""OTA write characteristic."""

OTA_NOTIFY_CHAR_UUID: str = "6E40FF03-B5A3-F393-E0A9-E50E24DCCA9E"
"""OTA notify characteristic."""

DIAL_SERVICE_UUID: str = "00001810-0000-1000-8000-00805f9b34fb"
"""Alternative dial-update service (some firmware versions)."""

DIAL_CHAR_UUID: str = "00002a30-0000-1000-8000-00805f9b34fb"
"""Alternative dial-update characteristic (read/write/notify)."""

# ======================================================================
# Standard GATT service/characteristic UUIDs used by the watch
# (from Beken library and Bluetooth SIG)
# ======================================================================

BATTERY_SERVICE_UUID: str = "0000180f-0000-1000-8000-00805f9b34fb"
"""Battery Service (standard)."""

BATTERY_LEVEL_CHAR_UUID: str = "00002a19-0000-1000-8000-00805f9b34fb"
"""Battery Level characteristic (standard)."""

DEVICE_INFO_SERVICE_UUID: str = "0000180a-0000-1000-8000-00805f9b34fb"
"""Device Information Service (standard)."""

FIRMWARE_REVISION_CHAR_UUID: str = "00002a26-0000-1000-8000-00805f9b34fb"
"""Firmware Revision String characteristic (standard)."""

SOFTWARE_REVISION_CHAR_UUID: str = "00002a28-0000-1000-8000-00805f9b34fb"
"""Software Revision String characteristic (standard) — used for device function flags."""

DEVICE_NAME_CHAR_UUID: str = "00002a2a-0000-1000-8000-00805f9b34fb"
"""Vendor-specific device name characteristic (0x2A2A, used by Beken chips)."""

MANUFACTURER_NAME_CHAR_UUID: str = "00002a29-0000-1000-8000-00805f9b34fb"
"""Manufacturer Name String characteristic (standard GATT)."""

MODEL_NUMBER_CHAR_UUID: str = "00002a24-0000-1000-8000-00805f9b34fb"
"""Model Number String characteristic (standard GATT)."""

# ======================================================================
# Convenience: UUID objects for Bleak
# ======================================================================

UART_SERVICE = _uuid.UUID(UART_SERVICE_UUID)
UART_WRITE_CHAR = _uuid.UUID(UART_WRITE_CHAR_UUID)
UART_NOTIFY_CHAR = _uuid.UUID(UART_NOTIFY_CHAR_UUID)
UART_NOTIFY_CCCD = _uuid.UUID(UART_NOTIFY_CCCD_UUID)
OTA_SERVICE = _uuid.UUID(OTA_SERVICE_UUID)
OTA_WRITE_CHAR = _uuid.UUID(OTA_WRITE_CHAR_UUID)
OTA_NOTIFY_CHAR = _uuid.UUID(OTA_NOTIFY_CHAR_UUID)
DIAL_SERVICE = _uuid.UUID(DIAL_SERVICE_UUID)
DIAL_CHAR = _uuid.UUID(DIAL_CHAR_UUID)
