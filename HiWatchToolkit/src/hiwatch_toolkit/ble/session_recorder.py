"""
Session Recorder — persists every BLE transaction to a JSON log file.

Each session creates a file at ``logs/session_YYYYMMDD_HHMMSS.json``
containing an array of transaction records::

    {
        "timestamp":   "2026-07-15T14:23:05.123",
        "direction":   "TX",
        "command":     "SETTING",
        "subcommand":  "SYNC_TIME",
        "raw_hex":     "CD 00 09 12 01 01 00 04 ...",
        "parsed":      { ... },
        "gatt_uuid":   null,
        "gatt_label":  null,
        "status":      "OK"
    }

GATT characteristic reads (battery, firmware, etc.) are also recorded
with ``direction: "GATT_READ"``, the characteristic UUID, and the raw
hex value.

Usage::

    recorder = SessionRecorder()
    recorder.start()                     # creates file
    recorder.record(entry)               # LoggedPacket or dict
    recorder.record_gatt(uuid, label, value)
    recorder.stop()                      # flushes and closes
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional

from ..protocol.debugger import LoggedPacket, ParsedPacket

logger = logging.getLogger(__name__)

# Default log directory — created under the project root
DEFAULT_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "logs")


def _ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


class SessionRecorder:
    """Records every BLE transaction to a JSON session file.

    The file is written as a JSON array, one object per transaction.
    Entries are appended incrementally (not held in memory) for crash
    resilience.
    """

    def __init__(self, log_dir: str = "") -> None:
        self._log_dir = _ensure_dir(log_dir or DEFAULT_LOG_DIR)
        self._file_path: Optional[str] = None
        self._file_handle = None
        self._first_entry = True
        self._entry_count: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def file_path(self) -> Optional[str]:
        """Full path to the current session file, or ``None`` if not started."""
        return self._file_path

    @property
    def entry_count(self) -> int:
        """Number of transactions recorded in this session."""
        return self._entry_count

    def start(self) -> None:
        """Create a new session file and write the opening ``[``."""
        if self._file_handle is not None:
            logger.warning("SessionRecorder already started — stopping first")
            self.stop()

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._file_path = os.path.join(self._log_dir, f"session_{ts}.json")
        self._file_handle = open(self._file_path, "w", encoding="utf-8")
        self._file_handle.write("[\n")
        self._file_handle.flush()
        self._first_entry = True
        self._entry_count = 0
        logger.info("Session recording started: %s", self._file_path)

    def stop(self) -> None:
        """Write the closing ``]`` and close the file."""
        if self._file_handle is None:
            return
        try:
            self._file_handle.write("\n]\n")
            self._file_handle.flush()
            self._file_handle.close()
        except Exception as exc:
            logger.warning("Error closing session file: %s", exc)
        finally:
            self._file_handle = None
            logger.info(
                "Session recording stopped: %s (%d entries)",
                self._file_path,
                self._entry_count,
            )

    def __del__(self) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(self, entry: LoggedPacket) -> None:
        """Record a parsed BLE packet (TX/RX).

        Parameters
        ----------
        entry:
            A :class:`LoggedPacket` produced by :func:`format_packet`.
        """
        if self._file_handle is None:
            return
        obj = self._logged_packet_to_dict(entry)
        self._write_entry(obj)

    def record_gatt(
        self,
        uuid: str,
        label: str,
        value: Optional[bytearray],
        success: bool = True,
    ) -> None:
        """Record a GATT characteristic read.

        Parameters
        ----------
        uuid:
            Full characteristic UUID.
        label:
            Human-readable label (e.g. ``"Battery Level"``).
        value:
            Raw value bytes, or ``None`` if the read failed.
        success:
            Whether the read succeeded.
        """
        if self._file_handle is None:
            return
        obj = {
            "timestamp": datetime.now().isoformat(timespec="milliseconds"),
            "direction": "GATT_READ",
            "gatt_uuid": uuid,
            "gatt_label": label,
            "success": success,
            "raw_hex": (value.hex(" ").upper() if value else ""),
            "raw_bytes": list(value) if value else [],
        }
        self._write_entry(obj)

    def record_custom(self, direction: str, data: dict) -> None:
        """Record an arbitrary transaction (e.g. connection events).

        Parameters
        ----------
        direction:
            ``"CONNECT"``, ``"DISCONNECT"``, etc.
        data:
            Arbitrary key-value pairs to include.
        """
        if self._file_handle is None:
            return
        obj = {
            "timestamp": datetime.now().isoformat(timespec="milliseconds"),
            "direction": direction,
            **data,
        }
        self._write_entry(obj)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_entry(self, obj: dict) -> None:
        if self._file_handle is None:
            return
        try:
            sep = "\n" if self._first_entry else ",\n"
            self._first_entry = False
            self._file_handle.write(sep + json.dumps(obj, indent=2, default=str))
            self._file_handle.flush()
            self._entry_count += 1
        except Exception as exc:
            logger.warning("Failed to write session entry: %s", exc)

    @staticmethod
    def _logged_packet_to_dict(entry: LoggedPacket) -> dict:
        parsed = entry.parsed
        return {
            "timestamp": datetime.now().isoformat(timespec="milliseconds"),
            "direction": entry.direction,
            "length": entry.length,
            "main_cmd": entry.main_cmd,
            "main_cmd_name": entry.main_cmd_name,
            "sub_cmd": entry.sub_cmd,
            "sub_cmd_name": entry.sub_cmd_name,
            "payload_summary": entry.payload_summary,
            "status": entry.status,
            "raw_hex": entry.raw_hex,
            "parsed": {
                "is_valid": parsed.is_valid,
                "error": parsed.error if not parsed.is_valid else "",
                "header": parsed.header,
                "length": parsed.length,
                "main_cmd": parsed.main_cmd,
                "main_cmd_name": parsed.main_cmd_name,
                "sub_cmd": parsed.sub_cmd,
                "sub_cmd_name": parsed.sub_cmd_name,
                "payload_length": parsed.payload_length,
                "payload_hex": parsed.payload.hex(" ").upper() if parsed.payload else "",
            },
        }
