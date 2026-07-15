"""
D-Bus GATT test: Write time sync packet and read response via BlueZ D-Bus API.

Connects to the already-known BLE GATT service at:
  /org/bluez/hci0/dev_66_22_AA_00_42_78

Write characteristic: service0020/char0021  (6e400002)
Notify characteristic: service0020/char0023 (6e400003)
"""

import sys
import os
import asyncio
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "HiWatchToolkit"))

from src.hiwatch_toolkit.protocol.commands import build_set_time, build_dial_read_status, build_dial_read_info
from src.hiwatch_toolkit.protocol.packet import Packet
from src.hiwatch_toolkit.protocol.debugger import format_packet, format_packet_line

from dbus_fast import Message, MessageType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.constants import BusType

DEVICE_PATH = "/org/bluez/hci0/dev_66_22_AA_00_42_78"
WRITE_CHAR_PATH = f"{DEVICE_PATH}/service0020/char0021"
NOTIFY_CHAR_PATH = f"{DEVICE_PATH}/service0020/char0023"
NOTIFY_CCCD_PATH = f"{NOTIFY_CHAR_PATH}/desc0025"

bus: MessageBus = None
responses = []

async def call_dbus(destination, path, interface, member, signature=None, body=None):
    msg = Message(
        destination=destination,
        path=path,
        interface=interface,
        member=member,
    )
    if signature is not None:
        msg.signature = signature
    if body is not None:
        msg.body = body
    reply = await bus.call(msg)
    if reply.message_type == MessageType.ERROR:
        raise Exception(f"D-Bus error: {reply.body}")
    return reply

async def properties_get(path, interface, prop):
    reply = await call_dbus(
        "org.bluez", path,
        "org.freedesktop.DBus.Properties",
        "Get",
        "ss",
        [interface, prop],
    )
    return reply.body[0].value if reply.body else None

async def start_notify(char_path):
    """Write 0x0001 to CCCD to enable notifications."""
    cccd_path = char_path[:-1] + "5"
    # Try to find the CCCD descriptor
    objects = (await call_dbus(
        "org.bluez", "/",
        "org.freedesktop.DBus.ObjectManager",
        "GetManagedObjects",
    )).body[0]
    
    # Find the CCCD for this characteristic
    for path, ifaces in objects.items():
        if "org.bluez.GattDescriptor1" in ifaces:
            desc = ifaces["org.bluez.GattDescriptor1"]
            if str(desc.get("UUID", "")) == "00002902-0000-1000-8000-00805f9b34fb" and path.startswith(char_path.rstrip("0123456789")):
                print(f"  Found CCCD: {path}")
                # Write 0x0001 to enable notifications
                msg = Message(
                    destination="org.bluez",
                    path=path,
                    interface="org.bluez.GattDescriptor1",
                    member="WriteValue",
                    signature="aya{sv}",
                    body=[Variant("ay", b"\x01\x00"), {}],
                )
                reply = await bus.call(msg)
                if reply.message_type == MessageType.ERROR:
                    print(f"  CCCD write error: {reply.body}")
                    return False
                print(f"  Notifications enabled!")
                return True
    
    print("  CCCD not found!")
    return False

async def read_char(char_path):
    """Read characteristic value."""
    reply = await call_dbus(
        "org.bluez", char_path,
        "org.bluez.GattCharacteristic1",
        "ReadValue",
        "a{sv}",
        [{}],
    )
    return bytes(reply.body[0]) if reply.body else None

async def write_char(char_path, data):
    """Write to characteristic with response."""
    msg = Message(
        destination="org.bluez",
        path=char_path,
        interface="org.bluez.GattCharacteristic1",
        member="WriteValue",
        signature="aya{sv}",
        body=[Variant("ay", data), {}],
    )
    reply = await bus.call(msg)
    if reply.message_type == MessageType.ERROR:
        raise Exception(f"Write error: {reply.body}")
    return True

async def write_char_without_response(char_path, data):
    """Write to characteristic without response."""
    msg = Message(
        destination="org.bluez",
        path=char_path,
        interface="org.bluez.GattCharacteristic1",
        member="WriteValue",
        signature="aya{sv}",
        body=[Variant("ay", data), {"type": Variant("s", "command")}],
    )
    reply = await bus.call(msg)
    if reply.message_type == MessageType.ERROR:
        raise Exception(f"Write error: {reply.body}")
    return True

async def register_notify_callback(char_path):
    """Register for PropertiesChanged signals on the notify characteristic."""
    import dbus_fast.service as service
    
    # We'll use a match rule instead of registering an object
    rule = f"interface='org.freedesktop.DBus.Properties',type='signal',path='{char_path}'"
    await bus.call(
        Message(
            destination="org.freedesktop.DBus",
            path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus",
            member="AddMatch",
            signature="s",
            body=[rule],
        )
    )
    
    # Listen for signals
    while True:
        msg = await bus.wait_for_message()
        if msg.path == char_path and msg.interface == "org.freedesktop.DBus.Properties":
            if msg.member == "PropertiesChanged":
                ifaces, changed, invalidated = msg.body
                if "org.bluez.GattCharacteristic1" in ifaces:
                    props = ifaces["org.bluez.GattCharacteristic1"]
                    if "Value" in props:
                        data = bytes(props["Value"].value)
                        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        print(f"\n[{ts}] RX ({len(data)}b): {data.hex(' ').upper()}")
                        asc = "".join(ch(b) if 32 <= b < 127 else "." for b in data)
                        print(f"          ASCII: {asc}")
                        responses.append(data)
                        
                        if data[0] == 0xCD:
                            print(f"          *** VALID 0xCD PACKET! ***")
                            parsed = Packet.parse_response(data)
                            if parsed["is_valid"]:
                                print(f"          Main=0x{parsed['main_cmd']:02X} Sub=0x{parsed['sub_cmd']:02X}")
                                resp_val = int.from_bytes(parsed["payload"], 'big') if parsed["payload"] else 0
                                if resp_val >= 1000:
                                    print(f"          => ACK #{resp_val - 1000}")

async def main():
    global bus
    
    print("=" * 72)
    print("D-Bus GATT Direct Test - Write Time Sync to Watch")
    print("=" * 72)
    print()
    
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    print("Connected to D-Bus system bus")
    
    # Step 1: Check device properties
    print("\n[1] Checking device status...")
    for prop in ["Connected", "ServicesResolved", "Name", "Address"]:
        val = await properties_get(DEVICE_PATH, "org.bluez.Device1", prop)
        print(f"  {prop}: {val}")
    
    # Step 2: Read current values
    print("\n[2] Reading current characteristic values...")
    for name, path in [("Write (6e400002)", WRITE_CHAR_PATH), ("Notify (6e400003)", NOTIFY_CHAR_PATH)]:
        try:
            val = await read_char(path)
            if val:
                print(f"  {name}: {val.hex(' ').upper()}")
            else:
                print(f"  {name}: (empty)")
        except Exception as e:
            print(f"  {name}: {e}")
    
    # Step 3: Enable notifications
    print("\n[3] Enabling notifications on notify characteristic...")
    await start_notify(NOTIFY_CHAR_PATH)
    
    # Step 4: Start listening for responses in background
    print("\n[4] Starting notification listener...")
    listen_task = asyncio.create_task(register_notify_callback(NOTIFY_CHAR_PATH))
    
    # Step 5: Build and send packets
    packets = [
        ("SET_TIME", build_set_time()),
        ("DIAL_STATUS", build_dial_read_status()),
        ("DIAL_INFO", build_dial_read_info()),
    ]
    
    for name, pkt in packets:
        data = pkt.data
        entry = format_packet(pkt.data, "TX")
        print(f"\n>>> {name}")
        print(format_packet_line(entry))
        
        # Try write with response first
        try:
            print(f"  Sending via WriteValue (with response)...")
            await write_char(WRITE_CHAR_PATH, data)
            print(f"  OK")
        except Exception as e:
            print(f"  Write with response failed: {e}")
            try:
                print(f"  Sending via WriteValue (command/write-without-response)...")
                await write_char_without_response(WRITE_CHAR_PATH, data)
                print(f"  OK")
            except Exception as e2:
                print(f"  Write without response also failed: {e2}")
        
        await asyncio.sleep(2)
    
    # Step 6: Wait for responses
    print(f"\n[6] Waiting 15 seconds for responses...")
    await asyncio.sleep(15)
    listen_task.cancel()
    
    print()
    print("=" * 72)
    print(f"  RESULT: {len(responses)} response(s) received")
    print("=" * 72)
    
    if responses:
        for data in responses:
            if data[0] == 0xCD:
                print("\n  *** BLE TRANSPORT CONFIRMED! ***")
                parsed = Packet.parse_response(data)
                if parsed["is_valid"]:
                    print(f"  Valid 0xCD packet received!")
                    print(f"  Main=0x{parsed['main_cmd']:02X} Sub=0x{parsed['sub_cmd']:02X}")
                    print(f"  Payload: {parsed['payload'].hex(' ').upper()}")
                    resp_val = int.from_bytes(parsed["payload"], 'big') if parsed["payload"] else 0
                    if resp_val >= 1000:
                        print(f"  => ACK #{resp_val - 1000}")
                    elif resp_val == 2:
                        print(f"  => SUCCESS")
                    elif resp_val == 1:
                        print(f"  => CHECKSUM ERROR")
                print(f"\n  TRANSPORT: BLE (Nordic UART-like)")
                print(f"  SERVICE UUID: 6e400801-b5a3-f393-e0a9-e50e24dcca9d")
                print(f"  WRITE CHAR:   6e400002-b5a3-f393-e0a9-e50e24dcca9d")
                print(f"  NOTIFY CHAR:  6e400003-b5a3-f393-e0a9-e50e24dcca9d")
            else:
                print(f"\n  Non-0xCD response: {data.hex(' ').upper()}")
    else:
        print("\n  No responses received via BLE GATT.")
        print("  Possible explanations:")
        print("  1. Watch requires explicit pairing (already bonded)")
        print("  2. Watch needs app-level handshake before accepting commands")
        print("  3. Wrong characteristic for write/notify")
        print("  4. Try RFCOMM instead (classic Bluetooth Serial Port)")


if __name__ == "__main__":
    asyncio.run(main())
