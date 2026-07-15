"""
Page 4: Gallery — Browse, inspect, and manage locally saved watch faces.

Each watch face is stored as a ``{uid}.bin`` + ``{uid}.json`` pair in a
gallery directory (default ``~/.hiwatch_toolkit/gallery/``).
"""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...watchface import WatchFaceFormat, WatchFaceGallery, WatchFaceMetadata


class GalleryPage(QWidget):
    """Local watch face gallery page."""

    install_requested = Signal(bytes, dict)
    """Emitted when the user clicks **Install** on a stored face."""

    def __init__(self) -> None:
        super().__init__()
        self._gallery_dir = os.path.join(
            os.path.expanduser("~"), ".hiwatch_toolkit", "gallery"
        )
        self._gallery = WatchFaceGallery(self._gallery_dir)
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Title
        title = QLabel("Watch Face Gallery")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        subtitle = QLabel(
            f"Stored in: {self._gallery_dir}"
        )
        subtitle.setObjectName("infoLabel")
        layout.addWidget(subtitle)

        # --- Main content: list + detail side by side ---
        content = QHBoxLayout()
        content.setSpacing(16)

        # Face list
        list_group = QGroupBox("Saved Faces")
        list_layout = QVBoxLayout(list_group)

        self._face_list = QListWidget()
        self._face_list.setMinimumWidth(280)
        self._face_list.itemClicked.connect(self._on_face_selected)
        list_layout.addWidget(self._face_list)

        # List buttons
        list_btn_row = QHBoxLayout()
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setObjectName("secondaryButton")
        self._refresh_btn.clicked.connect(self.refresh)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setObjectName("dangerButton")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete)
        list_btn_row.addWidget(self._refresh_btn)
        list_btn_row.addWidget(self._delete_btn)
        list_btn_row.addStretch()
        list_layout.addLayout(list_btn_row)

        content.addWidget(list_group, stretch=1)

        # Detail panel
        detail_group = QGroupBox("Details")
        detail_layout = QVBoxLayout(detail_group)

        detail_fields = [
            ("Name:", "_detail_name"),
            ("Dimensions:", "_detail_dims"),
            ("Format:", "_detail_format"),
            ("Size:", "_detail_size"),
            ("Checksum:", "_detail_checksum"),
            ("Created:", "_detail_created"),
            ("Thumbnail:", "_detail_thumb"),
            ("Font:", "_detail_font"),
        ]
        self._detail_labels: dict[str, QLabel] = {}
        for label_text, attr_name in detail_fields:
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setObjectName("infoLabel")
            lbl.setFixedWidth(90)
            val = QLabel("—")
            val.setObjectName("valueLabel")
            val.setWordWrap(True)
            setattr(self, attr_name, val)
            self._detail_labels[label_text] = val
            row.addWidget(lbl)
            row.addWidget(val, 1)
            detail_layout.addLayout(row)

        detail_layout.addStretch()

        # Detail buttons
        detail_btn_row = QHBoxLayout()
        self._install_btn = QPushButton("Install to Watch")
        self._install_btn.setEnabled(False)
        self._install_btn.clicked.connect(self._on_install)
        self._export_btn = QPushButton("Export...")
        self._export_btn.setObjectName("secondaryButton")
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._on_export)
        detail_btn_row.addWidget(self._install_btn)
        detail_btn_row.addWidget(self._export_btn)
        detail_btn_row.addStretch()
        detail_layout.addLayout(detail_btn_row)

        content.addWidget(detail_group, stretch=1)

        layout.addLayout(content, stretch=1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Reload the face list from the gallery directory."""
        self._face_list.clear()
        self._clear_detail()
        self._selected_meta: Optional[WatchFaceMetadata] = None
        self._install_btn.setEnabled(False)
        self._export_btn.setEnabled(False)
        self._delete_btn.setEnabled(False)

        faces = self._gallery.list_all()
        if not faces:
            item = QListWidgetItem("(empty — build a face first)")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            item.setForeground(Qt.GlobalColor.gray)
            self._face_list.addItem(item)
            return

        for meta in faces:
            text = f"{meta.name}  —  {meta.width}×{meta.height}"
            item = QListWidgetItem(text)
            item.setData(256, meta)
            self._face_list.addItem(item)

    def set_gallery_dir(self, path: str) -> None:
        """Override the default gallery directory."""
        self._gallery_dir = path
        self._gallery = WatchFaceGallery(path)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_face_selected(self, item: QListWidgetItem) -> None:
        meta: WatchFaceMetadata = item.data(256)
        if meta is None:
            return
        self._selected_meta = meta
        self._detail_name.setText(meta.name)
        self._detail_dims.setText(f"{meta.width} × {meta.height}")
        fmt = WatchFaceFormat(meta.algorithm).name.title() if hasattr(WatchFaceFormat, "name") else str(meta.algorithm)
        self._detail_format.setText(fmt)
        self._detail_size.setText(f"{meta.file_size:,} bytes")
        self._detail_checksum.setText(f"0x{meta.checksum:08X}")
        self._detail_created.setText(meta.created)
        self._detail_thumb.setText("Yes" if meta.has_thumbnail else "No")
        self._detail_font.setText("Yes" if meta.has_font else "No")

        self._install_btn.setEnabled(True)
        self._export_btn.setEnabled(True)
        self._delete_btn.setEnabled(True)

    def _clear_detail(self) -> None:
        for lbl in self._detail_labels.values():
            lbl.setText("—")

    def _on_install(self) -> None:
        if self._selected_meta is None:
            return
        uid = self._selected_meta.uid
        binary = self._gallery.load_binary(uid)
        meta = self._gallery.load_metadata(uid)
        if binary is None or meta is None:
            QMessageBox.warning(self, "Error", "Failed to load watch face files.")
            return
        self.install_requested.emit(binary, meta.to_dict())

    def _on_export(self) -> None:
        if self._selected_meta is None:
            return
        uid = self._selected_meta.uid
        meta = self._selected_meta

        default_name = f"{meta.name}.bin"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Watch Face", default_name,
            "Binary (*.bin);;All Files (*)",
        )
        if not path:
            return

        result = self._gallery.export_binary(uid, path)
        if result is None:
            QMessageBox.warning(self, "Error", "Failed to export watch face.")

    def _on_delete(self) -> None:
        if self._selected_meta is None:
            return
        uid = self._selected_meta.uid
        name = self._selected_meta.name

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f'Delete "{name}" from the gallery?\nThis cannot be undone.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._gallery.delete(uid)
        self.refresh()
