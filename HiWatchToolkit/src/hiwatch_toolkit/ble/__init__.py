"""HiWatch Toolkit - BLE communication layer (via Bleak)."""

from .scanner import WatchScanner, WatchDeviceInfo
from .connection import WatchConnection, ConnectionState
from .device_client import WatchDeviceClient
from .transfer import WatchFaceTransfer, TransferProgress, TransferState, TransferError
from .discovery import WatchServiceDiscovery, ServiceInfo, CharInfo
from .session_recorder import SessionRecorder

__all__ = [
    "WatchScanner",
    "WatchDeviceInfo",
    "WatchConnection",
    "ConnectionState",
    "WatchDeviceClient",
    "WatchFaceTransfer",
    "TransferProgress",
    "TransferState",
    "TransferError",
    "WatchServiceDiscovery",
    "ServiceInfo",
    "CharInfo",
    "SessionRecorder",
]
