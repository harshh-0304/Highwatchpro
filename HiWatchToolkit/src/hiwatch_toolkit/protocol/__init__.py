"""HiWatch Toolkit - BLE Protocol implementation."""

from .constants import (
    # Header / envelope
    PACKET_HEADER,
    PROTOCOL_VERSION,
    # Main command IDs
    CMD_SETTING,
    CMD_SPORT,
    CMD_DIAL_UPDATE,
    CMD_DIAL_READ,
    CMD_FILE,
    CMD_FILE_RESPONSE,
    CMD_VOICE_CHAT,
    CMD_DEVICE_CONTROL,
    # Dial update sub-commands
    DIAL_FILE,
    DIAL_START,
    DIAL_FINISH,
    # Dial read sub-commands
    DIAL_READ_STATUS,
    DIAL_READ_INFO,
    DIAL_DEVICE_GET,
    # Setting sub-commands
    SETTING_SYNC_TIME,
    SETTING_ENTER_OTA,
    # Response codes
    RESP_ACK_BASE,
    RESP_CHECK_FAILED,
    RESP_SUCCESS,
    RESP_BATTERY_LOW,
    RESP_CHARGE_REQUIRED,
    RESP_OUT_OF_MEMORY,
    # BLE UUIDs
    UART_SERVICE_UUID,
    UART_WRITE_CHAR_UUID,
    UART_NOTIFY_CHAR_UUID,
    UART_NOTIFY_CCCD_UUID,
    OTA_SERVICE_UUID,
    OTA_WRITE_CHAR_UUID,
    OTA_NOTIFY_CHAR_UUID,
)
from .packet import Packet
from .commands import (
    build_dial_start,
    build_dial_file_chunk,
    build_dial_finish,
    build_dial_read_status,
    build_dial_read_info,
    build_set_time,
    build_enter_ota,
)
from .command_names import main_command_name, sub_command_name, response_code_name
from .debugger import parse_packet, format_packet, format_packet_line

__all__ = [
    # Constants
    "PACKET_HEADER",
    "PROTOCOL_VERSION",
    "CMD_SETTING",
    "CMD_SPORT",
    "CMD_DIAL_UPDATE",
    "CMD_DIAL_READ",
    "CMD_FILE",
    "CMD_FILE_RESPONSE",
    "CMD_VOICE_CHAT",
    "CMD_DEVICE_CONTROL",
    "DIAL_FILE",
    "DIAL_START",
    "DIAL_FINISH",
    "DIAL_READ_STATUS",
    "DIAL_READ_INFO",
    "DIAL_DEVICE_GET",
    "SETTING_SYNC_TIME",
    "SETTING_ENTER_OTA",
    "RESP_ACK_BASE",
    "RESP_CHECK_FAILED",
    "RESP_SUCCESS",
    "RESP_BATTERY_LOW",
    "RESP_CHARGE_REQUIRED",
    "RESP_OUT_OF_MEMORY",
    "UART_SERVICE_UUID",
    "UART_WRITE_CHAR_UUID",
    "UART_NOTIFY_CHAR_UUID",
    "UART_NOTIFY_CCCD_UUID",
    "OTA_SERVICE_UUID",
    "OTA_WRITE_CHAR_UUID",
    "OTA_NOTIFY_CHAR_UUID",
    # Classes
    "Packet",
    # Command builders
    "build_dial_start",
    "build_dial_file_chunk",
    "build_dial_finish",
    "build_dial_read_status",
    "build_dial_read_info",
    "build_set_time",
    "build_enter_ota",
    # Debugger
    "main_command_name",
    "sub_command_name",
    "response_code_name",
    "parse_packet",
    "format_packet",
    "format_packet_line",
]
