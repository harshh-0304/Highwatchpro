"""
24-bit Windows BMP writer.

Matches ``BitmapConverter.java`` exactly::

    Bitmap → 24-bit BMP file (BGR byte order, bottom-up rows,
    row padding to 4-byte boundary with 0xFF filler bytes).
"""

from __future__ import annotations

import struct
from io import BytesIO
from typing import List, Optional

from PIL import Image


class BMPWriter24:
    """
    Creates a byte-exact 24-bit Windows BMP from a PIL ``Image``.

    The output matches what ``BitmapConverter.convert()`` produces for
    ``BitmapFormat.BITMAP_24_BIT_COLOR``::

        Offset  Size  Field
        ------  ----  -----
        0       2     Signature "BM"
        2       4     File size (little-endian)
        6       4     Reserved (zeros)
        10      4     Pixel data offset = 54
        14      4     Info header size = 40
        18      4     Width (little-endian)
        22      4     Height (little-endian)
        26      2     Planes = 1
        28      2     Bits per pixel = 24
        30      4     Compression = 0
        34      4     Image data size
        38      4     H-res (0)
        42      4     V-res (0)
        46      4     Colors used = 0
        50      4     Important colors = 0
        54      N     Pixel data (BGR, bottom-up, padded rows)
    """

    FILE_HEADER_SIZE = 14
    INFO_HEADER_SIZE = 40
    BITS_PER_PIXEL = 24
    BYTES_PER_PIXEL = 3
    PAD_BYTE = 0xFF  # The BitmapConverter uses -1 (0xFF) for padding

    def __init__(self, image: Image.Image) -> None:
        if image.mode != "RGB":
            image = image.convert("RGB")
        self._image = image
        self._width, self._height = image.size

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write(self) -> bytes:
        """Produce the complete 24-bit BMP as ``bytes``."""
        buf = BytesIO()
        self._write_file_header(buf)
        self._write_info_header(buf)
        self._write_pixels(buf)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _write_le16(buf: BytesIO, value: int) -> None:
        buf.write(struct.pack("<H", value & 0xFFFF))

    @staticmethod
    def _write_le32(buf: BytesIO, value: int) -> None:
        buf.write(struct.pack("<I", value & 0xFFFFFFFF))

    def _padded_row_size(self) -> int:
        """Byte count per row including padding to 4-byte boundary.

        ``rowWidthInBytes = bytePerPixel * width``
        ``if rowWidthInBytes % 4 != 0 → pad with 0xFF to next multiple of 4``
        """
        raw = self.BYTES_PER_PIXEL * self._width
        if raw % 4 == 0:
            return raw
        return raw + (4 - (raw % 4))

    def _pixel_data_size(self) -> int:
        return self._padded_row_size() * self._height

    def _write_file_header(self, buf: BytesIO) -> None:
        """``writeFileHeader()`` in BitmapConverter.java."""
        file_size = self.FILE_HEADER_SIZE + self.INFO_HEADER_SIZE + self._pixel_data_size()
        buf.write(b"BM")  # signature
        self._write_le32(buf, file_size)
        self._write_le32(buf, 0)  # reserved
        self._write_le32(buf, 54)  # pixel offset

    def _write_info_header(self, buf: BytesIO) -> None:
        """``writeInfoHeader()`` in BitmapConverter.java.

        Note the off-by-one width adjustment when padding == 3 bytes.
        """
        padded = self._padded_row_size()
        raw_row = self.BYTES_PER_PIXEL * self._width
        pad_bytes = padded - raw_row

        # If padding is exactly 3 bytes, the Java code adds 1 to width.
        # This is a quirk of the original BitmapConverter.
        adjusted_width = self._width
        if pad_bytes == 3:
            adjusted_width += 1

        self._write_le32(buf, self.INFO_HEADER_SIZE)
        self._write_le32(buf, adjusted_width)
        self._write_le32(buf, self._height)
        self._write_le16(buf, 1)  # planes
        self._write_le16(buf, self.BITS_PER_PIXEL)
        self._write_le32(buf, 0)  # compression
        self._write_le32(buf, self._pixel_data_size())
        # BIOS settings: the original uses R2.id.parent for h/v resolution (= 0x1F400 = 128000)
        # but practically these can be 0 for our purposes.
        self._write_le32(buf, 0)  # h-res
        self._write_le32(buf, 0)  # v-res
        self._write_le32(buf, 0)  # colors used (0 = all)
        self._write_le32(buf, 0)  # important colors

    def _write_pixels(self, buf: BytesIO) -> None:
        """``writeImageData()`` in BitmapConverter.java.

        Writes rows **bottom-up** (BMP convention), each pixel as BGR,
        with padding bytes after each row.

        The Java code loops::

            for (int y = height - 1; y >= 0; y--)
                for (int x = 0; x < width; x++)
                    writePixel(pixel[x + y * width])
                writePadding()
        """
        pixels = list(self._image.getdata())  # type: List[tuple]
        padded = self._padded_row_size()
        raw_row = self.BYTES_PER_PIXEL * self._width
        pad_count = padded - raw_row

        for y in range(self._height - 1, -1, -1):
            row_start = y * self._width
            for x in range(self._width):
                r, g, b = pixels[row_start + x]
                buf.write(bytes([b, g, r]))  # BGR order
            # Padding
            if pad_count > 0:
                buf.write(bytes([self.PAD_BYTE] * pad_count))
