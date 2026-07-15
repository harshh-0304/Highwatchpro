"""
Local watch face gallery — save, load, duplicate, delete, export.

Each watch face is stored as two files in the gallery directory::

    {gallery_dir}/
        {uid}.bin       # assembled binary
        {uid}.json      # metadata (WatchFaceMetadata serialised)
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import List, Optional

from ..utils.bytes import Bytes
from .models import WatchFaceMetadata


class WatchFaceGallery:
    """Manages the local watch face gallery on disk."""

    def __init__(self, gallery_dir: str | os.PathLike) -> None:
        self._dir = Path(gallery_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def directory(self) -> Path:
        return self._dir

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def save(self, binary: bytes, meta: WatchFaceMetadata) -> Path:
        """Persist a watch face to the gallery.

        Writes ``{uid}.bin`` and ``{uid}.json``.  Returns the path to
        the ``.bin`` file.
        """
        bin_path = self._dir / f"{meta.uid}.bin"
        json_path = self._dir / f"{meta.uid}.json"

        bin_path.write_bytes(binary)
        json_path.write_text(json.dumps(meta.to_dict(), indent=2))

        return bin_path

    def load_binary(self, uid: str) -> Optional[bytes]:
        """Read the binary data for a stored watch face."""
        path = self._dir / f"{uid}.bin"
        if not path.exists():
            return None
        return path.read_bytes()

    def load_metadata(self, uid: str) -> Optional[WatchFaceMetadata]:
        """Read the metadata for a stored watch face."""
        path = self._dir / f"{uid}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return WatchFaceMetadata.from_dict(data)

    def list_all(self) -> List[WatchFaceMetadata]:
        """Return metadata for every watch face in the gallery."""
        results: List[WatchFaceMetadata] = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(path.read_text())
                results.append(WatchFaceMetadata.from_dict(data))
            except (json.JSONDecodeError, KeyError):
                continue  # skip corrupt entries
        return results

    def delete(self, uid: str) -> bool:
        """Remove a watch face from the gallery.  Returns ``True`` if
        anything was deleted."""
        removed = False
        for ext in (".bin", ".json"):
            path = self._dir / f"{uid}{ext}"
            if path.exists():
                path.unlink()
                removed = True
        return removed

    def duplicate(self, uid: str, new_name: str) -> Optional[WatchFaceMetadata]:
        """Clone an existing watch face with a new name.

        Returns the new metadata (or ``None`` if the original is missing).
        """
        old_meta = self.load_metadata(uid)
        binary = self.load_binary(uid)
        if old_meta is None or binary is None:
            return None

        import uuid
        new_meta = WatchFaceMetadata(
            uid=uuid.uuid4().hex[:12],
            name=new_name,
            width=old_meta.width,
            height=old_meta.height,
            algorithm=old_meta.algorithm,
            strip_header=old_meta.strip_header,
            has_font=old_meta.has_font,
            has_thumbnail=old_meta.has_thumbnail,
            thumb_percent=old_meta.thumb_percent,
            file_size=old_meta.file_size,
            checksum=old_meta.checksum,
            source_image=old_meta.source_image,
        )
        self.save(binary, new_meta)
        return new_meta

    def export_binary(self, uid: str, dest_path: str | os.PathLike) -> Optional[Path]:
        """Export a ``.bin`` file to an arbitrary location."""
        binary = self.load_binary(uid)
        if binary is None:
            return None
        dest = Path(dest_path)
        dest.write_bytes(binary)
        return dest

    # ------------------------------------------------------------------
    # Integrity
    # ------------------------------------------------------------------

    def verify_checksum(self, uid: str) -> bool:
        """Verify that the stored binary's additive checksum matches the
        metadata.  Returns ``True`` if OK or missing."""
        meta = self.load_metadata(uid)
        binary = self.load_binary(uid)
        if meta is None or binary is None:
            return False
        return Bytes.additive_checksum_32(binary) == meta.checksum
