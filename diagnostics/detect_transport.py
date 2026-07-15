"""
STEP 4: Automatic Transport Detection

Runs BLE test first. If successful, reports BLE as the transport.
Otherwise proceeds to RFCOMM test.

Produces a final summary report.

Usage:
    python diagnostics/detect_transport.py [mac_address]
"""

import sys
import os
import asyncio
import struct
import socket
import subprocess
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "HiWatchToolkit"))

from src.hiwatch_toolkit.protocol.commands import build_set_time, build_dial_read_status, build_dial_read_info
from src.hiwatch_toolkit.protocol.packet import Packet
from src.hiwatch_toolkit.protocol.debugger import format_packet, format_packet_line
from src.hiwatch_toolkit.protocol.constants import (
    UART_WRITE_CHAR_UUID,
    UART_NOTIFY_CHAR_UUID,
    UART_WRITE_ALIPAY_CHAR_UUID,
    OTA_WRITE_CHAR_UUID,
    DIAL_CHAR_UUID,
    UART_SERVICE_UUID,
    OTA_SERVICE_UUID,
    BATTERY_LEVEL_CHAR_UUID,
    FIRMWARE_REVISION_CHAR_UUID,
    MANUFACTURER_NAME_CHAR_UUID,
)

MAC = sys.argv[1] if len(sys.argv) > 1 else "66:22:AA:00:42:78"

# ======================================================================
# Result tracking
# ======================================================================
result = {
    "ble": "NOT TRIED",
    "rfcomm": "NOT TRIED",
    "transport": None,
    "uuid_or_channel": None,
    "response": None,
    "response_raw": None,
}

# ======================================================================
# BLE Test
# ======================================================================
async def test_ble():
    from bleak import BleakScanner, BleakClient

    packets = [
        ("SET_TIME", build_set_time()),
        ("DIAL_STATUS", build_dial_read_status()),
        ("DIAL_INFO", build_dial_read_info()),
    ]

    print("\n" + "=" * 72)
    print("  PHASE 1: BLE TEST")
    print("=" * 72)

    device = await BleakScanner.find_device_by_address(MAC, timeout=10)
    if not device:
        print("\n  BLE: Device not found in scan")
        result["ble"] = "FAILED (not found)"
        return False

    print(f"\n  Found: {device.name or '(no name)'}  RSSI={device.rssi}")

    async with BleakClient(device, timeout=30) as client:
        print(f"  Connected. MTU={await client.mtu_size if hasattr(client, 'mtu_size') else '?'}")

        services = await client.get_services()
        writable = []
        notify_chars = []

        for svc in services:
            for ch in services.characteristics:
                # Actually iterate properly
                pass

        for svc in services:
            for ch in svc.characteristics:
                cuuid = str(ch.uuid).lower()
                if "write" in ch.properties:
                    writable.append((cuuid, ch.uuid))
                if "notify" in ch.properties or "indicate" in ch.properties:
                    notify_chars.append((cuuid, ch.uuid))

        if not writable:
            print("  No writable characteristics found")
            result["ble"] = "FAILED (no write char)"
            return False

        print(f"  Writable chars: {len(writable)}")
        print(f"  Notify chars: {len(notify_chars)}")

        # Subscribe to notifies
        rx_queue = asyncio.Queue()
        def handler(s, d):
            rx_queue.put_nowait((datetime.now(), d))

        for cuuid, uuid in notify_chars:
            try:
                await client.start_notify(uuid, handler)
                print(f"  Subscribed: {cuuid[:34]}...")
            except Exception as e:
                print(f"  Subscribe failed {cuuid[:34]}...: {e}")

        # Try writing each packet
        responses = []
        for name, pkt in packets:
            data = pkt.data
            print(f"\n  Sending {name}: {data.hex(' ').upper()}")
            sent = False

            # Prioritize known UART write
            for cuuid, uuid in writable:
                if "6e400002" in cuuid or "6e400005" in cuuid:
                    try:
                        await client.write_gatt_char(uuid, data, response=True)
                        sent = True
                        print(f"  -> Sent on {cuuid[:34]}...")
                        break
                    except:
                        pass

            if not sent:
                for cuuid, uuid in writable:
                    if cuuid not in [c[0] for c in writable[:2]]:  # skip already tried
                        try:
                            await client.write_gatt_char(uuid, data, response=True)
                            sent = True
                            print(f"  -> Sent on {cuuid[:34]}...")
                            break
                        except:
                            pass

            if not sent:
                # Try write-without-response on remaining
                for cuuid, uuid in writable:
                    try:
                        await client.write_gatt_char(uuid, data, response=False)
                        sent = True
                        print(f"  -> Sent (no response) on {cuuid[:34]}...")
                        break
                    except:
                        pass

            if not sent:
                print("  -> Could not write")

        # Wait for responses
        print("\n  Waiting 8 seconds for responses...")
        deadline = asyncio.get_event_loop().time() + 8
        while asyncio.get_event_loop().time() < deadline:
            try:
                remaining = deadline - asyncio.get_event_loop().time()
                ts, data = await asyncio.wait_for(rx_queue.get(), timeout=max(0.1, remaining))
                responses.append(data)
                is_cd = data[0] == 0xCD if len(data) > 0 else False
                tag = "*** 0xCD PACKET ***" if is_cd else "(raw)"
                print(f"  RX [{ts.strftime('%H:%M:%S.%f')[:-3]}] ({len(data)}b) {tag}: {data.hex(' ').upper()}")
            except asyncio.TimeoutError:
                break

        # Also try GATT reads
        print("\n  Attempting GATT reads...")
        for uuid, label in [
            (BATTERY_LEVEL_CHAR_UUID, "Battery"),
            (FIRMWARE_REVISION_CHAR_UUID, "Firmware"),
            (MANUFACTURER_NAME_CHAR_UUID, "Manufacturer"),
        ]:
            try:
                val = await client.read_gatt_char(uuid)
                text = val.decode("utf-8", errors="replace").strip()
                print(f"  {label}: {text}")
                if len(text) > 0:
                    responses.append(val)
            except:
                pass

        if responses:
            result["ble"] = "SUCCESS"
            result["transport"] = "BLE"
            result["uuid_or_channel"] = UART_WRITE_CHAR_UUID
            result["response"] = responses[0].hex(" ").upper()
            result["response_raw"] = responses[0]
            return True
        else:
            result["ble"] = "FAILED (no response)"
            return False

# ======================================================================
# RFCOMM Test
# ======================================================================
def test_rfcomm():
    packets = [
        ("SET_TIME", build_set_time()),
        ("DIAL_STATUS", build_dial_read_status()),
        ("DIAL_INFO", build_dial_read_info()),
    ]

    print("\n" + "=" * 72)
    print("  PHASE 2: RFCOMM (CLASSIC BLUETOOTH) TEST")
    print("=" * 72)

    # Try SDP discovery
    print("\n  SDP discovery...")
    sdp_channels = []
    try:
        r = subprocess.run(["sdptool", "browse", MAC], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            for line in r.stdout.split("\n"):
                if "Channel" in line:
                    try:
                        sdp_channels.append(int(line.split()[-1]))
                    except:
                        pass
    except:
        pass

    if sdp_channels:
        print(f"  SDP channels: {sdp_channels}")
        scan_channels = sdp_channels
    else:
        print(f"  No SDP info, scanning 1-30")
        scan_channels = list(range(1, 31))

    # Probe channels
    print("\n  Probing channels...")
    connected_sock = None
    connected_ch = None

    for ch in scan_channels:
        if ch == 0:
            continue
        sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        sock.settimeout(3.0)
        try:
            sock.connect((MAC, ch))
            connected_sock = sock
            connected_ch = ch
            print(f"  Channel {ch}: CONNECTED!")
            break
        except Exception:
            sock.close()

    if connected_sock is None:
        print("\n  No RFCOMM channel accepted connection")
        # Try common serial channels directly with longer timeout
        for ch in [1, 2, 3, 4, 5, 10, 15, 20, 25]:
            sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            sock.settimeout(5.0)
            try:
                sock.connect((MAC, ch))
                connected_sock = sock
                connected_ch = ch
                print(f"  Channel {ch}: CONNECTED on retry!")
                break
            except Exception:
                sock.close()

    if connected_sock is None:
        result["rfcomm"] = "FAILED (no channel)"
        return False

    print(f"\n  Connected on RFCOMM channel {connected_ch}")

    # Send packets and wait for response
    responses = []
    for name, pkt in packets:
        data = pkt.data
        print(f"\n  Sending {name}: {data.hex(' ').upper()}")
        try:
            connected_sock.sendall(data)
            connected_sock.settimeout(5.0)
            while True:
                try:
                    chunk = connected_sock.recv(1024)
                    if not chunk:
                        break
                    print(f"  RX: {chunk.hex(' ').upper()}")
                    responses.append(chunk)
                    if len(chunk) >= 8 and chunk[0] == 0xCD:
                        field_len = struct.unpack(">H", chunk[1:3])[0]
                        if len(chunk) >= field_len + 3:
                            print(f"  *** Complete 0xCD protocol packet! ***")
                            break
                except socket.timeout:
                    break
        except Exception as e:
            print(f"  Error: {e}")
        print(f"  Done with {name}")

    connected_sock.close()

    if responses:
        result["rfcomm"] = "SUCCESS"
        result["transport"] = "RFCOMM"
        result["uuid_or_channel"] = str(connected_ch)
        result["response"] = responses[0].hex(" ").upper()
        result["response_raw"] = responses[0]
        return True
    else:
        result["rfcomm"] = "FAILED (no response)"
        return False

# ======================================================================
# Main
# ======================================================================
async def main():
    print("=" * 72)
    print("  TRANSPORT DETECTION ENGINE")
    print(f"  Target: {MAC}")
    print(f"  Time:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 72)
    print()
    print("  Strategy: BLE first → RFCOMM fallback")
    print()

    ble_ok = await test_ble()

    rfcomm_ok = False
    if not ble_ok:
        rfcomm_ok = test_rfcomm()

    # ==================================================================
    # FINAL REPORT
    # ==================================================================
    print()
    print("=" * 72)
    print("  FINAL TRANSPORT DETECTION REPORT")
    print("=" * 72)
    print()
    print(f"  BLE:     {result['ble']}")
    print(f"  RFCOMM:  {result['rfcomm']}")
    print()

    if result["transport"]:
        print(f"  TRANSPORT: {result['transport']}")
        print(f"  UUID/CH:   {result['uuid_or_channel']}")
        print(f"  RESPONSE:  {result['response']}")
        if result["response_raw"] and len(result["response_raw"]) >= 8:
            parsed = Packet.parse_response(result["response_raw"])
            if parsed["is_valid"]:
                print(f"  PARSED:    Main=0x{parsed['main_cmd']:02X} Sub=0x{parsed['sub_cmd']:02X}")
                print(f"             Payload={parsed['payload'].hex(' ').upper()}")
                resp_val = int.from_bytes(parsed["payload"], 'big') if parsed["payload"] else 0
                if resp_val >= 1000:
                    print(f"             => ACK #{resp_val - 1000}")
                elif resp_val == 2:
                    print(f"             => SUCCESS")
                elif resp_val == 1:
                    print(f"             => CHECKSUM ERROR")
                else:
                    print(f"             => Response code: {resp_val}")
        print()
        print("  STATUS: ✓ WORKING TRANSPORT FOUND")
        print()
        print("  RECOMMENDATION: Configure the application to use")
        print(f"  {result['transport'].lower()} with {result['uuid_or_channel']}")
    else:
        print("  TRANSPORT: NONE")
        print()
        print("  ✗ No working transport found.")
        print()
        print("  TROUBLESHOOTING:")
        print("  1. Is the watch powered on and in range?")
        print("  2. Is Bluetooth enabled on this computer?")
        print("  3. Try pairing first:")
        print("       bluetoothctl pair " + MAC)
        print("  4. Try connecting with bluetoothctl:")
        print("       bluetoothctl connect " + MAC)
        print("  5. Check dmesg for Bluetooth errors:")
        print("       dmesg | grep -i bluetooth")
        print("  6. Check Bluetooth service:")
        print("       systemctl status bluetooth")
        print("  7. Run RFCOMM test with sudo:")
        print("       sudo python diagnostics/rfcomm_test.py " + MAC)
        print("  8. Manually specify an RFCOMM channel:")
        print("       python diagnostics/rfcomm_test.py " + MAC + " --channel 1")
        print("  9. Check if watch advertises any services:")
        print("       sdptool browse " + MAC)

    print()
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
