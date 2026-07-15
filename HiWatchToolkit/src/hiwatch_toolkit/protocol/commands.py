"""
High-level command builders.

Each function constructs a :class:`Packet` for a specific operation,
matching the corresponding ``SendData.get*Value()`` method from the app.
"""

from __future__ import annotations

import struct
import time as _time

from ..utils.bytes import Bytes
from .constants import (
    CMD_DIAL_UPDATE,
    CMD_DIAL_READ,
    CMD_SETTING,
    DIAL_START,
    DIAL_FILE,
    DIAL_FINISH,
    DIAL_READ_STATUS,
    DIAL_READ_INFO,
    SETTING_SYNC_TIME,
    SETTING_ENTER_OTA,
)
from .packet import Packet


# ======================================================================
# Dial (watch face) commands
# ======================================================================


def build_dial_start(
    font_position: int,
    is_custom: bool,
    bg_r: int = 0xFF,
    bg_g: int = 0xFF,
    bg_b: int = 0xFF,
    replace_pic_pos: int | None = None,
) -> Packet:
    """Build the **Start** command for a dial update transfer.

    Matches ``SendData.getDialUpdateStartValue()`` — two overloads::

        // With replacePicPos (when pictureNums > 0):
        getProtocol(0x1F, 0x02, combine({fontPos, customFlag}, {R, G, B}, {picPos}))

        // Without replacePicPos:
        getProtocol(0x1F, 0x02, combine({fontPos, customFlag}, {R, G, B}))

    Parameters
    ----------
    font_position:
        Font index on the watch (0 = default).
    is_custom:
        ``True`` for a custom theme (has separate font data),
        ``False`` for a fixed/stock theme.
    bg_r, bg_g, bg_b:
        Background colour bytes. The app sends ``Color.red(-1)`` etc.,
        which evaluates to ``0xFF`` for white.
    replace_pic_pos:
        Optional picture-slot index (only sent when ``pictureNums > 0``).
    """
    custom_flag = 0x01 if is_custom else 0x00
    payload = bytes([font_position & 0xFF, custom_flag, bg_r & 0xFF, bg_g & 0xFF, bg_b & 0xFF])

    if replace_pic_pos is not None:
        payload += bytes([replace_pic_pos & 0xFF])

    return Packet.with_payload(CMD_DIAL_UPDATE, DIAL_START, payload)


def build_dial_file_chunk(
    sequence_number: int,
    chunk_data: bytes,
) -> Packet:
    """Build a **File Data** chunk for dial update.

    Matches ``WatchThemeTools.sendFileData()``::

        combine(shortToBytes(sendNum + 1), chunkData)
        → then wrapped in getDialUpdateFileValue()

    The packet payload is::

        [seq_num:2 big-endian] [chunk_data:N] [checksum:2 big-endian]

    where ``checksum = sum(seq_num + chunk_data) & 0xFFFF``.
    """
    seq_bytes = Bytes.short_to_bytes_big(sequence_number & 0xFFFF)
    body = seq_bytes + chunk_data
    cksum = Bytes.additive_checksum_16(body)
    cksum_bytes = Bytes.short_to_bytes_big(cksum)

    payload = body + cksum_bytes
    return Packet.with_payload(CMD_DIAL_UPDATE, DIAL_FILE, payload)


def build_dial_finish(total_file_size: int, total_checksum: int) -> Packet:
    """Build the **Finish** command for a dial update.

    Matches ``WatchThemeTools.calculateFinishCheckcode()``::

        combine(intToBytes(length), intToBytes(i))

    where both fields are **big-endian 32-bit** values.

    The packet payload is::

        [total_file_size:4 big-endian] [total_checksum:4 big-endian]
    """
    payload = Bytes.int_to_bytes_big(total_file_size & 0xFFFFFFFF)
    payload += Bytes.int_to_bytes_big(total_checksum & 0xFFFFFFFF)
    return Packet.with_payload(CMD_DIAL_UPDATE, DIAL_FINISH, payload)


# ======================================================================
# Dial read / status commands
# ======================================================================


def build_dial_read_status() -> Packet:
    """Build a **Read Dial Status** command.

    Matches ``SendData.getDialUpdateStatus()`` → ``getReadDialValue(1)``.
    """
    return Packet.no_payload(CMD_DIAL_READ, DIAL_READ_STATUS)


def build_dial_read_info() -> Packet:
    """Build a **Read Dial Info** command.

    Matches ``SendData.getDialClockInfo()`` → ``getReadDialValue(2)``.
    """
    return Packet.no_payload(CMD_DIAL_READ, DIAL_READ_INFO)


# ======================================================================
# Setting / system commands
# ======================================================================


def build_set_time() -> Packet:
    """Build a **Set Time** command synchronising the phone's current
    UTC time to the watch.

    Matches ``SendData.getSetTimesValue()`` with the packed bitfield::

        uint32 packed =
            ((year - 2000) << 26) |
            (month         << 22) |
            (day           << 17) |
            (hour          << 12) |
            (minute        <<  6) |
            second;
    """
    now = _time.localtime()
    year = now.tm_year
    month = now.tm_mon
    day = now.tm_mday
    hour = now.tm_hour
    minute = now.tm_min
    second = now.tm_sec

    packed = (
        ((year - 2000) << 26)
        | (month << 22)
        | (day << 17)
        | (hour << 12)
        | (minute << 6)
        | second
    )

    payload = struct.pack(">I", packed & 0xFFFFFFFF)
    return Packet.with_payload(CMD_SETTING, SETTING_SYNC_TIME, payload)


def build_enter_ota() -> Packet:
    """Build an **Enter OTA Mode** command.

    Matches ``SendData.getEnterOtaMode()`` → ``getNoValueProtocol(0x12, 0x19)``.
    """
    return Packet.no_payload(CMD_SETTING, SETTING_ENTER_OTA)
