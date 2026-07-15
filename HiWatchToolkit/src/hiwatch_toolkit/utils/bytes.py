"""
Byte-level utility primitives.

Mirrors the endianness conversions from xfkj.fitpro.utils.NumberUtils
to ensure bit-exact compatibility with the watch BLE protocol.
"""

from __future__ import annotations

import struct
from typing import ClassVar


class Bytes:
    """
    Static utility for byte conversions matching the Java NumberUtils signatures.

    All methods return ``bytes`` objects (not lists or mutable bytearrays) so
    callers can safely hash or concatenate them without defensive copies.
    """

    # ------------------------------------------------------------------
    # Short (16-bit)
    # ------------------------------------------------------------------

    @staticmethod
    def short_to_bytes_big(value: int) -> bytes:
        """Big-endian uint16 → ``bytes(2)``.

        Matches ``NumberUtils.shortToBytes()``::

            return {(byte)(s >> 8), (byte)(s & 0xFF)}
        """
        return struct.pack(">H", value & 0xFFFF)

    @staticmethod
    def short_to_bytes_little(value: int) -> bytes:
        """Little-endian uint16 → ``bytes(2)``.

        Matches ``NumberUtils.shortToBytesLittle()``::

            return {(byte)(s & 0xFF), (byte)(s >> 8)}
        """
        return struct.pack("<H", value & 0xFFFF)

    # ------------------------------------------------------------------
    # Integer (32-bit)
    # ------------------------------------------------------------------

    @staticmethod
    def int_to_bytes_big(value: int) -> bytes:
        """Big-endian int32 → ``bytes(4)``.

        Matches the first overload of ``NumberUtils.intToBytes()``::

            for i in range(4):
                bArr[i] = (byte)(value >>> (24 - i * 8))
        """
        return struct.pack(">I", value & 0xFFFFFFFF)

    @staticmethod
    def int_to_bytes_little(value: int) -> bytes:
        """Little-endian int32 → ``bytes(4)``.

        Matches ``NumberUtils.intToBytes_Little()``::

            return {(byte)(i & 0xFF), (byte)((i>>8)&0xFF),
                    (byte)((i>>16)&0xFF), (byte)((i>>24)&0xFF)}
        """
        return struct.pack("<I", value & 0xFFFFFFFF)

    @staticmethod
    def int_to_bytes_be_short(value: int) -> bytes:
        """Big-endian int32, keep only **bytes[2..3]** → ``bytes(2)``.

        This matches the pattern used in ``SendData.getProtocol()`` where
        ``ByteUtil.intToBytes(length)`` is computed (4 bytes big-endian) but
        only the *last two* bytes are copied into the packet at offset 1::

            bArrIntToBytes = ByteUtil.intToBytes(numValueOf.intValue() - 3);
            System.arraycopy(bArrIntToBytes, 2, bArr2, 1, 2);
        """
        raw = struct.pack(">I", value & 0xFFFFFFFF)
        return raw[2:]  # keep low 16 bits in big-endian order

    @staticmethod
    def int_from_bytes_be_short(data: bytes) -> int:
        """Inverse of :meth:`int_to_bytes_be_short`."""
        return struct.unpack(">H", data)[0]

    # ------------------------------------------------------------------
    # Long (64-bit)
    # ------------------------------------------------------------------

    @staticmethod
    def long_to_bytes_big(value: int) -> bytes:
        """Big-endian uint64 → ``bytes(8)``."""
        return struct.pack(">Q", value & 0xFFFFFFFFFFFFFFFF)

    @staticmethod
    def long_to_bytes_little(value: int) -> bytes:
        """Little-endian uint64 → ``bytes(8)``."""
        return struct.pack("<Q", value & 0xFFFFFFFFFFFFFFFF)

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def bytes_to_int_big(data: bytes) -> int:
        """Big-endian bytes (up to 4) → int."""
        return int.from_bytes(data, "big", signed=False)

    @staticmethod
    def bytes_to_int_little(data: bytes) -> int:
        """Little-endian bytes (up to 4) → int."""
        return int.from_bytes(data, "little", signed=False)

    @staticmethod
    def bytes_to_short_big(data: bytes) -> int:
        """Big-endian bytes(2) → int."""
        return struct.unpack(">H", data)[0]

    @staticmethod
    def bytes_to_short_little(data: bytes) -> int:
        """Little-endian bytes(2) → int."""
        return struct.unpack("<H", data)[0]

    # ------------------------------------------------------------------
    # Checksum (matches WatchThemeTools.calculateCheckcode)
    # ------------------------------------------------------------------

    @staticmethod
    def additive_checksum_16(data: bytes) -> int:
        """16-bit additive checksum: sum of all bytes masked to uint16.

        Matches::

            short s = 0;
            for (byte b : bArr)  s = (short)(s + (b & 0xFF));
            return NumberUtils.shortToBytes(s);   // stored big-endian
        """
        return sum(data) & 0xFFFF

    @staticmethod
    def additive_checksum_32(data: bytes) -> int:
        """32-bit additive checksum: sum of all bytes masked to uint32.

        Matches::

            int i = 0;
            for (byte b : mFileData)  i += (short)(b & 0xFF);
            return NumberUtils.combineBytes(
                NumberUtils.intToBytes(length),
                NumberUtils.intToBytes(i)
            );
        """
        return sum(data) & 0xFFFFFFFF

    # ------------------------------------------------------------------
    # Combine (variadic concat)
    # ------------------------------------------------------------------

    @staticmethod
    def combine(*chunks: bytes) -> bytes:
        """Concatenate zero or more byte buffers.

        Matches ``NumberUtils.combineBytes(byte[]...)`` which sums lengths
        and copies each array in declaration order.
        """
        return b"".join(chunks)

    # ------------------------------------------------------------------
    # Hex / text helpers (matching ConvertUtils / ByteUtil)
    # ------------------------------------------------------------------

    HEX_DIGITS: ClassVar[str] = "0123456789ABCDEF"

    @staticmethod
    def hex_string_to_bytes(hex_str: str) -> bytes:
        """``"1601"`` → ``b'\\x16\\x01'``."""
        return bytes.fromhex(hex_str)

    @staticmethod
    def bytes_to_hex_string(data: bytes, sep: str = "") -> str:
        """``b'\\x16\\x01'`` → ``"1601"``."""
        return data.hex(sep).upper()

    # ------------------------------------------------------------------
    # Bitfield access (matching NumberUtils.intToBinary)
    # ------------------------------------------------------------------

    @staticmethod
    def get_bit(value: int, bit_index: int) -> int:
        """Extract bit ``bit_index`` (0 = LSB) from ``value``.

        Matches ``NumberUtils.intToBinary(config)[bit_index]``.
        """
        return (value >> bit_index) & 1
