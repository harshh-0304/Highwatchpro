"""
Data models for watch face metadata and configuration.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Optional


class WatchFaceFormat(IntEnum):
    """Conversion algorithm matching ``ClockDialInfoBody.algorithm``."""

    STANDARD = 0
    """Standard RGB565 big-endian (algorithm 0)."""

    BEKEN = 1
    """Beken chip-specific format (algorithm 1)."""

    YIZHAOWEI = 2
    """Yizhaowei with 10-byte header (algorithm 2)."""

    BIT8 = 3
    """8-bit dial (algorithm 3)."""


@dataclass
class ThumbnailConfig:
    """Thumbnail generation parameters."""

    percent: int = 25
    """Scale percentage (10–100)."""

    round_angle: int = 0
    """Rounded-corner radius in pixels (0 = disabled)."""

    def thumb_width(self, full_width: int) -> int:
        w = int(full_width * (self.percent / 100.0)) + 1
        if w % 2 != 0:
            w += 1
        return w

    def thumb_height(self, full_height: int) -> int:
        return int(full_height * (self.percent / 100.0))


@dataclass
class WatchFaceMetadata:
    """Serialisable metadata for a watch face in the gallery."""

    uid: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    """Unique identifier (used as filename stem)."""

    name: str = "Untitled"
    """Display name."""

    width: int = 240
    """Watch display width in pixels."""

    height: int = 240
    """Watch display height in pixels."""

    algorithm: WatchFaceFormat = WatchFaceFormat.STANDARD
    """Conversion format."""

    strip_header: bool = True
    """Whether the BMP header was stripped (config bit 0)."""

    has_font: bool = False
    """``True`` if a custom font binary is embedded."""

    has_thumbnail: bool = False
    """``True`` if a thumbnail is prepended."""

    thumb_percent: int = 25
    """Thumbnail scale percentage."""

    file_size: int = 0
    """Total size of the assembled binary in bytes."""

    checksum: int = 0
    """32-bit additive checksum of the assembled binary."""

    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    """ISO-8601 creation timestamp."""

    source_image: str = ""
    """Path to the original source image (optional)."""

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "algorithm": self.algorithm.value,
            "strip_header": self.strip_header,
            "has_font": self.has_font,
            "has_thumbnail": self.has_thumbnail,
            "thumb_percent": self.thumb_percent,
            "file_size": self.file_size,
            "checksum": self.checksum,
            "created": self.created,
            "source_image": self.source_image,
        }

    @classmethod
    def from_dict(cls, data: dict) -> WatchFaceMetadata:
        return cls(
            uid=data.get("uid", uuid.uuid4().hex[:12]),
            name=data.get("name", "Untitled"),
            width=data.get("width", 240),
            height=data.get("height", 240),
            algorithm=WatchFaceFormat(data.get("algorithm", 0)),
            strip_header=data.get("strip_header", True),
            has_font=data.get("has_font", False),
            has_thumbnail=data.get("has_thumbnail", False),
            thumb_percent=data.get("thumb_percent", 25),
            file_size=data.get("file_size", 0),
            checksum=data.get("checksum", 0),
            created=data.get("created", datetime.now().isoformat(timespec="seconds")),
            source_image=data.get("source_image", ""),
        )
