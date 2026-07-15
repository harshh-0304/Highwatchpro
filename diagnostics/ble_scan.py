"""
STEP 1: BLE Service & Characteristic Enumeration

Connects to the watch via BLE, enumerates ALL services/characteristics,
subscribes to every notify-capable characteristic, and prints all incoming data.

Usage:
    python diagnostics/ble_scan.py [mac_address]

Default MAC: 66:22:AA:00:42:78
"""

import sys
import os
import asyncio
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "HiWatchToolkit"))

from bleak import BleakScanner, BleakClient

MAC = sys.argv[1] if len(sys.argv) > 1 else "66:22:AA:00:42:78"

KNOWN_UUIDS = {
    "6e400001-b5a3-f393-e0a9-e50e24dcca9d": "UART Service (Nordic)",
    "6e400002-b5a3-f393-e0a9-e50e24dcca9d": "UART Write (TX)",
    "6e400003-b5a3-f393-e0a9-e50e24dcca9d": "UART Notify (RX)",
    "6e400005-b5a3-f393-e0a9-e50e24dcca9d": "UART Write (AliPay)",
    "6e40ff01-b5a3-f393-e0a9-e50e24dcca9e": "OTA Service (Jieli)",
    "6e40ff02-b5a3-f393-e0a9-e50e24dcca9e": "OTA Write",
    "6e40ff03-b5a3-f393-e0a9-e50e24dcca9e": "OTA Notify",
    "0000180f-0000-1000-8000-00805f9b34fb": "Battery Service",
    "00002a19-0000-1000-8000-00805f9b34fb": "Battery Level",
    "0000180a-0000-1000-8000-00805f9b34fb": "Device Info Service",
    "00002a26-0000-1000-8000-00805f9b34fb": "Firmware Revision",
    "00002a28-0000-1000-8000-00805f9b34fb": "Software Revision",
    "00002a2a-0000-1000-8000-00805f9b34fb": "Device Name",
    "00002a29-0000-1000-8000-00805f9b34fb": "Manufacturer Name",
    "00002a24-0000-1000-8000-00805f9b34fb": "Model Number",
    "00001810-0000-1000-8000-00805f9b34fb": "Dial Service (Alt)",
    "00002a30-0000-1000-8000-00805f9b34fb": "Dial Char",
    "0000ae00-0000-1000-8000-00805f9b34fb": "Jieli Service (Alt)",
    "0000ae01-0000-1000-8000-00805f9b34fb": "Jieli Write (Alt)",
    "0000ae02-0000-1000-8000-00805f9b34fb": "Jieli Notify (Alt)",
}

notify_data = []

def notification_handler(sender: int, data: bytes, char_uuid: str):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    hex_str = data.hex(" ").upper()
    ascii_str = "".join(ch(b) if 32 <= b < 127 else "." for b in data)
    print(f"  [{ts}] RX [{char_uuid}] ({len(data)} bytes)")
    print(f"         HEX: {hex_str}")
    print(f"         ASC: {ascii_str}")
    if data[0] == 0xCD:
        print(f"         *** VALID 0xCD PACKET ***")
    print()
    notify_data.append((ts, char_uuid, data))

async def main():
    print("=" * 72)
    print("BLE SCAN - Service & Characteristic Enumeration")
    print(f"Target: {MAC}")
    print("=" * 72)
    print()

    print("[1] Scanning for device...")
    device = await BleakScanner.find_device_by_address(MAC, timeout=10)
    if not device:
        print(f"  FAILED: Device {MAC} not found")
        sys.exit(1)
    print(f"  FOUND: {device.name or '(no name)'}  RSSI={device.rssi}")
    print()

    print("[2] Connecting...")
    async with BleakClient(device, timeout=30) as client:
        print(f"  CONNECTED  MTU={await client.mtu_size if hasattr(client, 'mtu_size') else 'N/A'}")
        print()

        print("[3] Service Enumeration")
        print("-" * 72)
        services = await client.get_services()
        notify_handles = []

        for service in services:
            svc_uuid = str(service.uuid).lower()
            svc_name = KNOWN_UUIDS.get(svc_uuid, "")
            print(f"\n  SERVICE: {svc_uuid}  {svc_name}")
            for char in service.characteristics:
                char_uuid = str(char.uuid).lower()
                char_name = KNOWN_UUIDS.get(char_uuid, "")
                props = ",".join(char.properties)

                print(f"    ├── CHAR: {char_uuid}  {char_name}")
                print(f"    │     Properties: {props}")

                # Read all readable descriptors
                if "read" in char.properties:
                    try:
                        val = await client.read_gatt_char(char.uuid)
                        hex_v = val.hex(" ").upper()
                        asc_v = "".join(ch(b) if 32 <= b < 127 else "." for b in val)
                        print(f"    │     Value: {hex_v}")
                        print(f"    │     ASCII: {asc_v}")
                    except Exception as e:
                        print(f"    │     Read failed: {e}")

                # Collect notify/indicate handles for subscription
                if "notify" in char.properties or "indicate" in char.properties:
                    notify_handles.append(char)

        print()
        print("-" * 72)
        print(f"\n[4] Subscribing to {len(notify_handles)} notify/indicate characteristics...")

        for char in notify_handles:
            char_uuid = str(char.uuid).lower()
            try:
                await client.start_notify(
                    char.uuid,
                    lambda s, d, cu=char_uuid: notification_handler(s, d, cu),
                )
                print(f"  SUBSCRIBED: {char_uuid}")
            except Exception as e:
                print(f"  FAILED:     {char_uuid}  ({e})")

        print()
        print("[5] Listening for notifications (15 seconds)...")
        print("=" * 72)
        await asyncio.sleep(15)
        print("=" * 72)
        print()

        print(f"[6] Summary: {len(notify_data)} notifications received")
        if notify_data:
            print("  All RX packets listed above ^")
            cd_packets = [n for n in notify_data if n[2][0] == 0xCD]
            if cd_packets:
                print(f"\n  *** {len(cd_packets)} valid 0xCD protocol packets detected! ***")
                for ts, uuid, data in cd_packets:
                    print(f"    [{ts}] {uuid}")
                    print(f"    RAW: {data.hex(' ').upper()}")
        else:
            print("  No notifications received.")
            print("  Possible reasons:")
            print("    - Watch requires pairing first")
            print("    - Watch requires app-level auth/bonding")
            print("    - Wrong transport (try RFCOMM)")
            print("    - Watch is idle and needs a command sent first")

        # Also try reading standard GATT characteristics
        print()
        print("[7] Attempting GATT reads of Device Info...")
        for uuid, label in [
            ("00002a19-0000-1000-8000-00805f9b34fb", "Battery Level"),
            ("00002a26-0000-1000-8000-00805f9b34fb", "Firmware Revision"),
            ("00002a28-0000-1000-8000-00805f9b34fb", "Software Revision"),
            ("00002a29-0000-1000-8000-00805f9b34fb", "Manufacturer Name"),
            ("00002a24-0000-1000-8000-00805f9b34fb", "Model Number"),
        ]:
            try:
                val = await client.read_gatt_char(uuid)
                print(f"  {label:20s}: {val.decode('utf-8', errors='replace').strip()}")
            except Exception as e:
                print(f"  {label:20s}: FAILED - {e}")

        print()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
