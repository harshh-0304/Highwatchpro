#!/bin/bash
# Fast BLE GATT test - connects, sends commands, reads response
# Uses dbus-send which has proven to work

MAC="66:22:AA:00:42:78"
DEV_PATH="/org/bluez/hci0/dev_66_22_AA_00_42_78"
WR_PATH="$DEV_PATH/service0020/char0021"
NT_PATH="$DEV_PATH/service0020/char0023"

echo "============================================================"
echo " Fast BLE GATT Test - Time Sync & Device Info"
echo "============================================================"
echo ""

# Step 1: Reconnect fresh
echo "[1] Connecting..."
bluetoothctl disconnect "$MAC" > /dev/null 2>&1
sleep 1
bluetoothctl connect "$MAC" > /dev/null 2>&1 &
sleep 8
echo "  Done"

# Step 2: Enable notifications
echo ""
echo "[2] Enabling notifications..."
dbus-send --system --dest=org.bluez --print-reply \
  "$NT_PATH" org.bluez.GattCharacteristic1.StartNotify > /dev/null 2>&1
echo "  Notifications enabled"

# Step 3: Read device info (Battery, Firmware, Manufacturer)
echo ""
echo "[3] Reading device info..."
for CHAR_PATH in \
  "$DEV_PATH/service001b/char001c" \
  "$DEV_PATH/service000c/char000f" \
  "$DEV_PATH/service000c/char000d" \
  "$DEV_PATH/service000c/char0015"; do
  result=$(dbus-send --system --dest=org.bluez --print-reply \
    "$CHAR_PATH" org.bluez.GattCharacteristic1.ReadValue \
    dict:string:variant: 2>/dev/null)
  if [ $? -eq 0 ]; then
    hex=$(echo "$result" | grep -o 'byte 0x[0-9A-Fa-f]*' | cut -d'x' -f2 | tr -d '\n' | xxd -r -p 2>/dev/null)
    echo "  $CHAR_PATH: $hex"
  else
    echo "  $CHAR_PATH: FAILED"
  fi
done

# Step 4: Build and send time sync packet
echo ""
echo "[4] Sending Time Sync..."
PKT=$(python3 -c "
import sys
sys.path.insert(0, 'HiWatchToolkit')
from src.hiwatch_toolkit.protocol.commands import build_set_time
pkt = build_set_time()
print(' '.join(f'0x{b:02X}' for b in pkt.data))
")
echo "  Packet: $PKT"

# Convert hex bytes to dbus-send array format
BYTE_ARRAY=$(python3 -c "
import sys
sys.path.insert(0, 'HiWatchToolkit')
from src.hiwatch_toolkit.protocol.commands import build_set_time
pkt = build_set_time()
print(','.join(f'0x{b:02X}' for b in pkt.data))
")

dbus-send --system --dest=org.bluez --print-reply \
  "$WR_PATH" org.bluez.GattCharacteristic1.WriteValue \
  "array:byte:$BYTE_ARRAY" \
  dict:string:variant: 2>&1
echo "  Write done"

# Step 5: Read notification response
echo ""
echo "[5] Reading response..."
sleep 3
result=$(dbus-send --system --dest=org.bluez --print-reply \
  "$NT_PATH" org.bluez.GattCharacteristic1.ReadValue \
  dict:string:variant: 2>&1)
echo "  Raw: $result"
hex=$(echo "$result" | grep -oP 'byte 0x[0-9A-Fa-f]+' | sed 's/byte 0x//' | tr '\n' ' ')
echo "  Hex: $hex"

# Step 6: Send DIAL_READ_STATUS
echo ""
echo "[6] Sending Dial Status..."
DS_PKT="0xCD,0x00,0x05,0x20,0x01,0x01,0x00,0x00"
dbus-send --system --dest=org.bluez --print-reply \
  "$WR_PATH" org.bluez.GattCharacteristic1.WriteValue \
  "array:byte:$DS_PKT" \
  dict:string:variant: 2>&1
echo "  Write done"

# Step 7: Read response
echo ""
echo "[7] Reading response..."
sleep 3
result=$(dbus-send --system --dest=org.bluez --print-reply \
  "$NT_PATH" org.bluez.GattCharacteristic1.ReadValue \
  dict:string:variant: 2>&1)
echo "  Raw: $result"
hex=$(echo "$result" | grep -oP 'byte 0x[0-9A-Fa-f]+' | sed 's/byte 0x//' | tr '\n' ' ')
echo "  Hex: $hex"

# Step 8: Send DIAL_READ_INFO  
echo ""
echo "[8] Sending Dial Info..."
DI_PKT="0xCD,0x00,0x05,0x20,0x01,0x02,0x00,0x00"
dbus-send --system --dest=org.bluez --print-reply \
  "$WR_PATH" org.bluez.GattCharacteristic1.WriteValue \
  "array:byte:$DI_PKT" \
  dict:string:variant: 2>&1
echo "  Write done"

# Step 9: Final read
echo ""
echo "[9] Reading response..."
sleep 3
result=$(dbus-send --system --dest=org.bluez --print-reply \
  "$NT_PATH" org.bluez.GattCharacteristic1.ReadValue \
  dict:string:variant: 2>&1)
echo "  Raw: $result"
hex=$(echo "$result" | grep -oP 'byte 0x[0-9A-Fa-f]+' | sed 's/byte 0x//' | tr '\n' ' ')
echo "  Hex: $hex"

echo ""
echo "============================================================"
echo " Done"
echo "============================================================"
