"""
RGB565 colour-space conversions.

Bit layout of a 16-bit RGB565 value::

    15 14 13 12 11  10  9  8  7  6  5  4  3  2  1  0
    R4  R3 R2 R1 R0  G5 G4 G3 G2 G1 G0 B4 B3 B2 B1 B0

Standard conversion from 8-bit-per-channel sRGB::

    R5 = (r * 249 + 1014) >> 11      (equivalently r >> 3)
    G6 = (g * 253 + 505)  >> 10      (equivalently g >> 2)
    B5 = (b * 249 + 1014) >> 11      (equivalently b >> 3)
    rgb565 = (R5 << 11) | (G6 << 5) | B5

References
----------
- ``BmpConvertTools.java`` — 24-bit BMP is converted to 16-bit RGB565 by the
  native ``libbmp-lib.so`` library. This module provides a pure-Python
  equivalent of that conversion.
"""

from __future__ import annotations

import struct
from typing import Tuple


class RGB565:
    """Static methods for RGB565 encoding and decoding."""

    # ------------------------------------------------------------------
    # Encoding (24-bit → 16-bit)
    # ------------------------------------------------------------------

    @staticmethod
    def from_rgb8(r: int, g: int, b: int) -> int:
        """Pack separate 8-bit R, G, B channels into a single 16-bit RGB565 value.

        Parameters
        ----------
        r, g, b:
            Channel values in range ``[0, 255]``.

        Returns
        -------
        int
            16-bit value ``0bRRRRR_GGGGGG_BBBBB``.
        """
        r5 = (r * 249 + 1014) >> 11  # equivalent to r >> 3
        g6 = (g * 253 + 505) >> 10  # equivalent to g >> 2
        b5 = (b * 249 + 1014) >> 11  # equivalent to b >> 3
        return (r5 << 11) | (g6 << 5) | b5

    @staticmethod
    def from_rgb8_fast(r: int, g: int, b: int) -> int:
        """Faster variant using bit-shift truncation (same result)."""
        return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

    # ------------------------------------------------------------------
    # Decoding (16-bit → 24-bit)
    # ------------------------------------------------------------------

    @staticmethod
    def to_rgb8(rgb565: int) -> Tuple[int, int, int]:
        """Expand a 16-bit RGB565 value back to 8-bit-per-channel (approximate).

        Uses bit replication to fill the low bits::

            R = (r5 << 3) | (r5 >> 2)
            G = (g6 << 2) | (g6 >> 4)
            B = (b5 << 3) | (b5 >> 2)

        Returns
        -------
        tuple of (r, g, b) each in ``[0, 255]``.
        """
        r5 = (rgb565 >> 11) & 0x1F
        g6 = (rgb565 >> 5) & 0x3F
        b5 = rgb565 & 0x1F
        r = (r5 << 3) | (r5 >> 2)
        g = (g6 << 2) | (g6 >> 4)
        b = (b5 << 3) | (b5 >> 2)
        return r, g, b

    # ------------------------------------------------------------------
    # Byte-order helpers
    # ------------------------------------------------------------------

    @staticmethod
    def to_bytes_le(rgb565: int) -> bytes:
        """RGB565 value → little-endian byte pair (BMP order).

        BMP stores the low byte first::

            byte 0 = (rgb565 & 0xFF)          # low byte
            byte 1 = ((rgb565 >> 8) & 0xFF)   # high byte
        """
        return struct.pack("<H", rgb565 & 0xFFFF)

    @staticmethod
    def to_bytes_be(rgb565: int) -> bytes:
        """RGB565 value → big-endian byte pair (watch-native order).

        The watch expects the high byte first::

            byte 0 = ((rgb565 >> 8) & 0xFF)   # high byte
            byte 1 = (rgb565 & 0xFF)          # low byte
        """
        return struct.pack(">H", rgb565 & 0xFFFF)

    @staticmethod
    def from_bytes_le(data: bytes, offset: int = 0) -> int:
        """Little-endian byte pair → RGB565 value."""
        return struct.unpack_from("<H", data, offset)[0]

    @staticmethod
    def from_bytes_be(data: bytes, offset: int = 0) -> int:
        """Big-endian byte pair → RGB565 value."""
        return struct.unpack_from(">H", data, offset)[0]

    # ------------------------------------------------------------------
    # Bulk conversion
    # ------------------------------------------------------------------

    @staticmethod
    def convert_pixels_rgb8_to_le(pixels: bytes, width: int, height: int) -> bytearray:
        """Convert a flat array of RGB888 bytes (BGR order, bottom-up) to
        little-endian RGB565 bytes.

        This matches the native ``Bmp24ConvertBmp16`` conversion for an
        input 24-bit BMP.

        Parameters
        ----------
        pixels:
            Raw 24-bit BGR pixel data, bottom-up row order,
            tightly packed (3 bytes per pixel, no row padding).
        width, height:
            Image dimensions.

        Returns
        -------
        ``bytearray`` of 16-bit RGB565 in **little-endian** byte order,
        bottom-up row order, tightly packed (2 bytes per pixel).
        """
        out = bytearray(width * height * 2)
        idx = 0
        for py in range(height):
            for px in range(width):
                # BMP byte order at the pixel level: B, G, R
                b = pixels[idx]
                g = pixels[idx + 1]
                r = pixels[idx + 2]
                idx += 3
                rgb565 = RGB565.from_rgb8(r, g, b)
                # Store little-endian (low byte first)
                out[py * width * 2 + px * 2] = rgb565 & 0xFF
                out[py * width * 2 + px * 2 + 1] = (rgb565 >> 8) & 0xFF
        return out
