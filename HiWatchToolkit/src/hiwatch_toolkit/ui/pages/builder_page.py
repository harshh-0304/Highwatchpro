"""
Page 2: Watch Face Builder — Import PNG, crop, resize, preview, convert.
"""

from __future__ import annotations

import os
from typing import Optional

from PIL import Image
from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...converter import WatchFacePipeline
from ...watchface import WatchFaceBuilder, WatchFaceFormat, WatchFaceMetadata


class ConvertWorker(QObject):
    """Converts image to watch format in a background thread."""

    finished = Signal(bytes, dict)  # binary_data, metadata dict
    progress = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        image_path: str,
        width: int,
        height: int,
        algorithm: int,
        font_path: Optional[str] = None,
        thumb_percent: int = 0,
        name: str = "Untitled",
    ) -> None:
        super().__init__()
        self._image_path = image_path
        self._width = width
        self._height = height
        self._algorithm = algorithm
        self._font_path = font_path
        self._thumb_percent = thumb_percent
        self._name = name

    @Slot()
    def run(self) -> None:
        try:
            self.progress.emit("Loading image...")
            img = Image.open(self._image_path).convert("RGB")

            self.progress.emit(f"Resizing to {self._width}×{self._height}...")
            img = img.resize((self._width, self._height), Image.Resampling.LANCZOS)

            self.progress.emit("Building watch face...")
            builder = WatchFaceBuilder(img, self._width, self._height, name=self._name)
            builder.set_source_path(self._image_path)

            if self._font_path and os.path.exists(self._font_path):
                with open(self._font_path, "rb") as f:
                    builder.set_font(f.read())

            if self._thumb_percent > 0:
                builder.set_thumbnail(percent=self._thumb_percent)

            binary, meta = builder.build(algorithm=WatchFaceFormat(self._algorithm))

            self.progress.emit(
                f"Done — {len(binary)} bytes, checksum 0x{meta.checksum:08X}"
            )
            self.finished.emit(binary, meta.to_dict())

        except Exception as exc:
            self.error.emit(str(exc))


class BuilderPage(QWidget):
    """Watch face builder page."""

    face_built = Signal(bytes, dict)
    """Emitted with (binary_data, metadata_dict) when conversion completes."""

    def __init__(self) -> None:
        super().__init__()
        self._image_path: Optional[str] = None
        self._convert_thread: Optional[QThread] = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("Watch Face Builder")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        subtitle = QLabel("Import an image, configure dimensions, and convert to watch format")
        subtitle.setObjectName("infoLabel")
        layout.addWidget(subtitle)

        # --- Source image ---
        src_group = QGroupBox("Source Image")
        src_layout = QHBoxLayout(src_group)

        self._import_btn = QPushButton("Import PNG...")
        self._import_btn.clicked.connect(self._import_image)
        src_layout.addWidget(self._import_btn)

        self._src_label = QLabel("No file selected")
        self._src_label.setObjectName("infoLabel")
        src_layout.addWidget(self._src_label, 1)

        src_layout.addStretch()
        layout.addWidget(src_group)

        # --- Preview ---
        preview_group = QGroupBox("Preview")
        preview_layout = QVBoxLayout(preview_group)
        self._preview_label = QLabel()
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumHeight(160)
        self._preview_label.setMaximumHeight(320)
        self._preview_label.setStyleSheet(
            "background-color: #f0f0f0; border-radius: 8px; padding: 8px;"
        )
        preview_layout.addWidget(self._preview_label)
        layout.addWidget(preview_group)

        # --- Configuration ---
        config_group = QGroupBox("Configuration")
        config_form = QFormLayout(config_group)

        self._name_input = QLineEdit("My Watch Face")
        config_form.addRow("Name:", self._name_input)

        self._width_input = QSpinBox()
        self._width_input.setRange(64, 640)
        self._width_input.setValue(240)
        self._width_input.setSingleStep(2)
        config_form.addRow("Width:", self._width_input)

        self._height_input = QSpinBox()
        self._height_input.setRange(64, 640)
        self._height_input.setValue(240)
        self._height_input.setSingleStep(2)
        config_form.addRow("Height:", self._height_input)

        self._algorithm_combo = QComboBox()
        self._algorithm_combo.addItem("Standard RGB565", 0)
        self._algorithm_combo.addItem("Yizhaowei", 2)
        self._algorithm_combo.addItem("8-bit Dial", 3)
        config_form.addRow("Format:", self._algorithm_combo)

        self._thumb_input = QSpinBox()
        self._thumb_input.setRange(0, 100)
        self._thumb_input.setValue(25)
        self._thumb_input.setSuffix(" %")
        config_form.addRow("Thumbnail:", self._thumb_input)

        layout.addWidget(config_group)

        # --- Font ---
        font_group = QGroupBox("Custom Font (optional)")
        font_layout = QHBoxLayout(font_group)

        self._font_btn = QPushButton("Select Font .bin...")
        self._font_btn.setObjectName("secondaryButton")
        self._font_btn.clicked.connect(self._select_font)
        font_layout.addWidget(self._font_btn)

        self._font_label = QLabel("No font selected")
        self._font_label.setObjectName("infoLabel")
        font_layout.addWidget(self._font_label, 1)

        layout.addWidget(font_group)

        # --- Actions ---
        action_layout = QHBoxLayout()
        self._convert_btn = QPushButton("Convert to Watch Format")
        self._convert_btn.clicked.connect(self._start_convert)
        self._convert_btn.setEnabled(False)
        action_layout.addWidget(self._convert_btn)

        self._save_btn = QPushButton("Save Project")
        self._save_btn.setObjectName("secondaryButton")
        self._save_btn.setEnabled(False)
        action_layout.addWidget(self._save_btn)
        action_layout.addStretch()

        layout.addLayout(action_layout)

        self._status_label = QLabel("")
        self._status_label.setObjectName("statusLabel")
        layout.addWidget(self._status_label)

        layout.addStretch()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _import_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Image", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if not path:
            return
        self._image_path = path
        self._src_label.setText(os.path.basename(path))
        self._convert_btn.setEnabled(True)

        # Show preview
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            scaled = pixmap.scaledToWidth(320, Qt.TransformationMode.SmoothTransformation)
            self._preview_label.setPixmap(scaled)

    def _select_font(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Font Binary", "", "Binary (*.bin);;All Files (*)"
        )
        if path:
            self._font_label.setText(os.path.basename(path))
            self._font_path = path
        else:
            self._font_path = None
            self._font_label.setText("No font selected")

    def _start_convert(self) -> None:
        if not self._image_path:
            return

        self._convert_btn.setEnabled(False)
        self._status_label.setText("Converting...")

        font_path: Optional[str] = getattr(self, "_font_path", None)
        thumb_pct = self._thumb_input.value()
        alg = self._algorithm_combo.currentData()

        self._convert_worker = ConvertWorker(
            image_path=self._image_path,
            width=self._width_input.value(),
            height=self._height_input.value(),
            algorithm=alg,
            font_path=font_path,
            thumb_percent=thumb_pct if thumb_pct > 0 else 0,
            name=self._name_input.text(),
        )
        self._convert_thread = QThread()
        self._convert_worker.moveToThread(self._convert_thread)
        self._convert_worker.finished.connect(self._on_convert_finished)
        self._convert_worker.progress.connect(self._on_convert_progress)
        self._convert_worker.error.connect(self._on_convert_error)
        self._convert_thread.started.connect(self._convert_worker.run)
        self._convert_thread.finished.connect(self._convert_thread.deleteLater)
        self._convert_thread.start()

    @Slot(bytes, dict)
    def _on_convert_finished(self, binary: bytes, meta: dict) -> None:
        self._convert_btn.setEnabled(True)
        self._save_btn.setEnabled(True)
        self._status_label.setText(
            f"Ready — {len(binary)} bytes, checksum 0x{meta.get('checksum', 0):08X}"
        )
        self.face_built.emit(binary, meta)

        if self._convert_thread:
            self._convert_thread.quit()
            self._convert_thread = None

    @Slot(str)
    def _on_convert_progress(self, msg: str) -> None:
        self._status_label.setText(msg)

    @Slot(str)
    def _on_convert_error(self, msg: str) -> None:
        self._convert_btn.setEnabled(True)
        self._status_label.setText(f"Error: {msg}")
        if self._convert_thread:
            self._convert_thread.quit()
            self._convert_thread = None
