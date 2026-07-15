"""
Page 1: Connect — Scan BLE, connect to watch, show device info.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from ...ble import WatchScanner, WatchDeviceInfo

logger = logging.getLogger(__name__)


class ScanWorker(QObject):
    """Runs BLE scan in a background thread."""

    finished = Signal(list)  # list[WatchDeviceInfo]
    error = Signal(str)

    def __init__(self, timeout: float = 4.0) -> None:
        super().__init__()
        self._timeout = timeout

    @Slot()
    def run(self) -> None:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            scanner = WatchScanner()
            devices = loop.run_until_complete(scanner.scan(timeout=self._timeout))
            loop.close()
            self.finished.emit(devices)
        except Exception as exc:
            logger.error("Scan error: %s", exc)
            self.error.emit(str(exc))


class ConnectPage(QWidget):
    """BLE connection management page."""

    notification_received = Signal(bytes)
    """Emitted when a BLE notification arrives from the watch."""

    connect_requested = Signal(object)  # WatchDeviceInfo
    """Emitted when the user clicks **Connect**."""

    disconnect_requested = Signal()
    """Emitted when the user clicks **Disconnect**."""

    def __init__(self) -> None:
        super().__init__()
        self._current_device: Optional[WatchDeviceInfo] = None
        self._scan_thread: Optional[QThread] = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Title
        title = QLabel("Connect to Watch")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        subtitle = QLabel("Scan for nearby HiWatch Pro devices")
        subtitle.setObjectName("infoLabel")
        layout.addWidget(subtitle)

        # --- Scan section ---
        scan_group = QGroupBox("Device Discovery")
        scan_layout = QVBoxLayout(scan_group)

        scan_btn_row = QHBoxLayout()
        self._scan_btn = QPushButton("Scan for Devices")
        self._scan_btn.clicked.connect(self._start_scan)
        scan_btn_row.addWidget(self._scan_btn)
        scan_btn_row.addStretch()
        scan_layout.addLayout(scan_btn_row)

        self._device_list = QListWidget()
        self._device_list.setMinimumHeight(120)
        self._device_list.itemClicked.connect(self._on_device_selected)
        scan_layout.addWidget(self._device_list)

        self._scan_status = QLabel("")
        self._scan_status.setObjectName("statusLabel")
        scan_layout.addWidget(self._scan_status)

        layout.addWidget(scan_group)

        # --- Connection section ---
        conn_group = QGroupBox("Connection")
        conn_layout = QVBoxLayout(conn_group)

        conn_btn_row = QHBoxLayout()
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setEnabled(False)
        self._connect_btn.clicked.connect(self._connect)
        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setObjectName("dangerButton")
        self._disconnect_btn.setEnabled(False)
        self._disconnect_btn.clicked.connect(self._disconnect)
        conn_btn_row.addWidget(self._connect_btn)
        conn_btn_row.addWidget(self._disconnect_btn)
        conn_btn_row.addStretch()
        conn_layout.addLayout(conn_btn_row)

        self._conn_status = QLabel("Not connected")
        self._conn_status.setObjectName("statusLabel")
        conn_layout.addWidget(self._conn_status)

        layout.addWidget(conn_group)

        # --- Device info section ---
        info_group = QGroupBox("Device Information")
        info_layout = QVBoxLayout(info_group)

        self._info_labels: dict[str, QLabel] = {}
        info_keys = (
            "Device Name",
            "Battery",
            "Firmware Version",
            "Software Revision",
            "Manufacturer",
            "Display",
            "Algorithm",
        )
        for key in info_keys:
            row = QHBoxLayout()
            label_key = QLabel(f"{key}:")
            label_key.setObjectName("infoLabel")
            label_key.setFixedWidth(140)
            label_val = QLabel("—")
            label_val.setObjectName("valueLabel")
            self._info_labels[key] = label_val
            row.addWidget(label_key)
            row.addWidget(label_val)
            row.addStretch()
            info_layout.addLayout(row)

        layout.addWidget(info_group)
        layout.addStretch()

    # ------------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------------

    def _start_scan(self) -> None:
        self._device_list.clear()
        self._scan_btn.setEnabled(False)
        self._scan_status.setText("Scanning...")
        self._connect_btn.setEnabled(False)

        self._scan_worker = ScanWorker(timeout=4.0)
        self._scan_thread = QThread()
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.error.connect(self._on_scan_error)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)
        self._scan_thread.start()

    @Slot(list)
    def _on_scan_finished(self, devices: list) -> None:
        self._scan_btn.setEnabled(True)
        self._scan_status.setText(f"Found {len(devices)} device(s)")

        for dev in devices:
            item = QListWidgetItem(f"{dev.name}  |  {dev.address}  |  RSSI: {dev.rssi}")
            item.setData(256, dev)  # store device info in user role
            self._device_list.addItem(item)

        if self._scan_thread:
            self._scan_thread.quit()
            self._scan_thread = None

    @Slot(str)
    def _on_scan_error(self, msg: str) -> None:
        self._scan_btn.setEnabled(True)
        self._scan_status.setText(f"Scan error: {msg}")
        if self._scan_thread:
            self._scan_thread.quit()
            self._scan_thread = None

    # ------------------------------------------------------------------
    # Selection / Connect
    # ------------------------------------------------------------------

    def _on_device_selected(self, item: QListWidgetItem) -> None:
        dev: WatchDeviceInfo = item.data(256)
        self._current_device = dev
        self._connect_btn.setEnabled(True)
        self._scan_status.setText(f"Selected: {dev.name}")

    def _connect(self) -> None:
        if self._current_device is None:
            return
        self._conn_status.setText(f"Connecting to {self._current_device.name}...")
        self._connect_btn.setEnabled(False)
        self.connect_requested.emit(self._current_device)

    def _disconnect(self) -> None:
        self._conn_status.setText("Disconnected")
        self._connect_btn.setEnabled(True)
        self._disconnect_btn.setEnabled(False)
        self.disconnect_requested.emit()
        for v in self._info_labels.values():
            v.setText("—")

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def current_device(self) -> Optional[WatchDeviceInfo]:
        """The currently selected or connected device."""
        return self._current_device

    @property
    def is_connected(self) -> bool:
        """Whether the UI thinks it's connected (may differ from BLE state)."""
        return self._connect_btn.isEnabled() is False and self._disconnect_btn.isEnabled() is True

    # ------------------------------------------------------------------
    # Device info update (called externally after connection)
    # ------------------------------------------------------------------

    def update_device_info(self, **kwargs) -> None:
        """Update the device info labels from keyword arguments.

        Accepted keyword keys and their mapping to display labels::

            device_name       → "Device Name"
            battery           → "Battery"  (formatted as "XX %")
            firmware_version  → "Firmware Version"
            software_revision → "Software Revision"
            manufacturer_name → "Manufacturer"
            width / height    → "Display"  (formatted as "W×H")
            algorithm         → "Algorithm"
        """
        label_map: dict[str, str] = {
            "device_name": "Device Name",
            "battery": "Battery",
            "firmware_version": "Firmware Version",
            "software_revision": "Software Revision",
            "manufacturer_name": "Manufacturer",
            "algorithm": "Algorithm",
        }

        for key, val in kwargs.items():
            if key == "battery":
                self._info_labels["Battery"].setText(f"{val} %")
            elif key == "width" and val:
                height = kwargs.get("height", 0)
                self._info_labels["Display"].setText(f"{val}×{height}")
            elif key in label_map:
                label_key = label_map[key]
                if label_key in self._info_labels:
                    self._info_labels[label_key].setText(str(val))

        self._conn_status.setText("Connected")
        self._connect_btn.setEnabled(False)
        self._disconnect_btn.setEnabled(True)
