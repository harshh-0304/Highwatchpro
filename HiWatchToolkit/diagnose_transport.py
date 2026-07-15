#!/usr/bin/env python3
"""
TRANSPORT DIAGNOSTIC TOOL — Ultra3 Smartwatch

This tool makes NO assumptions about the transport.
It systematically probes every possible communication channel
and reports hard evidence.

Usage:
    python3 diagnose_transport.py [MAC_ADDRESS]

Default MAC: 66:22:AA:00:42:78
"""

import asyncio
import socket
import struct
import sys
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime

# Ensure src path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

ADDR = sys.argv[1] if len(sys.argv) > 1 else "66:22:AA:00:42:78"
DEVICE_PATH = f"/org/bluez/hci0/dev_{ADDR.replace(':', '_')}"

# ── Packet protocol helpers ─────────────────────────────────────────────

def make_packet(main_cmd: int, sub_cmd: int, payload: bytes = b"") -> bytes:
    """Build a 0xCD protocol packet (matching SendData.getProtocol)."""
    total_len = 8 + len(payload)
    buf = bytearray(total_len)
    buf[0] = 0xCD
    len_field = total_len - 3
    buf[1] = (len_field >> 8) & 0xFF
    buf[2] = len_field & 0xFF
    buf[3] = main_cmd & 0xFF
    buf[4] = 0x01  # version
    buf[5] = sub_cmd & 0xFF
    plen = len(payload)
    buf[6] = (plen >> 8) & 0xFF
    buf[7] = plen & 0xFF
    buf[8:] = payload
    return bytes(buf)

def make_no_value_packet(main_cmd: int, sub_cmd: int) -> bytes:
    return make_packet(main_cmd, sub_cmd, b"")

def parse_packet(data: bytes) -> dict:
    result = {
        "valid": False,
        "header": None,
        "length": None,
        "main_cmd": None,
        "version": None,
        "sub_cmd": None,
        "payload_length": None,
        "payload": b"",
        "error": "",
    }
    if len(data) < 8:
        result["error"] = f"Too short: {len(data)} bytes"
        return result
    if data[0] != 0xCD:
        result["error"] = f"Bad header: 0x{data[0]:02X}"
        return result
    result["header"] = data[0]
    field_len = (data[1] << 8) | data[2]
    result["length"] = field_len + 3
    result["main_cmd"] = data[3]
    result["version"] = data[4]
    result["sub_cmd"] = data[5]
    plen = (data[6] << 8) | data[7]
    result["payload_length"] = plen
    result["payload"] = data[8:8 + plen] if plen > 0 else b""
    result["valid"] = True
    return result


# ═══════════════════════════════════════════════════════════════════════════
# STEP 1: BLE GATT Service Enumeration
# ═══════════════════════════════════════════════════════════════════════════

async def step1_ble_gatt_enumeration():
    """Enumerate every BLE GATT service and characteristic."""
    print("\n" + "═" * 70)
    print("STEP 1: BLE GATT SERVICE ENUMERATION")
    print("═" * 70)

    from bleak import BleakClient, BleakScanner

    # 1a — Find device from cache
    scanner = BleakScanner()
    await scanner.start()
    await asyncio.sleep(2)
    await scanner.stop()

    device = None
    for d in scanner.discovered_devices:
        if d.address.upper() == ADDR.upper():
            device = d
            break

    if not device:
        # Try direct connection from address
        print("  Device not in scanner cache. Creating BLEDevice from address...")
        from bleak.backends.device import BLEDevice
        details = {
            "path": DEVICE_PATH,
            "props": {"Address": ADDR, "AddressType": "public", "Name": "Ultra3"}
        }
        device = BLEDevice(ADDR, "Ultra3", details=details)

    print(f"\n  Target device: {device.name} ({device.address})")
    print(f"  Details: {device.details}")

    # 1b — Connect and enumerate
    print(f"\n  Connecting via BLE (timeout=20s)...")
    client = BleakClient(device, timeout=20.0)

    try:
        await client.connect()
        print(f"  Connected!  is_connected={client.is_connected}")
        print(f"  MTU: {client.mtu_size}")
        print(f"  Services resolved: {client.services.resolved if hasattr(client.services, 'resolved') else 'N/A'}")
        print()

        # Poll service resolution for up to 15 seconds
        print("  Polling service resolution...")
        for i in range(15):
            svc_count = len(client.services.services)
            print(f"    t={i + 1}s: service count = {svc_count}")
            if svc_count > 0:
                break
            await asyncio.sleep(1)

        print(f"\n  ── FINAL SERVICE COUNT: {len(client.services.services)} ──")

        if client.services.services:
            for svc_uuid, svc in client.services.services.items():
                print(f"\n  ┌─ Service: {svc_uuid}")
                print(f"  │    Description: {svc.description}")
                print(f"  │    Handle: {svc.handle}")
                for char in svc.characteristics:
                    props = ", ".join(char.properties)
                    print(f"  ├── Char: {char.uuid}")
                    print(f"  │       Properties: [{props}]")
                    print(f"  │       Handle: {char.handle}")
                    # Try reading
                    try:
                        val = await client.read_gatt_char(char.uuid)
                        print(f"  │       Value: {val.hex(' ').upper() if val else '(empty)'}")
                    except Exception as e:
                        print(f"  │       Read: FAILED — {e}")
                    # List descriptors
                    for desc in char.descriptors:
                        try:
                            dval = await client.read_gatt_descriptor(desc.handle)
                            print(f"  │       Desc {desc.uuid}: {dval.hex(' ').upper()}")
                        except:
                            print(f"  │       Desc {desc.uuid}: (read failed)")
        else:
            print("\n  ⚠  NO SERVICES in BleakClient.services")
            print("  → Will check D-Bus GATT tree directly in STEP 2")

        await client.disconnect()
        print("\n  BLE disconnected")

        return client.services.services if client.services.services else {}

    except Exception as e:
        print(f"\n  ⚠  BLE connection error: {e}")
        import traceback
        traceback.print_exc()
        return {}


# ═══════════════════════════════════════════════════════════════════════════
# STEP 2: D-Bus Direct GATT Tree Inspection
# ═══════════════════════════════════════════════════════════════════════════

async def step2_dbus_gatt_tree():
    """Directly inspect the BlueZ D-Bus GATT service tree."""
    print("\n" + "═" * 70)
    print("STEP 2: D-BUS GATT TREE INSPECTION")
    print("═" * 70)

    from dbus_fast.aio import MessageBus
    from dbus_fast import DBusError

    bus = await MessageBus().connect()

    # Check if device object exists
    print(f"\n  Checking device path: {DEVICE_PATH}")
    try:
        xml = await bus.introspect("org.bluez", DEVICE_PATH)
        root = ET.fromstring(xml)
        print(f"  Device object EXISTS")
        print(f"\n  D-Bus child nodes:")
        for node in root.findall("node"):
            name = node.attrib.get("name", "")
            print(f"    ─ {name}")

        # If there are GATT service nodes, enumerate them
        gatt_services = []
        for node in root.findall("node"):
            name = node.attrib.get("name", "")
            gatt_services.append(name)

        return gatt_services

    except Exception as e:
        print(f"  Device path D-Bus error: {e}")

        # Try broader search — list all children of the adapter
        adapter_path = f"/org/bluez/hci0"
        try:
            xml = await bus.introspect("org.bluez", adapter_path)
            root = ET.fromstring(xml)
            print(f"\n  Adapter {adapter_path} children:")
            for node in root.findall("node"):
                name = node.attrib.get("name", "")
                if ADDR.replace(":", "_").upper() in name.upper():
                    print(f"    → {name} (MATCHES our device)")
            return []
        except Exception as e2:
            print(f"  Adapter introspection error: {e2}")
            return []
    finally:
        bus.disconnect()


# ═══════════════════════════════════════════════════════════════════════════
# STEP 3: RFCOMM Serial Port Probe
# ═══════════════════════════════════════════════════════════════════════════

async def step3_rfcomm_probe():
    """
    Try RFCOMM connection and send protocol packets.
    NOTE: Requires CAP_NET_ADMIN or root.
    """
    print("\n" + "═" * 70)
    print("STEP 3: RFCOMM SERIAL PORT PROBE")
    print("═" * 70)

    # Try to connect via RFCOMM socket
    for channel in [1, 2, 3, 5, 10, 15, 20]:
        try:
            sock = socket.socket(
                socket.AF_BLUETOOTH,
                socket.SOCK_STREAM,
                socket.BTPROTO_RFCOMM,
            )
            sock.settimeout(3.0)
            sock.connect((ADDR, channel))
            print(f"\n  ✅ RFCOMM channel {channel}: CONNECTED")

            # Send a time-sync packet (0xCD packet)
            probe = make_packet(0x12, 0x01, b"\x00\x00\x00\x00")
            print(f"  TX ({len(probe)} bytes): {probe.hex(' ').upper()}")
            sock.sendall(probe)

            # Wait for response
            sock.settimeout(2.0)
            try:
                resp = sock.recv(1024)
                print(f"  RX ({len(resp)} bytes): {resp.hex(' ').upper()}")
                if resp and resp[0] == 0xCD:
                    parsed = parse_packet(resp)
                    print(f"  → Valid 0xCD packet!")
                    print(f"    Main=0x{parsed['main_cmd']:02X}")
                    print(f"    Sub=0x{parsed['sub_cmd']:02X}")
                    print(f"    Payload: {parsed['payload'].hex(' ').upper()}")
                else:
                    print(f"  → Raw data (not 0xCD)")
            except socket.timeout:
                print(f"  RX: timeout (no response)")

            sock.close()

        except PermissionError:
            print(f"  ✗ RFCOMM channel {channel}: Permission denied (need root/cap_net_admin)")
            if channel == 2:
                print("    → This is the KNOWN working channel but needs privileges.")
                print("    → Run: sudo setcap cap_net_raw,cap_net_admin+eip /usr/bin/python3")
            break  # First permission error means we won't be able to try any more
        except OSError as e:
            if "Device or resource busy" in str(e):
                print(f"  ∼ RFCOMM channel {channel}: Busy (in use by another profile)")
                continue
            elif "Permission denied" in str(e):
                print(f"  ✗ RFCOMM channel {channel}: Permission denied")
                break
            else:
                print(f"  ∼ RFCOMM channel {channel}: {e}")
                continue
        except Exception as e:
            print(f"  ∼ RFCOMM channel {channel}: {e}")
            continue


# ═══════════════════════════════════════════════════════════════════════════
# STEP 4: BLE Connection with Notification Testing
# ═══════════════════════════════════════════════════════════════════════════

async def step4_ble_notification_test():
    """
    Try writing to known BLE UUIDs and see if any respond with notifications.
    Tests the Nordic UART service UUIDs and the 0xFFFF vendor UUID.
    """
    print("\n" + "═" * 70)
    print("STEP 4: BLE WRITE + NOTIFICATION PROBE")
    print("═" * 70)

    from bleak import BleakClient, BleakScanner

    scanner = BleakScanner()
    await scanner.start()
    await asyncio.sleep(2)
    await scanner.stop()

    device = None
    for d in scanner.discovered_devices:
        if d.address.upper() == ADDR.upper():
            device = d
            break

    if not device:
        print("  Device not found in cache — can't test BLE notifications")
        return

    # UUIDs to test — known from APK reverse engineering
    TEST_UUIDS = {
        "Nordic UART TX": "6e400002-b5a3-f393-e0a9-e50e24dcca9e",
        "Nordic UART RX": "6e400003-b5a3-f393-e0a9-e50e24dcca9e",
        "Vendor FFFF": "0000ffff-0000-1000-8000-00805f9b34fb",
        "OTA Write": "0000ff01-0000-1000-8000-00805f9b34fb",
        "OTA Notify": "0000ff02-0000-1000-8000-00805f9b34fb",
    }

    client = BleakClient(device, timeout=15.0)
    notifications = []

    def notification_handler(sender, data):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"      📩 [{ts}] NOTIFICATION from {sender}: {data.hex(' ').upper()}")
        notifications.append((ts, sender, data))

    try:
        await client.connect()
        print(f"  Connected! is_connected={client.is_connected}")
        print(f"  Services in collection: {len(client.services.services)}")

        if client.services.services:
            # List actual services found
            for svc_uuid, svc in client.services.services.items():
                print(f"\n  Service: {svc_uuid}")
                for char in svc.characteristics:
                    print(f"    Char {char.uuid}: [{', '.join(char.properties)}]")
        else:
            print("\n  ⚠  Services collection is EMPTY")
            print("  → Skipping write tests (no characteristics to target)")

        # If we found FFFF or Nordic UART chars, try writing and notification
        # But if NO services at all, this is the critical finding.

    except Exception as e:
        print(f"  BLE error: {e}")
    finally:
        try:
            await client.disconnect()
        except:
            pass
        print("\n  BLE disconnected")


# ═══════════════════════════════════════════════════════════════════════════
# STEP 5: Check BlueZ Device Info (all UUIDs)
# ═══════════════════════════════════════════════════════════════════════════

async def step5_bluez_device_info():
    """Get detailed BlueZ device info showing all known UUIDs."""
    print("\n" + "═" * 70)
    print("STEP 5: BLUEZ DEVICE INFO (ALL UUIDs / PROFILES)")
    print("═" * 70)

    from dbus_fast.aio import MessageBus
    from dbus_fast import DBusError, Variant

    bus = await MessageBus().connect()

    try:
        proxy = bus.get_proxy_object(
            "org.bluez", DEVICE_PATH,
            await bus.introspect("org.bluez", DEVICE_PATH),
        )
        dev = proxy.get_interface("org.bluez.Device1")

        uuids = await dev.get_uuids()
        name = await dev.get_name()
        alias = await dev.get_alias()
        connected = await dev.get_connected()
        addr = await dev.get_address()
        addr_type = await dev.get_address_type()
        paired = await dev.get_paired()
        trusted = await dev.get_trusted()
        modalias = await dev.get_modalias()
        rssi = await dev.get_rssi()
        services_resolved = await dev.get_services_resolved()
        device_class = await dev.get_device_class()

        print(f"\n  Address:        {addr} ({addr_type})")
        print(f"  Name:           {name} (alias: {alias})")
        print(f"  Class:          0x{device_class:06X} ({device_class})")
        print(f"  Paired:         {paired}")
        print(f"  Trusted:        {trusted}")
        print(f"  Connected:      {connected}")
        print(f"  ServicesResolved: {services_resolved}")
        print(f"  RSSI:           {rssi}")
        print(f"  Modalias:       {modalias}")

        print(f"\n  Advertised UUIDs ({len(uuids)}):")
        UUIDS_KNOWN = {
            "00001101": "Serial Port (SPP)",
            "00001108": "Headset (HSP)",
            "0000110b": "Audio Sink (A2DP)",
            "0000110c": "AV Remote Control Target (AVRCP)",
            "0000110d": "Advanced Audio Distribution (A2DP)",
            "0000110e": "AV Remote Control (AVRCP)",
            "0000111e": "Handsfree (HFP)",
            "00001200": "PnP Information",
            "00001800": "Generic Access (GATT)",
            "00001801": "Generic Attribute (GATT)",
            "0000180a": "Device Information (GATT)",
            "0000ffff": "Vendor-specific",
        }
        for u in uuids:
            short = u[:8].lower()
            desc = UUIDS_KNOWN.get(short, "")
            tag = "  ← BLE GATT" if short in ("00001800", "00001801", "0000180a", "0000ffff") else ""
            tag += "  ← BR/EDR SPP" if short == "00001101" else ""
            print(f"    {u}  {desc}{tag}")

        # KEY QUESTION: Are the GATT UUIDs really BLE or just BR/EDR?
        print()
        print(f"  KEY ANALYSIS:")
        print(f"  ─────────────")
        print(f"  BLE GATT UUIDs present: {'Yes' if any(u[:8].lower() in ('00001800','00001801','0000180a','0000ffff') for u in uuids) else 'No'}")
        print(f"  BR/EDR SPP UUID present: {'Yes' if '00001101' in str(uuids) else 'No'}")
        print(f"  ServicesResolved={services_resolved}: ", end="")

        # Check if the device D-Bus path has GATT service children
        xml = await bus.introspect("org.bluez", DEVICE_PATH)
        root = ET.fromstring(xml)
        gatt_nodes = [n.attrib.get("name") for n in root.findall("node") if "service" in (n.attrib.get("name", "")).lower()]
        if gatt_nodes:
            print(f"GATT service nodes FOUND on D-Bus: {gatt_nodes}")
        else:
            print(f"No GATT service nodes on D-Bus (device is BR/EDR only for data)")

    except Exception as e:
        print(f"  D-Bus error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        bus.disconnect()


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

async def main():
    print("=" * 70)
    print("  HIWATCH TOOLKIT — TRANSPORT DIAGNOSTIC")
    print(f"  Target: {ADDR}")
    print(f"  Time:   {datetime.now().isoformat()}")
    print("=" * 70)
    print()
    print("  This tool makes NO assumptions about the transport layer.")
    print("  It probes every available channel and reports hard facts.")
    print()

    # Order: BLE first (no permissions needed), RFCOMM second (may need root)
    gatt_services = await step1_ble_gatt_enumeration()
    await step2_dbus_gatt_tree()
    await step5_bluez_device_info()
    await step4_ble_notification_test()
    await step3_rfcomm_probe()

    # Final verdict
    print("\n" + "=" * 70)
    print("  DIAGNOSTIC SUMMARY")
    print("=" * 70)
    print()
    print(f"  BLE GATT services found via Bleak: {len(gatt_services)}")
    print(f"  BLE + BR/EDR UUIDs from BlueZ:     (see STEP 5)")
    print(f"  RFCOMM accessible:                  (see STEP 3)")
    print()
    print("  Based on this evidence, the transport can be determined.")
    print()

    # Disconnect BR/EDR if connected (cleanup)
    print("  Note: Watch may be in BR/EDR mode for audio.")
    print("  Run:  bluetoothctl disconnect " + ADDR)
    print("  Then: python3 diagnose_transport.py")
    print("  to test BLE GATT without BR/EDR interference.")
    print()


if __name__ == "__main__":
    asyncio.run(main())
