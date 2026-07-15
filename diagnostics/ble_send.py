"""
STEP 2: BLE Send Test - Time Sync Command

Connects via BLE, locates writable characteristics,
sends the 0xCD time sync packet, and waits for a response.

Usage:
    python diagnostics/ble_send.py [mac_address]

Default MAC: 66:22:AA:00:42:78
"""

import sys
import os
import asyncio
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "HiWatchToolkit"))

from bleak import BleakScanner, BleakClient

from src.hiwatch_toolkit.protocol.commands import (
    build_set_time,
    build_dial_read_status,
    build_dial_read_info,
    build_enter_ota,
)
from src.hiwatch_toolkit.protocol.packet import Packet
from src.hiwatch_toolkit.protocol.debugger import format_packet, format_packet_line
from src.hiwatch_toolkit.protocol.constants import (
    UART_WRITE_CHAR_UUID,
    UART_NOTIFY_CHAR_UUID,
    UART_WRITE_ALIPAY_CHAR_UUID,
    OTA_WRITE_CHAR_UUID,
    DIAL_CHAR_UUID,
)

MAC = sys.argv[1] if len(sys.argv) > 1 else "66:22:AA:00:42:78"

WRITE_PRIORITY = [
    ("UART Write", UART_WRITE_CHAR_UUID),
    ("UART AliPay", UART_WRITE_ALIPAY_CHAR_UUID),
    ("OTA Write", OTA_WRITE_CHAR_UUID),
    ("Dial Char", DIAL_CHAR_UUID),
]

rx_queue = asyncio.Queue()

def notification_handler(sender: int, data: bytes):
    ts = datetime.now()
    rx_queue.put_nowait((ts, data))

async def try_write(client, char_uuid: str, label: str, packet_data: bytes) -> bool:
    print(f"\n  --- Trying {label} ({char_uuid}) ---")
    try:
        await client.write_gatt_char(char_uuid, packet_data, response=True)
        print(f"  TX OK  ({len(packet_data)} bytes)")
        return True
    except Exception as e:
        print(f"  TX FAILED: {e}")
        return False

async def try_write_no_response(client, char_uuid: str, label: str, packet_data: bytes) -> bool:
    print(f"\n  --- Trying {label} ({char_uuid}) [write-without-response] ---")
    try:
        await client.write_gatt_char(char_uuid, packet_data, response=False)
        print(f"  TX OK (no response)  ({len(packet_data)} bytes)")
        return True
    except Exception as e:
        print(f"  TX FAILED: {e}")
        return False

async def main():
    print("=" * 72)
    print("BLE SEND - Time Sync Command Transmission")
    print(f"Target: {MAC}")
    print("=" * 72)
    print()

    # Build packets
    time_packet = build_set_time()
    dial_status_packet = build_dial_read_status()
    dial_info_packet = build_dial_read_info()

    packets = [
        ("SET_TIME (0x12,0x01)", time_packet),
        ("DIAL_READ_STATUS (0x20,0x01)", dial_status_packet),
        ("DIAL_READ_INFO (0x20,0x02)", dial_info_packet),
    ]

    print("Packets to send:")
    for name, pkt in packets:
        entry = format_packet(pkt.data, "TX")
        print(format_packet_line(entry))
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
        print(f"  CONNECTED")
        mtu = await client.mtu_size if hasattr(client, 'mtu_size') else '?'
        print(f"  MTU: {mtu}")
        print()

        print("[3] Enumerating characteristics to find writable ones...")
        services = await client.get_services()
        writable_chars = []
        writable_no_response_chars = []

        for service in services:
            for char in service.characteristics:
                cuuid = str(char.uuid).lower()
                if "write" in char.properties and "write-without-response" in char.properties:
                    writable_chars.append((cuuid, "write+write_without_response"))
                    writable_no_response_chars.append((cuuid, "write+write_without_response"))
                elif "write" in char.properties:
                    writable_chars.append((cuuid, "write"))
                elif "write-without-response" in char.properties:
                    writable_no_response_chars.append((cuuid, "write_without_response"))

        if not writable_chars and not writable_no_response_chars:
            print("  FATAL: No writable characteristics found!")
            print("  The watch does not support BLE write for this profile.")
            print("  => Try RFCOMM transport instead.")
            sys.exit(1)

        print(f"  Found {len(writable_chars)} write + {len(writable_no_response_chars)} write-without-response chars")
        for cuuid, props in writable_chars:
            print(f"    WRITE:      {cuuid}")
        for cuuid, props in writable_no_response_chars:
            if cuuid not in [c[0] for c in writable_chars]:
                print(f"    WR_NO_RESP: {cuuid}")
        print()

        # Subscribe to notify characteristics
        print("[4] Subscribing to notify characteristics...")
        for service in services:
            for char in service.characteristics:
                if "notify" in char.properties or "indicate" in char.properties:
                    try:
                        await client.start_notify(char.uuid, notification_handler)
                        print(f"  SUBSCRIBED: {char.uuid}")
                    except Exception as e:
                        print(f"  FAILED:     {char.uuid}  ({e})")

        # Check for the standard notify char specifically
        print()
        print("[5] Sending packets...")
        print("=" * 72)

        for name, pkt in packets:
            print(f"\n>>> Packet: {name}")
            entry = format_packet(pkt.data, "TX")
            print(format_packet_line(entry))

            sent_ok = False

            # Try write with response first (on write-capable chars)
            for cuuid, props in writable_chars:
                # Prioritize known UART
                if UART_WRITE_CHAR_UUID in cuuid:
                    if await try_write(client, cuuid, f"UART (known):{cuuid}", pkt.data):
                        sent_ok = True
                        break

            if not sent_ok:
                for cuuid, props in writable_chars:
                    if await try_write(client, cuuid, cuuid, pkt.data):
                        sent_ok = True
                        break

            # If write didn't work, try write-without-response
            if not sent_ok:
                for cuuid, props in writable_no_response_chars:
                    if cuuid not in [c[0] for c in writable_chars]:
                        if await try_write_no_response(client, cuuid, cuuid, pkt.data):
                            sent_ok = True
                            break

            if not sent_ok:
                print("  FAILED: Could not send on any characteristic")
            else:
                print(f"  Sent. Waiting 5s for response...")

        print()
        print("[6] Listening for responses (10 seconds total)...")
        print("=" * 72)

        deadline = asyncio.get_event_loop().time() + 10
        responses = []
        while asyncio.get_event_loop().time() < deadline:
            try:
                remaining = deadline - asyncio.get_event_loop().time()
                ts, data = await asyncio.wait_for(rx_queue.get(), timeout=max(0.1, remaining))
                responses.append((ts, data))
                entry = format_packet(data, "RX")
                print(format_packet_line(entry))
                print(f"  ASCII: {''.join(ch(b) if 32 <= b < 127 else '.' for b in data)}")
                print()
            except asyncio.TimeoutError:
                break

        print("=" * 72)
        print(f"\n[7] Result: {len(responses)} response(s) received")

        if responses:
            print("\n  *** SUCCESS: Watch responded! ***")
            for ts, data in responses:
                parsed = Packet.parse_response(data)
                if parsed["is_valid"]:
                    print(f"    Valid 0xCD packet:")
                    print(f"      Main cmd: 0x{parsed['main_cmd']:02X}")
                    print(f"      Sub cmd:  0x{parsed['sub_cmd']:02X}")
                    print(f"      Payload:  {parsed['payload'].hex(' ').upper()}")
                    resp_val = int.from_bytes(parsed['payload'], 'big') if parsed['payload'] else 0
                    if resp_val >= 1000:
                        print(f"      => ACK #{resp_val - 1000}")
                    elif resp_val == 2:
                        print(f"      => SUCCESS (2)")
                    elif resp_val == 1:
                        print(f"      => CHECKSUM ERROR (1)")
                print(f"    RAW: {data.hex(' ').upper()}")
        else:
            print("\n  *** NO RESPONSE from BLE ***")
            print("  The watch did not respond to any command via BLE.")
            print()
            print("  Possible causes:")
            print("    1. Wrong UUID for write (need to discover correct one)")
            print("    2. Watch requires pairing/bonding first")
            print("    3. Watch uses RFCOMM (classic Bluetooth) instead of BLE")
            print("    4. Write needs to be on a different service")
            print("    5. Packet needs different format on this transport")
            print()
            print("  => Proceed to RFCOMM test: python diagnostics/rfcomm_test.py")

        print()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
