"""
BLE AcquireWrite test - uses D-Bus AcquireWrite/AcquireNotify to get file
descriptors for direct I/O with the watch's BLE GATT characteristics.

This bypasses bluetoothctl's write command parsing issues.
"""

import sys
import os
import asyncio
import struct
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "HiWatchToolkit"))

from src.hiwatch_toolkit.protocol.commands import build_set_time, build_dial_read_status, build_dial_read_info
from src.hiwatch_toolkit.protocol.packet import Packet
from src.hiwatch_toolkit.protocol.debugger import format_packet, format_packet_line, parse_packet

from dbus_fast import Message, MessageType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.constants import BusType

DEVICE_PATH = "/org/bluez/hci0/dev_66_22_AA_00_42_78"
WRITE_CHAR_PATH = f"{DEVICE_PATH}/service0020/char0021"
NOTIFY_CHAR_PATH = f"{DEVICE_PATH}/service0020/char0023"

bus = None
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

async def acquire_write(char_path):
    """AcquireWrite returns a file descriptor for writing."""
    msg = Message(
        destination="org.bluez",
        path=char_path,
        interface="org.bluez.GattCharacteristic1",
        member="AcquireWrite",
        signature="a{sv}",
        body=[{}],
    )
    reply = await bus.call(msg)
    if reply.message_type == MessageType.ERROR:
        raise Exception(f"AcquireWrite error: {reply.body}")
    # Returns (fd, mtu) where fd is a Unix file descriptor
    fd = reply.body[0]
    mtu = reply.body[1]
    return fd, mtu

async def acquire_notify(char_path):
    """AcquireNotify returns a file descriptor for reading notifications."""
    msg = Message(
        destination="org.bluez",
        path=char_path,
        interface="org.bluez.GattCharacteristic1",
        member="AcquireNotify",
        signature="a{sv}",
        body=[{}],
    )
    reply = await bus.call(msg)
    if reply.message_type == MessageType.ERROR:
        raise Exception(f"AcquireNotify error: {reply.body}")
    fd = reply.body[0]
    mtu = reply.body[1]
    return fd, mtu

async def main():
    global bus

    print("=" * 72)
    print("BLE AcquireWrite/AcquireNotify - Direct GATT I/O")
    print("=" * 72)
    print()

    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    print("Connected to D-Bus")

    # Check device status
    reply = await call_dbus(
        "org.bluez", DEVICE_PATH,
        "org.freedesktop.DBus.Properties",
        "GetAll",
        "s",
        ["org.bluez.Device1"],
    )
    props = reply.body[0]
    print(f"Connected: {props.get('Connected')}")
    print(f"ServicesResolved: {props.get('ServicesResolved')}")
    print(f"Name: {props.get('Name')}")
    print()

    # Build packets
    packets = [
        ("SET_TIME", build_set_time()),
        ("DIAL_STATUS", build_dial_read_status()),
        ("DIAL_INFO", build_dial_read_info()),
    ]
    print("Packets to send:")
    for name, pkt in packets:
        entry = format_packet(pkt.data, "TX")
        print(format_packet_line(entry))
    print()

    # Acquire the write fd
    print("[1] Acquiring write fd...")
    try:
        write_fd, mtu = await acquire_write(WRITE_CHAR_PATH)
        print(f"  AcquireWrite: fd={write_fd}, MTU={mtu}")
        write_fh = os.fdopen(write_fd, "wb", buffering=0)
    except Exception as e:
        print(f"  AcquireWrite failed: {e}")
        print("  Trying WriteValue with correct signature instead...")
        write_fh = None

    # Acquire the notify fd
    print("[2] Acquiring notify fd...")
    notify_fh = None
    try:
        notify_fd, mtu_n = await acquire_notify(NOTIFY_CHAR_PATH)
        print(f"  AcquireNotify: fd={notify_fd}, MTU={mtu_n}")
        notify_fh = os.fdopen(notify_fd, "rb", buffering=0)
    except Exception as e:
        print(f"  AcquireNotify failed: {e}")
        print("  Notifications may not work")

    print()

    # Start a background reader for notifications
    async def read_notifications():
        if not notify_fh:
            return
        loop = asyncio.get_event_loop()
        while True:
            try:
                data = await loop.run_in_executor(None, lambda: notify_fh.read(512))
                if not data:
                    break
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                responses.append(data)
                asc = "".join(ch(b) if 32 <= b < 127 else "." for b in data)
                is_cd = data[0] == 0xCD if len(data) > 0 else False
                tag = "*** 0xCD PACKET ***" if is_cd else "(raw)"
                print(f"\n[{ts}] RX ({len(data)}b) {tag}: {data.hex(' ').upper()}")
                print(f"          ASCII: {asc}")
                if is_cd:
                    parsed = parse_packet(data)
                    if parsed.is_valid:
                        print(f"          Main=0x{parsed.main_cmd:02X} ({parsed.main_cmd_name})")
                        print(f"          Sub=0x{parsed.sub_cmd:02X} ({parsed.sub_cmd_name})")
                        print(f"          Payload: {parsed.payload.hex(' ').upper()}")
                        resp_val = int.from_bytes(parsed.payload, 'big') if parsed.payload else 0
                        if resp_val >= 1000:
                            print(f"          => ACK #{resp_val - 1000}")
            except Exception as e:
                print(f"\n  Notify read error: {e}")
                break
        print("\n  Notify reader stopped")

    if notify_fh:
        notify_task = asyncio.create_task(read_notifications())
    else:
        notify_task = None

    # Send packets
    print("[3] Sending packets...")
    print("-" * 72)

    for name, pkt in packets:
        data = pkt.data
        print(f"\n>>> {name}")

        if write_fh:
            # Write via AcquireWrite fd
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, lambda: write_fh.write(data))
                await loop.run_in_executor(None, lambda: write_fh.flush())
                print(f"  TX via fd: {data.hex(' ').upper()}")
                print(f"  OK ({len(data)} bytes)")
            except Exception as e:
                print(f"  Write failed: {e}")
        else:
            # Fallback: try D-Bus WriteValue directly with correct signature
            print(f"  Trying D-Bus WriteValue...")
            try:
                # Correct signature: ay (array of bytes)
                msg = Message(
                    destination="org.bluez",
                    path=WRITE_CHAR_PATH,
                    interface="org.bluez.GattCharacteristic1",
                    member="WriteValue",
                    signature="aya{sv}",
                    body=[list(data), {}],
                )
                reply = await bus.call(msg)
                if reply.message_type == MessageType.ERROR:
                    print(f"  WriteValue failed: {reply.body}")
                else:
                    print(f"  WriteValue OK!")
            except Exception as e:
                print(f"  WriteValue exception: {e}")

        await asyncio.sleep(3)

    # Wait for remaining notifications
    print("\n[4] Waiting 5 seconds for more responses...")
    await asyncio.sleep(5)

    if notify_task:
        notify_task.cancel()

    if write_fh:
        write_fh.close()

    # Summary
    print()
    print("=" * 72)
    print(f"  RESULT: {len(responses)} response(s) received")
    print("=" * 72)

    if responses:
        for data in responses:
            if len(data) > 0 and data[0] == 0xCD:
                parsed = parse_packet(data)
                if parsed.is_valid:
                    print(f"\n  VALID 0xCD packet:")
                    print(f"  Main=0x{parsed.main_cmd:02X} ({parsed.main_cmd_name})")
                    print(f"  Sub=0x{parsed.sub_cmd:02X} ({parsed.sub_cmd_name})")
                    print(f"  Payload ({parsed.payload_length}b): {parsed.payload.hex(' ').upper()}")

        print(f"\n  *** BLE GATT TRANSPORT CONFIRMED! ***")
        print(f"  SERVICE UUID: 6e400801-b5a3-f393-e0a9-e50e24dcca9d")
        print(f"  WRITE CHAR:   6e400002-b5a3-f393-e0a9-e50e24dcca9d")
        print(f"  NOTIFY CHAR:  6e400003-b5a3-f393-e0a9-e50e24dcca9d")
        print()
        print(f"  NOTE: The existing app uses:")
        print(f"    SERVICE UUID: 6e400001-b5a3-f393-e0a9-e50e24dcca9d")
        print(f"  The watch uses:")
        print(f"    SERVICE UUID: 6e400801-b5a3-f393-e0a9-e50e24dcca9d")
        print(f"  FIX NEEDED: Update UART_SERVICE_UUID from 6e400001 to 6e400801")
    else:
        print("\n  No responses. Checking if write succeeded but no response came.")
        print("  This might mean the packet format is wrong for this watch.")

    print()


if __name__ == "__main__":
    asyncio.run(main())
