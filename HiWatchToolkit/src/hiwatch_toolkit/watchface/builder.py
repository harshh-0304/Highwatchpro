"""
Assembles the complete watch face binary from its components.

Replicates the file-assembly logic in ``WatchThemeTools.startFile()``.

Assembly order (matches Java code)::

    if thumbnail_exists:
        mFileData = thumbnail_data                   # prepended
    if has_font:
        mFileData += font_data                       # middle
    mFileData += image_data                          # appended
"""

from __future__ import annotations

from typing import Optional

from PIL import Image

from ..converter import WatchFacePipeline
from ..utils.bytes import Bytes
from .models import WatchFaceFormat, WatchFaceMetadata, ThumbnailConfig


class WatchFaceBuilder:
    """
    Assembles a watch face binary ready for BLE transfer.

    Usage::

        builder = WatchFaceBuilder(image, width=240, height=240)
        builder.set_font(font_bytes)
        builder.set_thumbnail(percent=25)
        binary, meta = builder.build(algorithm=WatchFaceFormat.STANDARD)
    """

    def __init__(
        self,
        image: Image.Image,
        width: int,
        height: int,
        name: str = "Untitled",
    ) -> None:
        self._image = image
        self._width = width
        self._height = height
        self._name = name
        self._font_bytes: Optional[bytes] = None
        self._thumb_config: Optional[ThumbnailConfig] = None
        self._source_path: str = ""

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_font(self, font_data: bytes) -> WatchFaceBuilder:
        """Embed a custom font binary."""
        self._font_bytes = bytes(font_data)
        return self

    def set_thumbnail(self, percent: int = 25, round_angle: int = 0) -> WatchFaceBuilder:
        """Enable thumbnail generation."""
        self._thumb_config = ThumbnailConfig(percent=percent, round_angle=round_angle)
        return self

    def set_source_path(self, path: str) -> WatchFaceBuilder:
        """Record the original source image path (for metadata)."""
        self._source_path = path
        return self

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, algorithm: WatchFaceFormat = WatchFaceFormat.STANDARD) -> tuple[bytes, WatchFaceMetadata]:
        """Assemble the watch face binary.

        Returns
        -------
        tuple of ``(binary_blob, metadata)``.
        """
        pipeline = WatchFacePipeline(self._image, self._width, self._height)

        # 1. Generate image data in the requested format
        strip = algorithm != WatchFaceFormat.BIT8
        image_data = pipeline.to_watch_format(
            algorithm=algorithm.value,
            strip_header=strip,
        )

        # 2. Optionally prepend thumbnail
        thumb_data = b""
        if self._thumb_config is not None:
            # The Java code converts thumbnail for algorithm 2 specially
            thumb_data = pipeline.to_thumbnail_format(
                self._thumb_config.percent,
                algorithm=algorithm.value,
            )

        # 3. Optionally add font data
        font_data = self._font_bytes if self._font_bytes is not None else b""

        # 4. Assemble: thumbnail + font + image
        binary = Bytes.combine(thumb_data, font_data, image_data)

        # 5. Compute metadata
        total_checksum = Bytes.additive_checksum_32(binary)

        meta = WatchFaceMetadata(
            name=self._name,
            width=self._width,
            height=self._height,
            algorithm=algorithm,
            strip_header=strip,
            has_font=self._font_bytes is not None,
            has_thumbnail=self._thumb_config is not None,
            thumb_percent=self._thumb_config.percent if self._thumb_config else 25,
            file_size=len(binary),
            checksum=total_checksum,
            source_image=self._source_path,
        )

        return binary, meta

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @staticmethod
    def compute_finish_payload(file_size: int, checksum: int) -> bytes:
        """Build the 8-byte payload for the BLE ``Finish`` command.

        Matches ``WatchThemeTools.calculateFinishCheckcode()``::

            combine(intToBytes(length), intToBytes(i))  # both big-endian
        """
        return Bytes.int_to_bytes_big(file_size) + Bytes.int_to_bytes_big(checksum)
