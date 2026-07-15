"""
Page 5: Logs — Hex viewer and event log for BLE communication.

Provides a real-time scrolling log that captures:
- BLE packets sent and received (hex dump format)
- Application-level events (connection, transfer progress, errors)
- A clear button to reset the view
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class LogsPage(QWidget):
    """Real-time BLE communication and event log viewer."""

    def __init__(self) -> None:
        super().__init__()
        self._max_blocks: int = 500
        self._block_count: int = 0
        self._paused: bool = False
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Title
        title = QLabel("Communication Logs")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        subtitle = QLabel(
            "Real-time BLE packet hex dump and application event log"
        )
        subtitle.setObjectName("infoLabel")
        layout.addWidget(subtitle)

        # --- Log view ---
        self._log_view = QPlainTextEdit()
        self._log_view.setObjectName("logView")
        self._log_view.setReadOnly(True)
        self._log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._log_view.setMaximumBlockCount(self._max_blocks)
        layout.addWidget(self._log_view, stretch=1)

        # --- Controls ---
        controls = QHBoxLayout()

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setObjectName("secondaryButton")
        self._clear_btn.clicked.connect(self.clear)
        controls.addWidget(self._clear_btn)

        self._pause_btn = QPushButton("Pause")
        self._pause_btn.setObjectName("secondaryButton")
        self._pause_btn.setCheckable(True)
        self._pause_btn.toggled.connect(self._on_pause_toggled)
        controls.addWidget(self._pause_btn)

        controls.addStretch()

        self._line_count_label = QLabel("0 lines")
        self._line_count_label.setObjectName("infoLabel")
        controls.addWidget(self._line_count_label)

        layout.addLayout(controls)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append_packet(self, data: bytes, direction: str = "RX") -> None:
        """Append a BLE packet hex dump to the log.

        Parameters
        ----------
        data:
            Raw packet bytes received from (or sent to) the watch.
        direction:
            ``"RX"`` for received, ``"TX"`` for sent.
        """
        if self._paused:
            return

        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        hex_str = data.hex(" ").upper()

        # Group hex into 16-byte rows for readability
        lines = []
        for i in range(0, len(hex_str), 47):  # 16 bytes → "XX XX XX ... XX" (47 chars)
            lines.append(hex_str[i : i + 47])

        if len(lines) <= 1:
            self._log_view.appendPlainText(
                f"[{ts}] [{direction}] {hex_str}"
            )
        else:
            self._log_view.appendPlainText(
                f"[{ts}] [{direction}] ({len(data)} bytes)"
            )
            for line in lines:
                self._log_view.appendPlainText(f"          {line}")

        self._update_line_count()

    def append_log(self, message: str) -> None:
        """Append a free-text log message with a timestamp."""
        if self._paused:
            return
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._log_view.appendPlainText(f"[{ts}] [INF] {message}")
        self._update_line_count()

    def append_error(self, message: str) -> None:
        """Append an error message with a timestamp."""
        if self._paused:
            return
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._log_view.appendPlainText(f"[{ts}] [ERR] {message}")
        self._update_line_count()

    def clear(self) -> None:
        """Clear the entire log view."""
        self._log_view.clear()
        self._update_line_count()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _update_line_count(self) -> None:
        count = self._log_view.blockCount()
        self._line_count_label.setText(f"{count} lines")

    def _on_pause_toggled(self, paused: bool) -> None:
        self._paused = paused
        self._pause_btn.setText("Resume" if paused else "Pause")
        if not paused:
            self.append_log("Log resumed")
