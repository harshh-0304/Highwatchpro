"""
Main application window with sidebar navigation.

macOS-style layout::

    ╔══════════╤═══════════════════════════╗
    ║ Sidebar  │   Content Area            ║
    ║          │                           ║
    ║ 🔵 Connect  │   (stacked pages)       ║
    ║ 🎨 Builder  │                           ║
    ║ 📤 Upload   │                           ║
    ║ 🖼 Gallery  │                           ║
    ║ 📋 Logs     │                           ║
    ╚══════════╧═══════════════════════════╝
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .pages import (
    ConnectPage,
    BuilderPage,
    UploadPage,
    GalleryPage,
    LogsPage,
)


NAV_ITEMS = [
    ("Connect",   "🔵"),
    ("Builder",   "🎨"),
    ("Upload",    "📤"),
    ("Gallery",   "🖼"),
    ("Logs",      "📋"),
]


class MainWindow(QMainWindow):
    """Top-level application window."""

    def __init__(self) -> None:
        super().__init__()
        self._setup_window()
        self._build_ui()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_window(self) -> None:
        self.setWindowTitle("HiWatch Toolkit")
        self.resize(1100, 720)
        self.setMinimumSize(800, 520)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Sidebar ---
        self._sidebar = QListWidget()
        self._sidebar.setObjectName("sidebar")
        self._sidebar.setFixedWidth(180)
        self._sidebar.setIconSize(QSize(0, 0))
        self._sidebar.setSpacing(2)
        self._sidebar.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        for label, icon in NAV_ITEMS:
            item = QListWidgetItem(f"  {icon}  {label}")
            self._sidebar.addItem(item)

        # --- Pages ---
        self._pages = QStackedWidget()
        self._pages.setObjectName("pageContainer")

        self._connect_page = ConnectPage()
        self._builder_page = BuilderPage()
        self._upload_page = UploadPage()
        self._gallery_page = GalleryPage()
        self._logs_page = LogsPage()

        self._pages.addWidget(self._connect_page)   # index 0
        self._pages.addWidget(self._builder_page)    # index 1
        self._pages.addWidget(self._upload_page)     # index 2
        self._pages.addWidget(self._gallery_page)    # index 3
        self._pages.addWidget(self._logs_page)       # index 4

        # --- Assemble ---
        layout.addWidget(self._sidebar)
        layout.addWidget(self._pages, 1)

        # --- Signals ---
        self._sidebar.currentRowChanged.connect(self._pages.setCurrentIndex)
        self._sidebar.setCurrentRow(0)

        # --- Wire cross-page signals ---
        self._wire_signals()

    def _wire_signals(self) -> None:
        """Connect page-to-page signals."""

        # Builder → Upload: when binary is ready, switch to upload
        self._builder_page.face_built.connect(self._on_face_built)

        # Gallery → Upload: when "Install" clicked
        self._gallery_page.install_requested.connect(self._on_install_requested)

        # Connect page → Logs: forward BLE notifications
        self._connect_page.notification_received.connect(self._logs_page.append_packet)

    # ------------------------------------------------------------------
    # Cross-page actions
    # ------------------------------------------------------------------

    def _on_face_built(self, binary: bytes, meta: dict) -> None:
        """Called when the builder finishes converting a watch face."""
        self._upload_page.prepare(binary, meta)
        self._sidebar.setCurrentRow(2)  # switch to Upload page

    def _on_install_requested(self, binary: bytes, meta: dict) -> None:
        """Called when the gallery requests to install a face."""
        self._upload_page.prepare(binary, meta)
        self._sidebar.setCurrentRow(2)  # switch to Upload page

    # ------------------------------------------------------------------
    # Public API for top-level app controller
    # ------------------------------------------------------------------

    @property
    def connect_page(self) -> ConnectPage:
        return self._connect_page

    @property
    def upload_page(self) -> UploadPage:
        return self._upload_page

    @property
    def logs_page(self) -> LogsPage:
        return self._logs_page
