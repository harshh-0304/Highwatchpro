"""
Human-readable names for HiWatch protocol command IDs.

Used by the :class:`PacketDebugger` to annotate every transmitted and
received packet with the command/subcommand meaning.
"""

from __future__ import annotations

from .constants import (
    CMD_SETTING,
    CMD_SPORT,
    CMD_DIAL_UPDATE,
    CMD_DIAL_READ,
    CMD_FILE,
    CMD_FILE_RESPONSE,
    CMD_VOICE_CHAT,
    CMD_DEVICE_CONTROL,
    DIAL_FILE,
    DIAL_START,
    DIAL_FINISH,
    DIAL_READ_STATUS,
    DIAL_READ_INFO,
    DIAL_DEVICE_GET,
    SETTING_SYNC_TIME,
    SETTING_ENTER_OTA,
    RESP_ACK_BASE,
    RESP_SUCCESS,
    RESP_CHECK_FAILED,
    RESP_BATTERY_LOW,
    RESP_CHARGE_REQUIRED,
    RESP_OUT_OF_MEMORY,
)

# Pseudo command IDs used internally for non-protocol transactions
CMD_GATT_READ: int = 0xFD
"""Pseudo main command used by the session recorder for GATT reads."""

# ======================================================================
# Main command names
# ======================================================================

MAIN_COMMAND_NAMES: dict[int, str] = {
    CMD_SETTING: "SETTING",
    CMD_SPORT: "SPORT",
    CMD_DIAL_UPDATE: "DIAL_UPDATE",
    CMD_DIAL_READ: "DIAL_READ",
    CMD_FILE: "FILE",
    CMD_FILE_RESPONSE: "FILE_RESPONSE",
    CMD_VOICE_CHAT: "VOICE_CHAT",
    CMD_DEVICE_CONTROL: "DEVICE_CONTROL",
    CMD_GATT_READ: "GATT_READ",
}

# ======================================================================
# Sub-command names  (keyed by main command ID)
# ======================================================================

SUB_COMMAND_NAMES: dict[int, dict[int, str]] = {
    CMD_DIAL_UPDATE: {
        DIAL_FILE: "FILE_CHUNK",
        DIAL_START: "START",
        DIAL_FINISH: "FINISH",
    },
    CMD_DIAL_READ: {
        DIAL_READ_STATUS: "READ_STATUS",
        DIAL_READ_INFO: "READ_INFO",
        DIAL_DEVICE_GET: "DEVICE_GET",
    },
    CMD_SETTING: {
        SETTING_SYNC_TIME: "SYNC_TIME",
        SETTING_ENTER_OTA: "ENTER_OTA",
    },
    CMD_GATT_READ: {
        0x01: "REQUEST",
        0x02: "RESPONSE",
    },
}

# ======================================================================
# Response code descriptions
# ======================================================================

RESPONSE_DESCRIPTIONS: dict[int, str] = {
    RESP_CHECK_FAILED: "CHECKSUM_ERROR",
    RESP_SUCCESS: "SUCCESS",
    RESP_BATTERY_LOW: "BATTERY_LOW",
    RESP_CHARGE_REQUIRED: "CHARGING",
    RESP_OUT_OF_MEMORY: "OUT_OF_MEMORY",
}


def main_command_name(cmd: int) -> str:
    """Return the human-readable name for a main command ID.

    Returns ``"UNKNOWN_0x{cmd:02X}"`` for unrecognised values.
    """
    return MAIN_COMMAND_NAMES.get(cmd, f"UNKNOWN_0x{cmd:02X}")


def sub_command_name(main_cmd: int, sub_cmd: int) -> str:
    """Return the human-readable name for a sub-command.

    Falls back to ``"0x{sub_cmd:02X}"`` if unknown.
    """
    sub_map = SUB_COMMAND_NAMES.get(main_cmd)
    if sub_map is None:
        return f"0x{sub_cmd:02X}"
    return sub_map.get(sub_cmd, f"0x{sub_cmd:02X}")


def response_code_name(code: int) -> str:
    """Return a short description for a response code."""
    if code >= RESP_ACK_BASE:
        return f"ACK_{code - RESP_ACK_BASE}"
    return RESPONSE_DESCRIPTIONS.get(code, f"CODE_{code}")
