"""
Page 3: Upload — Transfer watch face binary to a connected HiWatch Pro device.

Follows the same QThread + QObject worker pattern as ConnectPage and
BuilderPage.  The page provides the UI; the actual BLE transfer is
orchestrated by AppController in ``main.py`` via signals and public
methods.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class UploadPage(QWidget):
    """Watch face BLE upload page."""

    transfer_requested = Signal(bytes, dict)
    """Emitted when the user clicks **Start Transfer**."""

    cancel_requested = Signal()
    """Emitted when the user clicks **Cancel**."""

    def __init__(self) -> None:
        super().__init__()
        self._binary: Optional[bytes] = None
        self._metadata: Optional[dict] = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Title
        title = QLabel("Upload Watch Face")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        subtitle = QLabel("Transfer a watch face binary to your connected device")
        subtitle.setObjectName("infoLabel")
        layout.addWidget(subtitle)

        # --- File info ---
        info_group = QGroupBox("Watch Face")
        info_form = QVBoxLayout(info_group)

        fields = [
            ("Name:", "_file_name_label"),
            ("Dimensions:", "_file_dims_label"),
            ("File Size:", "_file_size_label"),
            ("Checksum:", "_file_checksum_label"),
        ]
        self._info_labels: dict[str, QLabel] = {}
        for label_text, attr_name in fields:
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setObjectName("infoLabel")
            lbl.setFixedWidth(100)
            val = QLabel("—")
            val.setObjectName("valueLabel")
            setattr(self, attr_name, val)
            self._info_labels[label_text] = val
            row.addWidget(lbl)
            row.addWidget(val)
            row.addStretch()
            info_form.addLayout(row)

        layout.addWidget(info_group)

        # --- Progress ---
        progress_group = QGroupBox("Transfer Progress")
        progress_layout = QVBoxLayout(progress_group)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        progress_layout.addWidget(self._progress_bar)

        self._status_label = QLabel("No file loaded")
        self._status_label.setObjectName("statusLabel")
        progress_layout.addWidget(self._status_label)

        layout.addWidget(progress_group)

        # --- Actions ---
        action_layout = QHBoxLayout()
        self._start_btn = QPushButton("Start Transfer")
        self._start_btn.setEnabled(False)
        self._start_btn.clicked.connect(self._on_start)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setObjectName("dangerButton")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)
        action_layout.addWidget(self._start_btn)
        action_layout.addWidget(self._cancel_btn)
        action_layout.addStretch()
        layout.addLayout(action_layout)

        # --- Transfer log ---
        log_group = QGroupBox("Transfer Log")
        log_layout = QVBoxLayout(log_group)
        self._log_view = QPlainTextEdit()
        self._log_view.setObjectName("logView")
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumHeight(160)
        log_layout.addWidget(self._log_view)
        layout.addWidget(log_group)

        layout.addStretch()

    # ------------------------------------------------------------------
    # Public API  (called by AppController in main.py)
    # ------------------------------------------------------------------

    def prepare(self, binary: bytes, meta: dict) -> None:
        """Load a watch face binary for transfer and populate the info panel."""
        self._binary = binary
        self._metadata = meta
        self._file_name_label.setText(meta.get("name", "Untitled"))
        dims = f'{meta.get("width", "?")} × {meta.get("height", "?")}'
        self._file_dims_label.setText(dims)
        self._file_size_label.setText(f"{len(binary):,} bytes")
        self._file_checksum_label.setText(f"0x{meta.get('checksum', 0):08X}")
        self._progress_bar.setValue(0)
        self._start_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._status_label.setText("Ready — press Start Transfer")
        self._log_view.clear()

    def update_progress(self, percent: float, status: str) -> None:
        """Update the progress bar (0.0–1.0) and status text."""
        self._progress_bar.setValue(int(percent * 100.0))
        self._status_label.setText(status)

    def set_transferring(self, active: bool) -> None:
        """Toggle the UI between idle and actively transferring states."""
        self._start_btn.setEnabled(not active)
        self._cancel_btn.setEnabled(active)

    def set_status(self, message: str) -> None:
        """Set the status label text without changing progress."""
        self._status_label.setText(message)

    def append_log(self, message: str) -> None:
        """Append a single line to the transfer log widget."""
        self._log_view.appendPlainText(message)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        if self._binary is None or self._metadata is None:
            return
        self.set_transferring(True)
        self.append_log("Starting transfer...")
        self.transfer_requested.emit(self._binary, self._metadata)

    def _on_cancel(self) -> None:
        self.append_log("Cancel requested...")
        self.cancel_requested.emit()
        self.set_transferring(False)
        self._status_label.setText("Cancelled")
