#!/usr/bin/env python3
"""
Standalone test script — connects to Ultra3 watch via BLE,
reads device info, syncs time, logs every transaction.

Usage:
    python3 test_watch_connect.py
"""

import asyncio
import sys
import os
from datetime import datetime

# Ensure src path is available
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from hiwatch_toolkit.ble import WatchDeviceClient
from hiwatch_toolkit.protocol.debugger import format_packet, format_packet_line


async def main():
    # Replace with your watch's MAC address from bluetoothctl scan
    # Default: 66:22:AA:00:42:78 (Ultra3)
    address = sys.argv[1] if len(sys.argv) > 1 else "66:22:AA:00:42:78"

    print(f"Connecting to {address}...")
    print()

    from bleak import BleakScanner
    from bleak.backends.device import BLEDevice

    # First try to find by scanning
    device = None
    print("Scanning for BLE devices (3s)...")
    devices = await BleakScanner.discover(timeout=3.0, return_adv=True)
    for addr, (dev, adv) in devices.items():
        if addr.upper() == address.upper():
            device = dev
            name = dev.name or adv.local_name or "?"
            rssi = adv.rssi if adv.rssi is not None else "?"
            print(f"Found in scan: {name} ({addr}) RSSI={rssi}")
            break

    if device is None:
        # Try to connect by address directly — Bleak can connect if BlueZ
        # already knows the device from a previous scan
        print(f"Not found in current scan. Trying direct connection to {address}...")
        # Create a minimal BLEDevice-like object for BleakClient
        # We need to get it from the BleakScanner's discovered devices cache
        # or create one manually
        scanner = BleakScanner()
        await scanner.start()
        await asyncio.sleep(1.0)
        known_devices = scanner.discovered_devices
        await scanner.stop()

        for dev in known_devices:
            if dev.address.upper() == address.upper():
                device = dev
                print(f"Found in device cache: {dev.name} ({dev.address})")
                break

    if device is None:
        print(f"ERROR: Device {address} not found in scan or cache.")
        print()
        print("Troubleshooting:")
        print("  1. Make sure your watch is not connected to phone (disable BT on phone)")
        print("  2. Put watch in pairing mode (check watch settings)")
        print("  3. Run: bluetoothctl scan on")
        print("  4. Check if device is listed: bluetoothctl devices")
        return

    # Connect and communicate
    client = WatchDeviceClient(device)

    # Wire logging
    def on_tx(data):
        entry = format_packet(bytes(data), direction="TX")
        print(f"  {format_packet_line(entry)}")
        print()

    def on_rx(data):
        entry = format_packet(bytes(data), direction="RX")
        print(f"  {format_packet_line(entry)}")
        print()

    try:
        print("Connecting...")
        await client.connect(timeout=15.0)
        client.connection.set_write_logger(on_tx)
        client.set_notification_handler(on_rx)
        print("CONNECTED!\n")

        print("=" * 50)
        print("STEP 1: Reading device info (GATT characteristics)")
        print("=" * 50)
        info = await client.read_device_info()
        print()
        print("Device Info Results:")
        print(f"  Battery:         {info.battery} %")
        print(f"  Firmware:        {info.firmware_version or '(not available)'}")
        print(f"  Software Rev:    {info.software_revision or '(not available)'}")
        print(f"  Device Name:     {info.device_name or '(not available)'}")
        print(f"  Manufacturer:    {info.manufacturer_name or '(not available)'}")
        print(f"  Model Number:    {info.model_number or '(not available)'}")
        if info.width and info.height:
            print(f"  Display:         {info.width} x {info.height}")
        if info.algorithm:
            print(f"  Algorithm:       {info.algorithm}")
        print()

        print("=" * 50)
        print("STEP 2: Synchronising time")
        print("=" * 50)
        success = await client.sync_time()
        if success:
            print("  TIME SYNC: SUCCESS (watch acknowledged)")
        else:
            print("  TIME SYNC: FAILED (no ACK after retries)")
        print()

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("Disconnecting...")
        await client.disconnect()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
