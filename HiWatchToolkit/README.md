# HiWatch Toolkit

Desktop application for HiWatch Pro smartwatch watch face management.

Replaces the official HiWatch Pro Android app for watch face creation and transfer via BLE.

## Features

- **Connect** – Scan and connect to HiWatch Pro devices via BLE
- **Watch Face Builder** – Import PNG images, crop, resize, preview, and convert to RGB565
- **Upload** – Transfer watch faces to the device with progress tracking
- **Gallery** – Manage local watch face library
- **Logs** – Real-time BLE packet hex viewer and debug console

## Requirements

- Python 3.10+
- Bluetooth adapter (BLE support)
- Linux (tested), macOS, Windows

## Installation

```bash
pip install -r requirements.txt
python -m hiwatch_toolkit.main
```
