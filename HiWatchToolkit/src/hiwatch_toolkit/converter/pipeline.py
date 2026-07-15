"""
Full watch-face conversion pipeline.

Converts a PIL ``Image`` into watch-native binary format by reading
pixels directly (avoiding the file-based BMP pipeline that would need
row-padding handling).

The reference Java pipeline is::

    Bitmap → 24-bit BMP → native Bmp24ConvertBmp16 → 16-bit BMP
    → getNotHeaderBmp()  [strip 54-byte header]
    → rotatDerection()   [little-endian bottom-up → big-endian top-down]
    → watch-native RGB565

This module implements an equivalent pure-Python pipeline that produces
bit-identical output for the ``rotatDerection`` step.
"""

from __future__ import annotations

from PIL import Image

from .rgb565 import RGB565
from .rotat_derection import rotat_derection


class WatchFacePipeline:
    """
    Converts a PIL ``Image`` into watch-native RGB565 binary data.

    Usage::

        image = Image.open("design.png").convert("RGB")
        pipe = WatchFacePipeline(image, width=240, height=240)
        watch_bin = pipe.to_watch_format(algorithm=0, strip_header=True)
    """

    def __init__(self, image: Image.Image, width: int, height: int) -> None:
        if image.mode != "RGB":
            image = image.convert("RGB")
        self._image = image
        self._width = width
        self._height = height

        if width % 2 != 0:
            raise ValueError(f"Width must be even, got {width}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def to_watch_format(
        self,
        algorithm: int = 0,
        strip_header: bool = True,
    ) -> bytes:
        """Convert image to watch-native binary format.

        Parameters
        ----------
        algorithm:
            ``0`` = standard RGB565 (big-endian, top-down).
            ``1`` = Beken (placeholder — returns 16-bit BMP).
            ``2`` = Yizhaowei (RGB565 + 10-byte prefix header).
            ``3/4`` = 8-bit dial (returns 16-bit BMP as-is).
        strip_header:
            For algorithm 0: ``True`` returns raw big-endian RGB565;
            ``False`` returns a complete 16-bit BMP (header + pixels).

        Returns
        -------
        ``bytes``
            The image data portion of a watch face binary.
        """
        # Step 1: Convert PIL pixels → little-endian RGB565, bottom-up
        # order (matching BMP convention, ready for rotatDerection).
        rgb565_le = self._pixels_to_rgb565_le()

        if algorithm == 2:
            # Yizhaowei: rotatDerection → wrap with 10-byte header
            watch = rotat_derection(self._width, self._height, bytes(rgb565_le))
            return self._yizhaowei_header() + bytes(watch)

        if algorithm == 0 and strip_header:
            # Standard format: rotatDerection → raw big-endian pixels
            return bytes(rotat_derection(self._width, self._height, bytes(rgb565_le)))

        # BMP path (algorithm 0 strip_header=False, or 1/3/4):
        header_16 = self._build_16bit_bmp_header()
        return header_16 + bytes(rgb565_le)

    def to_thumbnail_format(self, thumb_percent: int, algorithm: int = 0) -> bytes:
        """Generate a scaled-down thumbnail in watch-native format.

        The Java code computes::

            thumbWidth  = (int)(width * (percent / 100.0)) + 1
            thumbHeight = (int)(height * (percent / 100.0))
        """
        tw = int(self._width * (thumb_percent / 100.0)) + 1
        th = int(self._height * (thumb_percent / 100.0))
        if tw % 2 != 0:
            tw += 1  # ensure even width for rotatDerection

        thumb = self._image.resize((tw, th), Image.Resampling.LANCZOS)
        sub = WatchFacePipeline(thumb, tw, th)
        return sub.to_watch_format(algorithm=algorithm, strip_header=True)

    # ------------------------------------------------------------------
    # Pixel conversion
    # ------------------------------------------------------------------

    def _pixels_to_rgb565_le(self) -> bytearray:
        """Convert PIL image pixels to tightly-packed little-endian RGB565.

        Row order is **bottom-up** (BMP convention) so the output can be
        fed directly to :func:`rotat_derection`.

        Returns ``bytearray`` of ``width * height * 2`` bytes.
        """
        total = self._width * self._height * 2
        buf = bytearray(total)
        pixels = self._image.load()  # fast pixel accessor
        idx = 0

        # BMP convention: bottom row first in memory
        for y in range(self._height - 1, -1, -1):
            for x in range(self._width):
                r, g, b = pixels[x, y]  # type: ignore[index]
                rgb565 = RGB565.from_rgb8(r, g, b)
                buf[idx] = rgb565 & 0xFF          # low byte (BMP order)
                buf[idx + 1] = (rgb565 >> 8) & 0xFF  # high byte
                idx += 2

        return buf

    # ------------------------------------------------------------------
    # BMP header builder
    # ------------------------------------------------------------------

    def _build_16bit_bmp_header(self) -> bytes:
        """54-byte BMP info header for 16-bit RGB565 data.

        The pixel data (tightly-packed LE RGB565, bottom-up) is appended
        separately.  Width is assumed even, so no row-padding is needed.
        """
        import struct

        row_size = self._width * 2
        padded_row = ((row_size + 3) // 4) * 4
        pixel_data_size = padded_row * self._height
        file_size = 54 + pixel_data_size

        buf = bytearray(54)
        struct.pack_into("<2s", buf, 0, b"BM")
        struct.pack_into("<I", buf, 2, file_size)
        struct.pack_into("<I", buf, 10, 54)  # pixel offset
        struct.pack_into("<I", buf, 14, 40)  # info header size
        struct.pack_into("<i", buf, 18, self._width)
        struct.pack_into("<i", buf, 22, self._height)
        struct.pack_into("<H", buf, 26, 1)   # planes
        struct.pack_into("<H", buf, 28, 16)  # bits per pixel
        struct.pack_into("<I", buf, 34, pixel_data_size)
        return bytes(buf)

    # ------------------------------------------------------------------
    # Yizhaowei header builder
    # ------------------------------------------------------------------

    def _yizhaowei_header(self) -> bytes:
        """10-byte Yizhaowei prefix::

            [0x16, 0x01] + width(LE) + height(LE) + [0x00, 0x00, 0x0A, 0x00]
        """
        import struct

        hdr = bytearray(10)
        hdr[0] = 0x16
        hdr[1] = 0x01
        struct.pack_into("<H", hdr, 2, self._width)
        struct.pack_into("<H", hdr, 4, self._height)
        hdr[6] = 0x00
        hdr[7] = 0x00
        hdr[8] = 0x0A
        hdr[9] = 0x00
        return bytes(hdr)
