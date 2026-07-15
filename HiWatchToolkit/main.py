"""
HiWatch Toolkit — Desktop Application Entry Point

Wires the BLE async layer to the Qt UI using the same QThread-worker
pattern established by :mod:`~hiwatch_toolkit.ui.pages.connect_page` and
:mod:`~hiwatch_toolkit.ui.pages.builder_page`.

Architecture::

    Qt Main Loop (GUI thread)
        │
        ├── QTimer ──► periodic callbacks
        │
        ├── QThread workers ──► asyncio event loops for BLE ops
        │     │
        │     ├── ScanWorker        (scan for devices)
        │     ├── ConnectWorker     (connect to device)
        │     ├── ReadInfoWorker    (read device info)
        │     ├── TimeSyncWorker    (sync time with retry)
        │     └── TransferWorker    (send watch face binary)
        │
        └── Signals ──► cross-page + controller wiring

Usage::

    python main.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QApplication

from hiwatch_toolkit.ble import (
    WatchDeviceClient,
    WatchDeviceInfo,
    WatchServiceDiscovery,
    WatchFaceTransfer,
    TransferProgress,
    TransferState,
    SessionRecorder,
)
from hiwatch_toolkit.protocol.debugger import format_packet_line, format_packet
from hiwatch_toolkit.ui import MainWindow, apply_theme

logger = logging.getLogger("hiwatch_toolkit")
logger.setLevel(logging.DEBUG)

# Ensure log directory exists
_LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# BLE Worker classes  (run in background QThreads with their own event loops)
# ---------------------------------------------------------------------------


class DiscoveryWorker(QObject):
    """Performs service discovery on a device without maintaining a connection."""

    finished = Signal(str, dict)  # service_table_string, service_summary_dict
    error = Signal(str)

    def __init__(self, device_info: WatchDeviceInfo) -> None:
        super().__init__()
        self._device_info = device_info

    @Slot()
    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            discovery = WatchServiceDiscovery(self._device_info.device)
            services = loop.run_until_complete(discovery.discover(timeout=10.0))
            table = discovery.format_service_table()
            loop.run_until_complete(discovery.disconnect())
            self.finished.emit(table, {
                "service_count": discovery.service_count,
                "char_count": discovery.char_count,
            })
        except Exception as exc:
            logger.error("Discovery error: %s", exc)
            self.error.emit(str(exc))
        finally:
            loop.close()


class ConnectWorker(QObject):
    """Connects to a watch in a background thread."""

    connected = Signal(object)  # WatchDeviceClient
    discovery_info = Signal(str)  # service table string
    error = Signal(str)

    def __init__(self, device_info: WatchDeviceInfo) -> None:
        super().__init__()
        self._device_info = device_info

    @Slot()
    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            client = WatchDeviceClient(self._device_info.device)
            loop.run_until_complete(client.connect(timeout=10.0))

            # Log service discovery table
            svc_map = client.connection.service_map
            if svc_map:
                lines = ["=== Discovered Services ==="]
                for svc_uuid, chars in svc_map.items():
                    lines.append(f"  Service  {svc_uuid}")
                    for c in chars:
                        props = " + ".join(p.upper() for p in c["properties"])
                        lines.append(f"    Char  {c['uuid']}  [ {props} ]")
                self.discovery_info.emit("\n".join(lines))

            self.connected.emit(client)
        except Exception as exc:
            logger.error("Connect error: %s", exc)
            self.error.emit(str(exc))
        finally:
            loop.close()


class DisconnectWorker(QObject):
    """Disconnects from a watch in a background thread."""

    disconnected = Signal()
    error = Signal(str)

    def __init__(self, client: WatchDeviceClient) -> None:
        super().__init__()
        self._client = client

    @Slot()
    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._client.disconnect())
            self.disconnected.emit()
        except Exception as exc:
            logger.error("Disconnect error: %s", exc)
            self.error.emit(str(exc))
        finally:
            loop.close()


class ReadInfoWorker(QObject):
    """Reads device info in a background thread."""

    finished = Signal(dict)  # dict of device info fields (label-keyed)
    error = Signal(str)

    def __init__(self, client: WatchDeviceClient) -> None:
        super().__init__()
        self._client = client

    @Slot()
    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            info = loop.run_until_complete(self._client.read_device_info())
            self.finished.emit({
                "device_name": info.device_name,
                "battery": info.battery,
                "firmware_version": info.firmware_version,
                "software_revision": info.software_revision,
                "manufacturer_name": info.manufacturer_name,
                "width": info.width,
                "height": info.height,
                "algorithm": info.algorithm,
            })
        except Exception as exc:
            logger.error("ReadInfo error: %s", exc)
            self.error.emit(str(exc))
        finally:
            loop.close()


class TimeSyncWorker(QObject):
    """Synchronises time with the watch in a background thread."""

    success = Signal()
    failed = Signal(str)

    def __init__(self, client: WatchDeviceClient) -> None:
        super().__init__()
        self._client = client

    @Slot()
    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            ok = loop.run_until_complete(self._client.sync_time())
            if ok:
                self.success.emit()
            else:
                self.failed.emit("Time sync failed after retries")
        except Exception as exc:
            logger.error("TimeSync error: %s", exc)
            self.failed.emit(str(exc))
        finally:
            loop.close()


class TransferWorker(QObject):
    """Transfers a watch face binary in a background thread."""

    progress = Signal(float, str)  # percent (0.0–1.0), status text
    log = Signal(str)
    finished = Signal(bool, str)  # success, message
    error = Signal(str)

    def __init__(
        self,
        client: WatchDeviceClient,
        binary: bytes,
        meta: dict,
        chunk_size: int = 200,
    ) -> None:
        super().__init__()
        self._client = client
        self._binary = binary
        self._meta = meta
        self._chunk_size = chunk_size
        self._cancelled = False

    @Slot()
    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            font_pos = self._meta.get("font_position", 0)
            is_custom = self._meta.get("has_font", False)

            def _on_progress(p: TransferProgress) -> None:
                self.progress.emit(p.percent, f"Chunk {p.sequence} — {p.sent_bytes}/{p.total_bytes} bytes")
                self.log.emit(f"Seq {p.sequence}: sent {p.sent_bytes}/{p.total_bytes} bytes")

            transfer = WatchFaceTransfer(
                self._client.connection,
                progress_callback=_on_progress,
            )
            result = loop.run_until_complete(
                transfer.run(
                    self._binary,
                    font_position=font_pos,
                    is_custom=is_custom,
                    chunk_size=self._chunk_size,
                )
            )

            if result.state == TransferState.SUCCESS:
                self.log.emit("Transfer completed successfully!")
                self.finished.emit(True, "Transfer complete")
            else:
                msg = result.error_message or "Unknown error"
                self.log.emit(f"Transfer failed: {msg}")
                self.finished.emit(False, msg)

        except Exception as exc:
            logger.error("Transfer error: %s", exc)
            self.error.emit(str(exc))
        finally:
            loop.close()

    def cancel(self) -> None:
        self._cancelled = True


# ---------------------------------------------------------------------------
# Application Controller  (runs in the GUI thread, manages BLE workers)
# ---------------------------------------------------------------------------


class AppController(QObject):
    """Wires UI page signals to BLE operations via QThread workers."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__()
        self._window = window
        self._client: Optional[WatchDeviceClient] = None
        self._threads: list[QThread] = []

        # --- Session recorder ---
        self._session_recorder = SessionRecorder(log_dir=_LOG_DIR)
        self._session_recorder.start()

        # --- Clean up on window close ---
        window.destroyed.connect(self._on_window_destroyed)

        self._wire_signals()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _on_window_destroyed(self) -> None:
        """Stop the session recorder when the window closes."""
        self._session_recorder.stop()

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _wire_signals(self) -> None:
        cp = self._window.connect_page
        up = self._window.upload_page

        cp.connect_requested.connect(self._on_connect_requested)
        cp.disconnect_requested.connect(self._on_disconnect_requested)
        up.transfer_requested.connect(self._on_transfer_requested)

    # ------------------------------------------------------------------
    # Connect / Disconnect
    # ------------------------------------------------------------------

    def _on_connect_requested(self, device_info: WatchDeviceInfo) -> None:
        self._window.logs_page.append_log(f"Connecting to {device_info.name}...")
        self._session_recorder.record_custom("CONNECT", {
            "device_name": device_info.name,
            "device_address": device_info.address,
        })

        self._connect_worker = ConnectWorker(device_info)
        self._connect_thread = QThread()
        self._connect_worker.moveToThread(self._connect_thread)
        self._connect_worker.connected.connect(self._on_connected)
        self._connect_worker.discovery_info.connect(self._window.logs_page.append_log)
        self._connect_worker.error.connect(self._on_connect_error)
        self._connect_thread.started.connect(self._connect_worker.run)
        self._connect_thread.finished.connect(self._connect_thread.deleteLater)
        self._threads.append(self._connect_thread)
        self._connect_thread.start()

    @Slot(object)
    def _on_connected(self, client: WatchDeviceClient) -> None:
        self._client = client
        self._window.logs_page.append_log("Connected successfully")
        self._window.connect_page._conn_status.setText("Connected")
        self._window.connect_page._disconnect_btn.setEnabled(True)

        # Wire packet debugger — TX and RX through the session recorder
        client.set_notification_handler(self._on_notification)
        client.connection.set_write_logger(self._on_tx_packet)

        # Read device info in background
        self._read_info()

        if self._connect_thread:
            self._connect_thread.quit()
            self._connect_thread = None

    @Slot(str)
    def _on_connect_error(self, msg: str) -> None:
        self._window.logs_page.append_error(f"Connection failed: {msg}")
        self._session_recorder.record_custom("CONNECT_ERROR", {"error": msg})
        self._window.connect_page._conn_status.setText(f"Failed: {msg}")
        self._window.connect_page._connect_btn.setEnabled(True)
        if self._connect_thread:
            self._connect_thread.quit()
            self._connect_thread = None

    def _on_disconnect_requested(self) -> None:
        if self._client is None or not self._client.is_connected:
            self._window.connect_page._conn_status.setText("Disconnected")
            return

        self._window.logs_page.append_log("Disconnecting...")
        self._session_recorder.record_custom("DISCONNECT", {})

        self._disconnect_worker = DisconnectWorker(self._client)
        self._disconnect_thread = QThread()
        self._disconnect_worker.moveToThread(self._disconnect_thread)
        self._disconnect_worker.disconnected.connect(self._on_disconnected)
        self._disconnect_worker.error.connect(self._on_disconnect_error)
        self._disconnect_thread.started.connect(self._disconnect_worker.run)
        self._disconnect_thread.finished.connect(self._disconnect_thread.deleteLater)
        self._threads.append(self._disconnect_thread)
        self._disconnect_thread.start()

    def _on_disconnected(self) -> None:
        self._client = None
        self._window.logs_page.append_log("Disconnected")
        self._window.connect_page._conn_status.setText("Disconnected")
        self._window.connect_page._connect_btn.setEnabled(True)
        self._window.connect_page._disconnect_btn.setEnabled(False)
        for v in self._window.connect_page._info_labels.values():
            v.setText("—")
        if self._disconnect_thread:
            self._disconnect_thread.quit()
            self._disconnect_thread = None

    def _on_disconnect_error(self, msg: str) -> None:
        self._window.logs_page.append_error(f"Disconnect error: {msg}")
        self._window.connect_page._conn_status.setText("Disconnected (error)")
        self._client = None
        if self._disconnect_thread:
            self._disconnect_thread.quit()
            self._disconnect_thread = None

    # ------------------------------------------------------------------
    # Device info
    # ------------------------------------------------------------------

    def _read_info(self) -> None:
        if self._client is None:
            return

        self._info_worker = ReadInfoWorker(self._client)
        self._info_thread = QThread()
        self._info_worker.moveToThread(self._info_thread)
        self._info_worker.finished.connect(self._on_info_received)
        self._info_worker.error.connect(self._on_info_error)
        self._info_thread.started.connect(self._info_worker.run)
        self._info_thread.finished.connect(self._info_thread.deleteLater)
        self._threads.append(self._info_thread)
        self._info_thread.start()

    @Slot(dict)
    def _on_info_received(self, info: dict) -> None:
        self._window.connect_page.update_device_info(**info)

        # Log summary
        summary = (
            f"Device info: "
            f"name={info.get('device_name', '?')}, "
            f"{info.get('width')}×{info.get('height')}, "
            f"battery={info.get('battery')}%, "
            f"fw={info.get('firmware_version', '?')}"
        )
        self._window.logs_page.append_log(summary)
        self._session_recorder.record_custom("DEVICE_INFO", info)

        # After reading device info, synchronise time
        self._sync_time()

        if self._info_thread:
            self._info_thread.quit()
            self._info_thread = None

    @Slot(str)
    def _on_info_error(self, msg: str) -> None:
        self._window.logs_page.append_error(f"Device info error: {msg}")
        if self._info_thread:
            self._info_thread.quit()
            self._info_thread = None

    # ------------------------------------------------------------------
    # Time synchronisation
    # ------------------------------------------------------------------

    def _sync_time(self) -> None:
        """Synchronise the watch time in a background thread.

        Follows the same pattern as the official app which calls
        ``SDKCmdMannager.synchronTime()`` after reading the firmware
        version.
        """
        if self._client is None:
            return

        self._window.logs_page.append_log("Synchronising time...")

        self._timesync_worker = TimeSyncWorker(self._client)
        self._timesync_thread = QThread()
        self._timesync_worker.moveToThread(self._timesync_thread)
        self._timesync_worker.success.connect(self._on_time_synced)
        self._timesync_worker.failed.connect(self._on_time_sync_failed)
        self._timesync_thread.started.connect(self._timesync_worker.run)
        self._timesync_thread.finished.connect(self._timesync_thread.deleteLater)
        self._threads.append(self._timesync_thread)
        self._timesync_thread.start()

    @Slot()
    def _on_time_synced(self) -> None:
        self._window.logs_page.append_log("Time synchronised successfully")
        self._session_recorder.record_custom("TIME_SYNC", {"result": "SUCCESS"})
        if self._timesync_thread:
            self._timesync_thread.quit()
            self._timesync_thread = None

    @Slot(str)
    def _on_time_sync_failed(self, msg: str) -> None:
        self._window.logs_page.append_error(f"Time sync failed: {msg}")
        self._session_recorder.record_custom("TIME_SYNC", {"result": "FAILED", "error": msg})
        if self._timesync_thread:
            self._timesync_thread.quit()
            self._timesync_thread = None

    # ------------------------------------------------------------------
    # Watch face transfer
    # ------------------------------------------------------------------

    def _on_transfer_requested(self, binary: bytes, meta: dict) -> None:
        if self._client is None or not self._client.is_connected:
            self._window.logs_page.append_error(
                "Cannot transfer: no device connected"
            )
            self._window.upload_page.set_transferring(False)
            self._window.upload_page.append_log("ERROR: No device connected")
            return

        self._window.logs_page.append_log(
            f"Starting transfer: {meta.get('name', 'Untitled')} "
            f"({len(binary):,} bytes)"
        )

        self._transfer_worker = TransferWorker(self._client, binary, meta)
        self._transfer_thread = QThread()
        self._transfer_worker.moveToThread(self._transfer_thread)
        self._transfer_worker.progress.connect(self._window.upload_page.update_progress)
        self._transfer_worker.log.connect(self._window.upload_page.append_log)
        self._transfer_worker.finished.connect(self._on_transfer_finished)
        self._transfer_worker.error.connect(self._on_transfer_error)
        self._transfer_thread.started.connect(self._transfer_worker.run)
        self._transfer_thread.finished.connect(self._transfer_thread.deleteLater)
        self._threads.append(self._transfer_thread)
        self._transfer_thread.start()

    @Slot(bool, str)
    def _on_transfer_finished(self, success: bool, message: str) -> None:
        self._window.upload_page.set_transferring(False)
        if success:
            self._window.upload_page.set_status("Transfer complete!")
            self._window.logs_page.append_log("Transfer completed successfully")
        else:
            self._window.upload_page.set_status(f"Failed: {message}")
            self._window.logs_page.append_error(f"Transfer failed: {message}")
        if self._transfer_thread:
            self._transfer_thread.quit()
            self._transfer_thread = None

    @Slot(str)
    def _on_transfer_error(self, msg: str) -> None:
        self._window.upload_page.set_transferring(False)
        self._window.upload_page.set_status(f"Error: {msg}")
        self._window.logs_page.append_error(f"Transfer error: {msg}")
        if self._transfer_thread:
            self._transfer_thread.quit()
            self._transfer_thread = None

    # ------------------------------------------------------------------
    # Packet debugger — log every TX and RX through the session recorder
    # ------------------------------------------------------------------

    def _on_tx_packet(self, data: bytearray) -> None:
        """Log every outgoing packet through the packet debugger and session recorder."""
        entry = format_packet(bytes(data), direction="TX")
        self._window.logs_page.append_log(format_packet_line(entry))
        self._session_recorder.record(entry)

    def _on_notification(self, data: bytearray) -> None:
        """Forward every incoming BLE notification through the packet debugger and session recorder."""
        entry = format_packet(bytes(data), direction="RX")
        self._window.logs_page.append_log(format_packet_line(entry))
        self._session_recorder.record(entry)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Create the QApplication, build the UI, and start the Qt event loop."""
    app = QApplication(sys.argv)
    app.setApplicationName("HiWatch Toolkit")
    app.setOrganizationName("HiWatchToolkit")
    apply_theme(app)

    window = MainWindow()
    controller = AppController(window)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
