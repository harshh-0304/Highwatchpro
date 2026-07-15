"""
Low-level BLE packet builder.

Matches ``SendData.java`` protocol construction::

    Byte 0:    0xCD (header)
    Bytes 1-2: (total_length - 3)  as big-endian 16-bit  [via intToBytes + copy range 2..3]
    Byte 3:    main_command
    Byte 4:    0x01 (version)
    Byte 5:    sub_command
    Bytes 6-7: payload_length       as big-endian 16-bit  [via intToBytes + copy range 2..3]
    Bytes 8+:  payload
"""

from __future__ import annotations

from ..utils.bytes import Bytes
from .constants import PACKET_HEADER, PROTOCOL_VERSION


class Packet:
    """
    Immutable representation of a single BLE protocol packet.

    Construction follows the exact byte-for-byte layout produced by
    ``SendData.getProtocol()`` and ``SendData.getNoValueProtocol()``.
    """

    __slots__ = ("_data",)

    def __init__(self, data: bytes | bytearray | memoryview) -> None:
        self._data = bytes(data)  # defensive copy

    # ------------------------------------------------------------------
    # Public factory methods
    # ------------------------------------------------------------------

    @classmethod
    def with_payload(
        cls,
        main_cmd: int,
        sub_cmd: int,
        payload: bytes = b"",
    ) -> "Packet":
        """Build a packet with a payload body.

        Corresponds to ``SendData.getProtocol()``::

            Integer length = getLength() + payload.length;        // 8 + N
            byte[] buf = new byte[length];
            buf[0] = (byte)0xCD;
            byte[] lenField = ByteUtil.intToBytes(length - 3);    // big-endian 4
            System.arraycopy(lenField, 2, buf, 1, 2);             // keep last 2 bytes
            buf[3] = main_cmd;
            buf[4] = 0x01;                                        // version
            buf[5] = sub_cmd;
            byte[] plenField = ByteUtil.intToBytes(payload.length);
            System.arraycopy(plenField, 2, buf, 6, 2);
            System.arraycopy(payload, 0, buf, 8, payload.length);
        """
        total_length = 8 + len(payload)  # header(3) + main(1) + ver(1) + sub(1) + plen(2) + payload
        length_field = total_length - 3  # what goes into bytes 1-2

        buf = bytearray(total_length)
        buf[0] = PACKET_HEADER
        # length field: big-endian 16-bit from low 2 bytes of intToBytes
        len_bytes = Bytes.int_to_bytes_big(length_field)
        buf[1:3] = len_bytes[2:]
        buf[3] = main_cmd & 0xFF
        buf[4] = PROTOCOL_VERSION
        buf[5] = sub_cmd & 0xFF
        # payload length field: same treatment
        plen_bytes = Bytes.int_to_bytes_big(len(payload))
        buf[6:8] = plen_bytes[2:]
        buf[8:] = payload

        return cls(buf)

    @classmethod
    def no_payload(cls, main_cmd: int, sub_cmd: int) -> "Packet":
        """Build a packet with **no** payload body.

        Corresponds to ``SendData.getNoValueProtocol()``::

            Integer length = getLength();            // always 8
            byte[] buf = new byte[length];
            buf[0] = (byte)0xCD;
            byte[] lenField = ByteUtil.intToBytes(length - 3);
            System.arraycopy(lenField, 2, buf, 1, 2);
            buf[3] = main_cmd;
            buf[4] = 0x01;
            buf[5] = sub_cmd;
        """
        return cls.with_payload(main_cmd, sub_cmd, b"")

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def data(self) -> bytes:
        """Raw packet bytes ready for BLE write."""
        return self._data

    @property
    def main_command(self) -> int:
        return self._data[3]

    @property
    def sub_command(self) -> int:
        return self._data[5]

    @property
    def payload(self) -> bytes:
        """Extract payload bytes (everything after the 8-byte header)."""
        return self._data[8:]

    @property
    def length(self) -> int:
        """Total packet length."""
        return len(self._data)

    # ------------------------------------------------------------------
    # Hex dump helpers
    # ------------------------------------------------------------------

    def hex(self, sep: str = " ") -> str:
        """Hex string representation e.g. ``"CD 00 05 1F 01 02 00 00"``."""
        return Bytes.bytes_to_hex_string(self._data, sep)

    def __repr__(self) -> str:
        return (
            f"Packet(main=0x{self.main_command:02X}, sub=0x{self.sub_command:02X}, "
            f"len={self.length}, payload={self.payload.hex()})"
        )

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Packet):
            return self._data == other._data
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._data)

    # ------------------------------------------------------------------
    # Parsing responses from the watch
    # ------------------------------------------------------------------

    @staticmethod
    def parse_response(data: bytes) -> dict:
        """Parse a raw response byte string from the watch into a structured dict.

        Returns
        -------
        dict with keys:
            ``header``, ``length``, ``main_cmd``, ``version``,
            ``sub_cmd``, ``payload_length``, ``payload``, ``is_valid``
        """
        result: dict = {
            "header": None,
            "length": None,
            "main_cmd": None,
            "version": None,
            "sub_cmd": None,
            "payload_length": None,
            "payload": b"",
            "is_valid": False,
        }

        if len(data) < 8:
            return result

        if data[0] != PACKET_HEADER:
            return result

        result["header"] = data[0]
        # Length field is bytes[1:3] big-endian → actual length = field + 3
        field_len = Bytes.int_from_bytes_be_short(data[1:3])
        result["length"] = field_len + 3
        result["main_cmd"] = data[3]
        result["version"] = data[4]
        result["sub_cmd"] = data[5]
        plen = Bytes.int_from_bytes_be_short(data[6:8])
        result["payload_length"] = plen
        result["payload"] = data[8 : 8 + plen] if plen > 0 else b""
        result["is_valid"] = True
        return result
