"""
STEP 3: RFCOMM (Classic Bluetooth) Test

Attempts to connect to the watch via RFCOMM serial port on channels 1-30.
On the first successful connection, sends the time sync 0xCD packet
and waits for a response.

Usage:
    python diagnostics/rfcomm_test.py [mac_address] [--channel N]

Default MAC: 66:22:AA:00:42:78
"""

import sys
import os
import socket
import time
import struct
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "HiWatchToolkit"))

from src.hiwatch_toolkit.protocol.commands import build_set_time, build_dial_read_status, build_dial_read_info
from src.hiwatch_toolkit.protocol.packet import Packet
from src.hiwatch_toolkit.protocol.debugger import format_packet, format_packet_line

MAC = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "66:22:AA:00:42:78"

SPECIFIC_CHANNEL = None
for i, arg in enumerate(sys.argv):
    if arg == "--channel" and i + 1 < len(sys.argv):
        SPECIFIC_CHANNEL = int(sys.argv[i + 1])

def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}")

def discover_sdp_channels(mac: str):
    """Try to discover RFCOMM channels via sdptool browse."""
    log("Checking if bluetooth.service is reachable...")
    import subprocess
    try:
        result = subprocess.run(
            ["sdptool", "browse", mac],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            channels = []
            for line in result.stdout.split("\n"):
                line = line.strip()
                if "Channel" in line:
                    try:
                        ch = int(line.split()[-1])
                        channels.append(ch)
                    except:
                        pass
            if channels:
                log(f"SDP discovered channels: {sorted(set(channels))}")
                return sorted(set(channels))
            else:
                log("SDP browse completed but no channels found")
        else:
            log(f"sdptool browse failed (rc={result.returncode})")
            # Try bluetoothctl as fallback
            result2 = subprocess.run(
                ["bluetoothctl", "info", mac],
                capture_output=True, text=True, timeout=10
            )
            if result2.stdout:
                log(f"bluetoothctl info output:\n{result2.stdout[:2000]}")
    except FileNotFoundError:
        log("sdptool not found (install bluez-tools or bluez-deprecated)")
    except subprocess.TimeoutExpired:
        log("sdptool timed out")
    except Exception as e:
        log(f"SDP discovery error: {e}")
    return []

def rfcomm_connect(mac: str, channel: int, timeout_sec: float = 5.0):
    """Attempt an RFCOMM connection on a specific channel."""
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    sock.settimeout(timeout_sec)
    try:
        sock.connect((mac, channel))
        return sock
    except Exception:
        sock.close()
        return None

def send_and_recv(sock, data: bytes, timeout_sec: float = 10.0) -> bytes:
    """Send data over RFCOMM and wait for response."""
    sock.settimeout(timeout_sec)
    log(f"TX ({len(data)} bytes)")
    entry = format_packet(data, "TX")
    print(f"  {entry.replace(chr(10), chr(10) + '  ')}")
    print(f"  RAW: {data.hex(' ').upper()}")

    start = time.time()
    sock.sendall(data)

    response = b""
    while time.time() - start < timeout_sec:
        try:
            chunk = sock.recv(1024)
            if chunk:
                response += chunk
                log(f"RX chunk ({len(chunk)} bytes): {chunk.hex(' ').upper()}")
                # Check if we have a complete 0xCD packet
                if len(response) >= 8 and response[0] == 0xCD:
                    field_len = struct.unpack(">H", response[1:3])[0]
                    total_len = field_len + 3
                    if len(response) >= total_len:
                        log(f"Complete 0xCD packet received ({total_len} bytes)")
                        return response
            else:
                break
        except socket.timeout:
            break

    if response:
        # Check for partial 0xCD packet
        if response[0:1] == b"\xcd" or response[0:1] == b"\xCD":
            log(f"Partial potential 0xCD packet in {len(response)} bytes")
    return response

async def main():
    print("=" * 72)
    print("RFCOMM TEST - Classic Bluetooth Serial Port Probe")
    print(f"Target: {MAC}")
    print("=" * 72)
    print()

    # Build packets
    time_packet = build_set_time()
    dial_status_packet = build_dial_read_status()
    dial_info_packet = build_dial_read_info()

    test_packets = [
        ("SET_TIME (0x12,0x01)", time_packet),
        ("DIAL_READ_STATUS (0x20,0x01)", dial_status_packet),
        ("DIAL_READ_INFO (0x20,0x02)", dial_info_packet),
    ]

    print("Test packets:")
    for name, pkt in test_packets:
        entry = format_packet(pkt.data, "TX")
        print(f"  {name}:  {pkt.data.hex(' ').upper()}")
    print()

    # Step 1: SDP discovery
    print("[1] SDP service discovery...")
    sdp_channels = discover_sdp_channels(MAC)
    print(f"  SDP result: {sdp_channels}")
    print()

    # Step 2: Try specific channel or scan channels
    if SPECIFIC_CHANNEL is not None:
        scan_channels = [SPECIFIC_CHANNEL]
        log(f"Using specific channel: {SPECIFIC_CHANNEL}")
    elif sdp_channels:
        scan_channels = sdp_channels
        log(f"Using SDP-discovered channels: {scan_channels}")
    else:
        scan_channels = list(range(1, 31))
        log(f"No SDP data, scanning channels 1-30")

    print()
    print("[2] Probing RFCOMM channels...")
    print("=" * 72)

    connected_channel = None
    connected_sock = None

    for ch in scan_channels:
        if ch == 0:
            continue
        sock = rfcomm_connect(MAC, ch, timeout_sec=3.0)
        if sock:
            log(f"CHANNEL {ch}: CONNECTED!")
            connected_channel = ch
            connected_sock = sock
            break
        else:
            log(f"CHANNEL {ch}: no response")

    print()
    if connected_sock is None:
        print("=" * 72)
        print("\n  *** RFCOMM: NO CHANNEL CONNECTED ***")
        print()
        print("  The watch did not accept RFCOMM connections on any scanned channel.")
        print()
        print("  Possible causes:")
        print("    1. Bluetooth classic not enabled on the watch")
        print("    2. Watch requires prior bonding/pairing")
        print("    3. RFCOMM channel is outside 1-30 range")
        print("    4. `bluetoothd` not running or no permissions")
        print("    5. Need to run as root: sudo python diagnostics/rfcomm_test.py")
        print("    6. Need to pair first: bluetoothctl pair 66:22:AA:00:42:78")
        print()
        print("  => Run with: sudo python diagnostics/rfcomm_test.py")
        print("  => Or pair first: bluetoothctl pair 66:22:AA:00:42:78")
        print()
        sys.exit(1)

    print(f"[3] Connected on RFCOMM channel {connected_channel}")
    print()

    # Step 3: Send packets
    for name, pkt in test_packets:
        print(f">>> Sending: {name}")
        response = send_and_recv(connected_sock, pkt.data, timeout_sec=10.0)
        print()

        if response:
            entry = format_packet(response, "RX")
            print(format_packet_line(entry))
            asc = "".join(ch(b) if 32 <= b < 127 else "." for b in response)
            print(f"  ASCII: {asc}")
            print()

            parsed = Packet.parse_response(response)
            if parsed["is_valid"]:
                resp_val = int.from_bytes(parsed["payload"], 'big') if parsed["payload"] else 0
                if resp_val >= 1000:
                    log(f"*** ACK #{resp_val - 1000} RECEIVED ***")
                elif resp_val == 2:
                    log(f"*** SUCCESS RESPONSE ***")

                log("*** RFCOMM WORKS! Transport is classic Bluetooth Serial Port ***")
                print()
                print("=" * 72)
                print("  TRANSPORT: RFCOMM (Classic Bluetooth Serial Port)")
                print(f"  CHANNEL:   {connected_channel}")
                print("  STATUS:    WORKING")
                print("=" * 72)
                connected_sock.close()
                sys.exit(0)
        else:
            log(f"No response for {name}")

    log("Packets sent but no valid 0xCD response received over RFCOMM")
    log("Response bytes might be in different format on this transport")

    connected_sock.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
