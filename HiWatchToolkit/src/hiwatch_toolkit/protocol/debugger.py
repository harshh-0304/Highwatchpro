"""
BLE Packet Debugger — parse, validate, and display every packet.

For each packet the debugger produces::

    [14:23:05.123] [TX]  Len=12  Main=0x20 (DIAL_READ)  Sub=0x02 (READ_INFO)  OK
      CD 00 09 20 01 02 00 00

Integrity checks:
- Minimum length (8 bytes)
- Header byte ``0xCD``
- Length field matches actual data
- Payload length matches declared value

Malformed packets are logged as ``MALFORMED`` with the specific error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..utils.bytes import Bytes
from .constants import PACKET_HEADER, RESP_ACK_BASE
from .command_names import main_command_name, sub_command_name, response_code_name


@dataclass
class ParsedPacket:
    """Structured result from parsing a raw BLE packet."""

    is_valid: bool = False
    """``True`` if the packet passed all integrity checks."""

    error: str = ""
    """Error description if ``is_valid`` is ``False``."""

    header: int = 0
    length: int = 0
    main_cmd: int = 0
    version: int = 0
    sub_cmd: int = 0
    payload_length: int = 0
    payload: bytes = b""

    main_cmd_name: str = ""
    sub_cmd_name: str = ""

    raw_hex: str = ""
    """Space-separated uppercase hex dump of raw bytes."""


def parse_packet(data: bytes) -> ParsedPacket:
    """Parse and validate a raw BLE packet.

    Parameters
    ----------
    data:
        Raw bytes received from or to be sent to the watch.

    Returns
    -------
    :class:`ParsedPacket` with ``is_valid`` set accordingly.
    """
    result = ParsedPacket(raw_hex=data.hex(" ").upper())

    # --- Minimum length ---
    if len(data) < 8:
        result.error = f"Too short: {len(data)} bytes (need ≥8)"
        return result

    # --- Header byte ---
    if data[0] != PACKET_HEADER:
        result.error = f"Bad header: 0x{data[0]:02X} (expected 0x{PACKET_HEADER:02X})"
        return result

    # --- Parse fixed fields ---
    result.header = data[0]
    field_len = Bytes.int_from_bytes_be_short(data[1:3])
    result.length = field_len + 3
    result.main_cmd = data[3]
    result.version = data[4]
    result.sub_cmd = data[5]
    plen = Bytes.int_from_bytes_be_short(data[6:8])
    result.payload_length = plen

    # --- Length-field consistency ---
    if result.length != len(data):
        result.error = (
            f"Length mismatch: declared={result.length}, actual={len(data)}"
        )
        return result

    # --- Payload-length consistency ---
    actual_payload_len = len(data) - 8
    if plen > actual_payload_len:
        result.error = (
            f"Payload length mismatch: declared={plen}, available={actual_payload_len}"
        )
        return result

    result.payload = data[8 : 8 + plen]

    # --- Resolve names ---
    result.main_cmd_name = main_command_name(result.main_cmd)
    result.sub_cmd_name = sub_command_name(result.main_cmd, result.sub_cmd)

    result.is_valid = True
    return result


@dataclass
class LoggedPacket:
    """A fully formatted packet ready for display."""

    timestamp: str = ""
    direction: str = "RX"  # "TX" | "RX"
    length: int = 0
    main_cmd: int = 0
    main_cmd_name: str = ""
    sub_cmd: int = 0
    sub_cmd_name: str = ""
    payload_summary: str = ""
    status: str = "OK"
    raw_hex: str = ""
    parsed: ParsedPacket = field(default_factory=ParsedPacket)


def format_packet(
    data: bytes,
    direction: str = "RX",
) -> LoggedPacket:
    """Parse and format a packet into a structured log entry.

    Parameters
    ----------
    data:
        Raw bytes.
    direction:
        ``"TX"`` or ``"RX"``.

    Returns
    -------
    :class:`LoggedPacket` with all fields populated.
    """
    parsed = parse_packet(data)
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]

    entry = LoggedPacket(
        timestamp=ts,
        direction=direction,
        length=len(data),
        raw_hex=data.hex(" ").upper(),
        parsed=parsed,
    )

    if not parsed.is_valid:
        entry.status = f"MALFORMED: {parsed.error}"
        return entry

    entry.main_cmd = parsed.main_cmd
    entry.main_cmd_name = parsed.main_cmd_name
    entry.sub_cmd = parsed.sub_cmd
    entry.sub_cmd_name = parsed.sub_cmd_name

    # Build a short payload summary
    if parsed.payload_length == 0:
        entry.payload_summary = "(no payload)"
    elif parsed.payload_length <= 8:
        entry.payload_summary = parsed.payload.hex(" ").upper()
    else:
        entry.payload_summary = (
            parsed.payload[:8].hex(" ").upper() + f" … ({parsed.payload_length} bytes)"
        )

    return entry


def format_packet_line(entry: LoggedPacket) -> str:
    """Render a :class:`LoggedPacket` into a single human-readable log line.

    Example output::

        [14:23:05.123] [TX]  Len=12  Main=0x20 (DIAL_READ)  Sub=0x02 (READ_INFO)  OK
          CD 00 09 20 01 02 00 00

    Malformed::

        [14:23:05.123] [RX]  MALFORMED: Bad header: 0xAB (expected 0xCD)
          00 00 00 00 00 00 00 00
    """
    if not entry.parsed.is_valid:
        return (
            f"[{entry.timestamp}] [{entry.direction}]  {entry.status}\n"
            f"  {entry.raw_hex}"
        )

    return (
        f"[{entry.timestamp}] [{entry.direction}]  "
        f"Len={entry.length}  "
        f"Main=0x{entry.main_cmd:02X} ({entry.main_cmd_name})  "
        f"Sub=0x{entry.sub_cmd:02X} ({entry.sub_cmd_name})  "
        f"{entry.status}\n"
        f"  {entry.raw_hex}"
    )
