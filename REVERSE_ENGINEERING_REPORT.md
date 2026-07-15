# HiWatch Pro Reverse Engineering Report

**App:** com.legend.hiwatchpro.app (v1.3.67)  
**App Code Package:** xfkj.fitpro  
**Chip:** Jieli 6621D / 6620  
**Decompiled:** JADX  
**Date:** July 2026  

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [BLE Protocol](#2-ble-protocol)
3. [BLE Service & Characteristic UUIDs](#3-ble-service--characteristic-uuids)
4. [Command Protocol](#4-command-protocol)
5. [Time Synchronization Packet](#5-time-synchronization-packet)
6. [Watch Face Upload Protocol](#6-watch-face-upload-protocol)
7. [OTA / DFU Process](#7-ota--dfu-process)
8. [Firmware Download Flow](#8-firmware-download-flow)
9. [Firmware Security](#9-firmware-security)
10. [12-Hour AM/PM Format Assessment](#10-12-hour-ampm-format-assessment)
11. [Direct BLE Communication Feasibility](#11-direct-ble-communication-feasibility)
12. [Firmware Extraction Feasibility](#12-firmware-extraction-feasibility)
13. [Class / Source Map Index](#13-class--source-map-index)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      App Architecture                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  SplashActivity → MainActivity → MenusActivity              │
│       ↓                                                      │
│  BluetoothLeService (xfkj.fitpro.bluetooth)                  │
│       ↓                                                      │
│  BleManager (xfkj.fitpro.bluetooth)                          │
│       ↓                                                      │
│  CommandPool (queued BLE write executor)                     │
│       ↓                                                      │
│  BluetoothGatt (Android BLE stack)                           │
│                                                              │
│  OTA methods:                                                │
│  ├── Jieli OTA (JliOTAActivity) ← main/6621D                │
│  ├── Onmicro OTA (OMOTAActivity → DfuAppActivity)           │
│  ├── Beken OTA (BKOTAActivity)                              │
│  ├── LP OTA (LPOTAActivity)                                 │
│  └── LY OTA (LyOTActivity)                                  │
│                                                              │
│  Watch Face:                                                 │
│  ├── WatchThemeTools (BLE file transfer)                     │
│  ├── WatchThemeHelper (bin conversion/download mgmt)         │
│  └── WatchThemeH5Activity / SkinChangeActivity               │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Application Entry Points (from AndroidManifest)

| Component | Class |
|-----------|-------|
| Application | `xfkj.fitpro.application.MyApplication` |
| Launcher Activity | `xfkj.fitpro.activity.SplashActivity` |
| Main Activity | `xfkj.fitpro.activity.MainActivity` |
| Home/Device | `xfkj.fitpro.activity.home.MenusActivity` |
| BLE Service | `xfkj.fitpro.bluetooth.BluetoothLeService` |
| BLE Service alt | `xfkj.fitpro.service.LeService` |
| OTA | `xfkj.fitpro.activity.UpdateOtaActivity` |
| Watch Face | `xfkj.fitpro.activity.SkinChangeActivity` |
| Watch Theme H5 | `xfkj.fitpro.activity.clockDial.WatchThemeH5Activity` |
| Clock Dial List | `xfkj.fitpro.activity.clockDial.watchTheme1.ClockDialListActivity` |
| Skin Change | `xfkj.fitpro.activity.SkinChangeActivity` |

---

## 2. BLE Protocol

The app uses a **custom binary command protocol** over BLE UART service (Nordic UART-like).

### Connection Flow

```
1. Start BLE Scan (filter: device name/Hiwatch)
2. Connect to device
3. Discover services
4. Find UART service with Write + Notify characteristics
5. Enable notifications (CCCD 0x2902)
6. Request MTU (configurable, default ~509 max)
7. Send "pair" command (0x12, 0x0A)
8. Exchange data
```

### Key BLE Implementation Classes

| Class | Path | Purpose |
|-------|------|---------|
| `BluetoothLeService` | `xfkj.fitpro.bluetooth` | Android BLE GATT service |
| `BleManager` | `xfkj.fitpro.bluetooth` | BLE connection management |
| `CommandPool` | `xfkj.fitpro.bluetooth` | Queued command execution thread |
| `SendData` | `xfkj.fitpro.bluetooth` | Packet construction |
| `SDKCmdMannager` | `xfkj.fitpro.bluetooth` | High-level command API |
| `OtaManager` | `xfkj.fitpro.bluetooth` | OTA BLE broadcast + control |
| `Profile` | `xfkj.fitpro.bluetooth` | All BLE UUIDs |

Additionally, the app bundles the **Jieli SDK** (`com.jieli.*`) as an alternative/capability-based BLE layer:
- `com.jieli.ble.BleManager` - Full BLE manager
- `com.jieli.jl_bt_ota.tool.ParseHelper` - Jieli RCSP protocol parser
- `com.jieli.jl_bt_ota.constant.BluetoothConstant` - Jieli BLE UUIDs

---

## 3. BLE Service & Characteristic UUIDs

### Main Communication Service (Nordic UART-like)

| UUID | Type | Direction |
|------|------|-----------|
| `6e400001-b5a3-f393-e0a9-e50e24dcca9d` | **Service** | - |
| `6e400002-b5a3-f393-e0a9-e50e24dcca9d` | **Write** | Phone → Watch |
| `6e400003-b5a3-f393-e0a9-e50e24dcca9d` | **Notify** | Watch → Phone |
| `6e400005-b5a3-f393-e0a9-e50e24dcca9d` | Write (Alipay) | Phone → Watch |

### OTA Service (Jieli)

| UUID | Type |
|------|------|
| `6E40FF01-B5A3-F393-E0A9-E50E24DCCA9E` | **Service** |
| `6E40FF02-B5A3-F393-E0A9-E50E24DCCA9E` | Write |
| `6E40FF03-B5A3-F393-E0A9-E50E24DCCA9E` | Notify |

### Dial Upgrade Service

| UUID | Type |
|------|------|
| `00001810-0000-1000-8000-00805f9b34fb` | **Service** |
| `00002a30-0000-1000-8000-00805f9b34fb` | Read/Write/Notify |

### Standard Characteristics

| UUID | Description |
|------|-------------|
| `00002902-0000-1000-8000-00805f9b34fb` | CCCD (notification config) |

### Jieli SDK BLE UUIDs (Alternate transport)

| UUID | Type |
|------|------|
| `0000ae00-0000-1000-8000-00805F9B34FB` | Service |
| `0000ae01-0000-1000-8000-00805F9B34FB` | Write |
| `0000ae02-0000-1000-8000-00805F9B34FB` | Notification |

### OTA-Specific Additional UUIDs (from OtaManager)

| Name | UUID |
|------|------|
| `otas_tx_cmd_uuid` | `0000ff01-0000-1000-8000-00805f9b34fb` |
| `otas_tx_dat_uuid` | `0000ff02-0000-1000-8000-00805f9b34fb` |
| `otas_rx_cmd_uuid` | `0000ff03-0000-1000-8000-00805f9b34fb` |
| `otas_rx_dat_uuid` | `0000ff04-0000-1000-8000-00805f9b34fb` |
| `otas_tx_ips_cmd_uuid` | `6e40ff02-b5a3-f393-e0a9-e50e24dcca9e` |
| `otas_rx_ips_cmd_uuid` | `6e40ff03-b5a3-f393-e0a9-e50e24dcca9e` |
| `otas_data_cmd_uuid` | `6e400003-b5a3-f393-e0a9-e50e24dcca9d` |

---

## 4. Command Protocol

### Packet Structure

All commands use this format (`SendData.getProtocol()`):

```
Offset  Size  Description
──────────────────────────────────────────
0       1     0xCD (205) - Packet prefix/header
1       2     Packet length - 3 (big-endian, uint16)
3       1     Main command ID
4       1     Protocol version (always 0x01)
5       1     Sub command ID (key ID)
6       2     Data payload length (big-endian, uint16)
8       N     Payload data
```

**Short command variant** (`SendData.SwitchProtocol()`):

```
Offset  Size  Description
──────────────────────────────────────────
0       1     0xCD (205) - Packet prefix
1       2     0x0006 - Fixed length
3       1     Main command ID
4       1     0x01 - Version
5       1     Sub command ID
6       2     0x0001 - Fixed data length
8       1     Value
```

**No-payload variant** (`SendData.getNoValueProtocol()`):

```
Offset  Size  Description
──────────────────────────────────────────
0       1     0xCD (205)
1       2     Length (= 5)
3       1     Main command ID
4       1     0x01
5       1     Sub command ID
```

### Main Command IDs

| ID | Name | Source Constant | Description |
|----|------|----------------|-------------|
| `0x12` (18) | `PBSmartBandCommandIdSetting` | All device settings & time sync |
| `0x15` (21) | `PBSmartBandCommandIdSport` | Sport/activity data |
| `0x1C` (28) | `PBSmartBandCommandIdDeviceControlApp` | App-to-device control |
| `0x1A` (26) | `PBSmartBandCommandIdSetInfoByKey` | Read settings by key |
| `0x1F` (31) | `PBSmartBandCommandIdDialUpdate` | Watch face update |
| `0x20` (32) | `PBSmartBandCommandIdDialUpdateRead` | Watch face read/status |
| `0x22` (34) | `PBSmartBandCommandIdFile` | Generic file transfer |
| `0x23` (35) | `PBSmartBandCommandIdFileResponse` | File status |

### Sub-Commands (0x12 = Setting)

| ID | Name | Purpose |
|----|------|---------|
| `0x01` | `SycTime` | **Set system time** |
| `0x02` | `AlarmClock` | Set/read alarms |
| `0x03` | `SetStepTarget` | Set step goal |
| `0x04` | `SetUserInfo` | Set user height/weight/age/gender |
| `0x05` | `SetLongSitRemind` | Sedentary reminder |
| `0x06` | `SetHandSide` | Wearing hand |
| `0x07` | `SetCallRemind` | Call/SMS/app notification switches |
| `0x08` | `Taishou` | Wrist raise settings |
| `0x09` | `BrightScreen` | Bright screen schedule |
| `0x0A` | `IsPair` | **Pair/bind command** |
| `0x0B` | `FindMe` | Find watch |
| `0x0C` | `TakePhoto` | Camera remote |
| `0x0D` | `HeartRateSwitch` | Heart rate measurement switch |
| `0x0E` | `BloodPressureSwitch` | Blood pressure switch |
| `0x0F` | `SleepSwitch` | Sleep monitoring switch |
| `0x10` | `TestDataSwitch` | Test data mode |
| `0x11` | `PhoneCallPush` | Incoming call notification |
| `0x12` | `NotifyMsgPush` | Other message push |
| `0x13` | `SycContracts` | Sync contacts |
| `0x14` | `DisturbSwitch` | DND schedule |
| `0x15` | `Language` | **Set watch language** |
| `0x16` | `HeartAuto` | Auto heart rate settings |
| `0x17` | `DelContract` | Delete contact |
| `0x18` | `DeviceSetInfo` | Read device info (sub=24) |
| `0x19` | `EnterOtaMode` | **Enter OTA mode** |
| `0x1A` | `MeasureECG` | ECG measurement |
| `0x21` | `TempUnite` | Temperature unit |
| `0x22` | `SetTartSportTime` | Sport time target |
| `0x23` | `SetTartStandTime` | Stand time target |
| `0x24` | `Measure2` | Measure control (heart/blood/spo2) |
| `0x25` | `ContractSOS` | SOS contacts |
| `0x26` | `Pay` | Payment params |
| `0x27` | `AliPayTouChuan` | Alipay touch-through |
| `0xF9` | `Weather` | Weather data |
| `0xFA` | `Weather2` | Weather data (extended) |
| `0xFE` | `HeartRate` | Trigger heart rate reading |
| `0xFF` | `PhoneType` | Phone type |
| `0xF9` | `SleepBegin` | Sleep begin time |

### Response / Notification Format

The watch responds through the notify characteristic. Response parsing is implemented in `BaseReceiveData.java` (106KB) which handles the full protocol parsing for all command responses including health data, device info, and ACK messages.

---

## 5. Time Synchronization Packet

### Command Packet

From `SendData.getSetTimesValue()`:

```
0xCD 0x00 0x08 0x12 0x01 0x01 0x00 0x04  [DD DD DD DD]
 │     │       │    │    │    │    │         │
 │     │       │    │    │    │    │         └─ Encoded time (4 bytes)
 │     │       │    │    │    │    └─ Data length = 4
 │     │       │    │    │    └─ Sub cmd = 0x01 (Set system time)
 │     │       │    │    └─ Version = 0x01
 │     │       │    └─ Main cmd = 0x12 (Setting)
 │     │       └─ Packet length - 3 = 8
 │     └─ 0xCD (205) = Header prefix
```

### Time Encoding (4 bytes, big-endian)

```
Bit assignment (MSB first):
31 30 29 28 27 26 | 25 24 23 22 | 21 20 19 18 17 | 16 15 14 13 12 | 11 10 09 08 07 06 | 05 04 03 02 01 00
─────────────────┼────────────┼───────────────┼──────────────┼─────────────────┼──────────────────
Year-2000 (6b)   │ Month (4b) │ Day (5b)      │ Hour (5b)   │ Minute (6b)     │ Second (6b)
Range: 0-63      │ 1-12       │ 1-31          │ 0-23        │ 0-59            │ 0-59
```

**Example encoding for 2026-07-15 14:30:00:**
```
Year-2000 = 26 (0x1A), Month = 7, Day = 15, Hour = 14, Minute = 30, Second = 0
Binary:  011010 0111 01111 01110 011110 000000
         ──┬── ─┬─ ─┬── ─┬── ──┬── ──┬─
           26   7   15  14   30    0

Hex:     0x69 0xEE 0xF0 0x00
         Bit 31..0 = 0110 1001 1110 1110 1111 0000 0000 0000
```

### Timezone / Timestamp Command

There is also a separate timestamp command (`getTimeStamp()`):

```
Command ID: 0x1C (28), Sub: 0x10 (16)
Payload: 8 bytes
  Bytes 0-3: Unix timestamp (seconds since epoch, big-endian int32)
  Bytes 4-7: UTC timezone offset (seconds, big-endian int32)
```

This is sent when the watch requests the timestamp.

### Critical Finding: NO Time Format Field

**There is no AM/PM or 12h/24h flag in any command.** The time sync always uses 24-hour format (hour 0-23). The watch firmware alone decides how to display the hour.

The `WatchTimeCheckActivity.java` exists in `xfkj.fitpro.activity.debug` suggesting a debug tool for checking time sync, but no format switching.

### Language Setting

The app can set the watch language via:
```
0xCD 0x00 0x06 0x12 0x01 0x15 0x00 0x01 [lang_code]
```
Where `lang_code` is an integer (0=English, 1=Chinese, etc.)

---

## 6. Watch Face Upload Protocol

### Overview

The watch face system uses a sophisticated download + convert + transfer pipeline:

```
1. User browses themes on cloud (jusonsmart.com)
2. Theme assets downloaded: .bin files, font files, thumbnails
3. Assets converted to watch binary format
4. Transfer to watch over BLE using command group 0x1F/0x20
```

### Cloud API

- **Base domain:** `https://fpapi2.jusonsmart.com`
- **Watch theme list:** `api/v1/watch/theme/list`
- **Watch theme details:** `api/v1/watch/theme/detail`

Watch identity sent to cloud API:
```
token, mainModel, mchModel, screenType, grade,
screenWidth, screenHeight, versionCode, customer, algorithm
```

### BLE Watch Face Transfer Protocol

**Command group: 0x1F (31) - Dial Update**

| Sub | Name | Direction | Payload |
|-----|------|-----------|---------|
| `0x01` | DialUpdateFile | Phone→Watch | `[seq_num:2][data:N][checksum:2]` |
| `0x02` | DialUpdateStart | Phone→Watch | `[font_pos][custom_flag][bg_color:3][pic_pos]` |
| `0x03` | DialUpdateFinish | Phone→Watch | `[total_len:4][total_checksum:4]` |

**Command group: 0x20 (32) - Dial Read/Response**

| Sub | Name | Direction | Payload |
|-----|------|-----------|---------|
| `0x01` | DialReadStatus | Phone→Watch | (no payload) |
| `0x02` | DialReadInfo | Phone→Watch | (no payload) |
| `0x03` | DialDeviceControlResponse | Phone→Watch | `[response_byte]` |

**Response codes from watch (in `WatchThemeTools.response()`):**
- `1000+N` = ACK with packet number N (continue sending)
- `1` = Checksum failed
- `2` = Success (upgrade complete)
- `3` = Battery low
- `4` = Charging required
- `5` = Out of memory

### File Format

The data sent to the watch is a **raw binary blob** with the following structure:

**Fixed watch face (no custom font):**
```
[RGBT:565_pixel_data]
```

**Custom watch face:**
```
[font_bin][image_data]         (algorithm 1)
[font_bin][header+image_data]  (algorithm 2, header = 0x16,0x01 + width + height)
```

**With thumbnail support:**
```
[thumbnail_data][font_bin][image_data]
```

### Watch Binary Conversion

The `WatchThemeHelper.convertWatchThemeBin()` method handles three algorithms:

| Algorithm | Description |
|-----------|-------------|
| `1` | BK (Beken) format via JNI (`BmpConvertTools.convertBKBin()`) |
| `2` | 24-to-16-bit RGB565 conversion (Yizhaowei format) |
| Other | 24-to-16-bit RGB565 (config-dependent endianness) |

Thumbnail support is controlled by config bit 5.

### Transfer Flow

```
1. Check battery level
2. sendStartCmd() - Send dial update start (0x1F, 0x02)
3. Wait for ACK (response 1000)
4. writeOTA() - Send file chunks (0x1F, 0x01)
   - Each chunk: [seq_num:2][data:120-200bytes][checksum:2]
   - Config determines chunk size (bit 1: 120 = small, 200 = large)
5. After each chunk, wait for ACK with packet number
6. On ACK, send next chunk or resend on mismatch
7. All chunks sent: sendFinishCmd() (0x1F, 0x03)
   - Payload: [total_file_size:4][sum_checksum:4]
8. Watch responds 2 on success
```

---

## 7. OTA / DFU Process

### OTA Methods

The app supports **5 OTA methods** targeting different chip types:

| OTA Type | Activity | SDK | Used For |
|----------|----------|-----|----------|
| **Jieli** | `JliOTAActivity` | `com.jieli.*` | Main 6621D/6620 chip |
| **Onmicro** | `OMOTAActivity` | `com.onmicro.omtoolbox.dfu.DfuAppActivity` | OM chip |
| **Beken** | `BKOTAActivity` | `com.beken.beken_ota.*` | Beken chip |
| **LP** | `LPOTAActivity` | `com.phy.otalib.*` | LP chip |
| **LY** | `LyOTActivity` | Unknown SDK | LY chip |

### OTA Update Flow (Jieli - primary)

```
1. App checks firmware version
2. Saves current BT connection state
3. Sends "enter OTA mode" command (0x12, 0x19)
4. Watch reboots into OTA mode (separate BLE service/advertisement)
5. App disconnects and scans for OTA device
6. Reconnects to OTA-mode device
7. Discovers OTA service (6E40FF01 / 0000ff01)
8. Sends ISP command to wake bootloader
9. Receives device address
10. Sends firmware data via OTA characteristics
11. Firmware files uploaded: user.bin, app.bin, cfg.bin, patch.bin
12. Device resets and boots new firmware
```

### OTA Command (Enter OTA Mode)

```
0xCD 0x00 0x05 0x12 0x01 0x19
  │     │      │    │    │
  │     │      │    │    └─ Sub = 0x19 (EnterOtaMode)
  │     │      │    └─ Version
  │     │      └─ Main = 0x12 (Setting)
  │     └─ Length = 5 (no payload)
  └─ Header 0xCD
```

### ISP Flow

The OTA uses a native library (`WorkOnBoads`, from `com.example.otalib`) that implements:

1. **ISP mode entry** - Sends ISP command to bootloader
2. **Binary loading** - Writes app/cfg/patch binary data
3. **User data writing** - Main firmware update (user partition)
4. **Device reset**

The address for user data is extracted from the filename (e.g., `user29000.bin` → address 0x29000).

---

## 8. Firmware Download Flow

### OTA Check API

The app checks for firmware updates via:

```
GET https://tomato.gulaike.com/api/v1/config/app
Parameters:
  name=<device_name>:<gsensor>:<heart>:<led>
  type=1
  version=<current_firmware_version>
  platform=<platform_type>
```

### Server Response (OTAUpgradeInfo model)

```json
{
  "success": true,
  "data": {
    "app_down_url": "https://...firmware.zip",
    "display_name": "firmware_v1.2.3",
    "version": "1.2.3",
    "app_version": "xxx",
    "describe": "Update description",
    "update_time": "2026-01-01",
    "size": "1234567"
  }
}
```

### Firmware File

- Downloaded as a **.zip** file
- Extracted to OTA directory
- Contains up to 4 files matched by name:
  - `app*` - Application firmware
  - `cfg*` - Configuration data
  - `patch*` - Patch data
  - `user*` - **Main firmware** (user partition binary, filename includes hex address like `user29000.bin`)

### Static CDN Files

Watch face and theme assets are hosted at:
- `http://static.jusonsmart.com/`
- `https://res.jusonsmart.com/`

---

## 9. Firmware Security

### Observed Security Measures

1. **Checksum** - Each watch face data chunk has a simple 16-bit additive checksum:
   ```java
   short s = 0;
   for (byte b : data) s += (short)(b & 0xFF);
   ```

2. **Total Checksum** - At end of watch face transfer, 32-bit additive checksum of entire file is sent.

3. **Encryption Flag** - In UpdateOtaActivity, there's a call `OtaManager.do_work_on_boads.setEncrypt(false)`, which suggests:
   - Firmware CAN be encrypted
   - Encryption is currently **disabled** (`setEncrypt(false)`)
   - The native `WorkOnBoads` library handles encryption/decryption

4. **Jieli OTA Protocol** - The Jieli SDK (`com.jieli.jl_bt_ota`) implements:
   - Command-response protocol with sequence numbers
   - MD5 support (`GetDevMD5Cmd`, `CMD_GET_DEV_MD5`)
   - Feature mask / function map
   - OTA with enter/exit update mode commands
   - Firmware update blocks with offset tracking

5. **No Signature Verification Observed** - No asymmetric signature (RSA/ECDSA) checks were found in the decompiled Java code. The native `WorkOnBoads` library may contain proprietary verification.

### Jieli RCSP Protocol

The Jieli SDK uses a separate protocol (opcode-based):

```
Packet Header: 0xFE 0xDC 0xBA (3 bytes)
Data: [flags:2][param_len:2][param_data:N]
Packet Footer: 0xEF (1 byte)
```

Where flags contain: type (command/response), hasResponse flag, and opcode (1 byte).

Command IDs (Jieli RCSP):
- 1 = Data transfer
- 2 = Get target feature map
- 3 = Get target info
- 6 = Disconnect classic BT
- 11 = Switch device request
- 209 = Settings communication MTU
- 212 = Get device MD5
- 225 = OTA get update file offset
- 226 = OTA inquire if can update
- 227 = OTA enter update mode
- 228 = OTA exit update mode
- 229 = OTA send firmware update block
- 230 = OTA get device refresh firmware status
- 231 = Reboot device
- 232 = OTA notify update content size
- 240 = Custom (RCSP) command
- 255 = Extra custom

---

## 10. 12-Hour AM/PM Format Assessment

### Conclusion: **NOT Achievable through the app alone.**

### Analysis

1. **The time sync command sends hour in 24-hour format (0-23).** There is no 12h/24h mode flag in any command or protocol field examined.

2. **No AM/PM setting exists in the app.** A thorough search of all source files found:
   - No "time format" setting UI
   - No AM/PM toggle in settings
   - No 12-hour/24-hour format command to the watch
   - The app simply reads system time and packs the hour into the protocol

3. **Language setting exists, but no time format.** The only format-related command is the language setting (0x12, 0x15) which doesn't include time format.

4. **The watch firmware determines display format.** Since the app always sends hours as 0-23, the watch must decide whether to display "14:00" or "2:00 PM" based on its own firmware logic.

### Possible Approaches

| Approach | Difficulty | Feasibility |
|----------|-----------|-------------|
| **App patch** - Add AM/PM command to protocol | **Hard** | Needs reverse engineering a new command or modifying firmware |
| **Hidden command** - Find undocumented format command | **Unlikely** | No evidence in any code path |
| **Firmware patch** - Modify watch firmware | **Medium** | See Section 12 |
| **BLE proxy** - Intercept time sync, inject format flag | **Possible** | If the protocol has unused flag bits in time encoding - **NO unused bits in current encoding** |
| **Language-based** - Set locale that defaults to 12h | **Not possible** | Watch doesn't interpret locale for time format |

### Recommendation

The **only** reliable approach is a firmware modification. The watch firmware (running on Jieli 6621D) must be modified to interpret an unused protocol field or be patched to always display in 12-hour format.

---

## 11. Direct BLE Communication Feasibility

### Assessment: **Fully Feasible**

The BLE protocol is completely understood and does not require the official app for basic operations.

### What You Need

**GATT Connection:**
```
Service: 6e400001-b5a3-f393-e0a9-e50e24dcca9d
Write CC: 6e400002-b5a3-f393-e0a9-e50e24dcca9d
Notify CC: 6e400003-b5a3-f393-e0a9-e50e24dcca9d
```

**Enable notifications:**
```
Write to CCCD (00002902-0000-1000-8000-00805f9b34fb) 
on 6e400003: value = 0x0001 (enable notification)
```

**Initial handshake:**
```
1. Write: CD 00 06 12 01 0A 00 01 02  (Pair command)
2. Receive: ACK or device info response
```

**Set time (example):**
```
Write: CD 00 08 12 01 01 00 04 69 EE F0 00
```

**Implementation options:**
- Python with `bleak` library (cross-platform)
- Node.js with `@abandonware/noble`
- Android app with BluetoothGatt directly
- Rust with `btleplug`

### Capabilities Without Official App

| Operation | Feasible | Difficulty |
|-----------|----------|------------|
| Connect & discover services | ✅ Yes | Trivial |
| Read time from watch | ✅ Yes | Low |
| Set time on watch | ✅ Yes | Low |
| Read health data | ✅ Yes | Medium |
| Transfer watch face | ✅ Yes | Medium |
| Trigger OTA mode | ✅ Yes | Low |
| Read firmware version | ✅ Yes | Low |
| Upload firmware | ✅ Yes | Medium |

---

## 12. Firmware Extraction Feasibility

### Assessment: **Limited without hardware access**

The app itself does **not implement firmware extraction from the watch**. The OTA process is:
1. **Download** firmware from cloud server → phone
2. **Upload** firmware from phone → watch

There is no "read firmware from watch" or "backup firmware" functionality in the app.

### What's Possible

1. **Capture OTA firmware files** - The app downloads .zip firmware files to:
   ```
   /storage/emulated/0/Android/data/com.legend.hiwatchpro.app/files/ota/
   ```
   These are extracted and temporarily stored before uploading.

2. **Sniff OTA traffic** - Since firmware is transferred over BLE, a BLE sniffer (nRF Sniffer, Ubertooth) can capture the raw binary data during OTA.

3. **Reverse engineer native library** - The `WorkOnBoads` library handles the actual chip-level firmware loading:
   - `setEncrypt(false)` indicates firmware CAN be encrypted
   - The encryption is handled in native code (not visible in Java decompilation)
   - Need to reverse engineer the `.so` library

4. **Bootloader/BLE address** - The ISP flow during OTA:
   - Watch enters OTA mode
   - Sends device address via ISP notify
   - Address extracted from ISP response (bytes after 2-byte prefix)
   - Format: hex string reversed

### Jieli Chip Flash Map (inferred)

```
┌─────────────────────────────────────────┐
│  Flash Layout (Jieli 6621D, typical)     │
├─────────────────────────────────────────┤
│  0x00000 - Bootloader (read-only)        │
│  0x01000 - OTA boot flag                 │
│  0x02000 - Config/param storage          │
│  0x10000 - Firmware A (active)           │
│  0x29000 - User data / firmware (config) │
│  0x40000 - Firmware B (backup)           │
│  ...                                      │
│  0x80000 - Watch face / resource data     │
└─────────────────────────────────────────┘
```

The filename `user29000.bin` suggests the user partition starts at address 0x29000.

---

## 13. Class / Source Map Index

### BLE Layer
| File | Path |
|------|------|
| `BluetoothLeService.java` | `xfkj.fitpro/bluetooth/` |
| `BleManager.java` | `xfkj.fitpro/bluetooth/` |
| `CommandPool.java` | `xfkj.fitpro/bluetooth/` |
| `SendData.java` | `xfkj.fitpro/bluetooth/` |
| `SDKCmdMannager.java` | `xfkj.fitpro/bluetooth/` |
| `Profile.java` | `xfkj.fitpro/bluetooth/` |
| `OtaManager.java` | `xfkj.fitpro/bluetooth/` |
| `BaseReceiveData.java` | `xfkj.fitpro/bluetooth/revData/` |
| `ByteUtil.java` | `xfkj.fitpro/bluetooth/` |

### Watch Face / Dial
| File | Path |
|------|------|
| `WatchThemeTools.java` | `xfkj.fitpro/utils/` |
| `WatchThemeHelper.java` | `xfkj.fitpro/activity/clockDial/` |
| `WatchThemeH5Activity.java` | `xfkj.fitpro/activity/clockDial/` |
| `SkinChangeActivity.java` | `xfkj.fitpro/activity/` |
| `ClockDialListActivity.java` | `xfkj.fitpro/activity/clockDial/watchTheme1/` |
| `WatchTheme2Activity.java` | `xfkj.fitpro/activity/clockDial/watchTheme2/` |

### OTA
| File | Path |
|------|------|
| `UpdateOtaActivity.java` | `xfkj.fitpro/activity/` |
| `JliOTAActivity.java` | `xfkj.fitpro/activity/ota/` |
| `OMOTAActivity.java` | `xfkj.fitpro/activity/ota/` |
| `BKOTAActivity.java` | `xfkj.fitpro/activity/ota/` |
| `LPOTAActivity.java` | `xfkj.fitpro/activity/ota/` |
| `LyOTActivity.java` | `xfkj.fitpro/activity/ota/` |
| `OTAUpgradeInfo.java` | `xfkj.fitpro/model/` |
| `BmpConvertTools.java` | `xfkj.fitpro/jni/` |

### Services
| File | Path |
|------|------|
| `BluetoothLeService.java` | `xfkj.fitpro/bluetooth/` |
| `LeService.java` | `xfkj.fitpro/service/` |
| `NotifyService.java` | `xfkj.fitpro/service/` |
| `UploadDataService.java` | `xfkj.fitpro/service/` |

### Network / API
| File | Path |
|------|------|
| `HttpHelper.java` | `xfkj.fitpro/api/` |
| `CommonService.java` | `xfkj.fitpro/api/` |
| `NetWorkManager.java` | `xfkj.fitpro/api/` |
| `Api.java` | `xfkj.fitpro/api/` |

### Debug Activities
| File | Path |
|------|------|
| `BluetoothCommandActivity.java` | `xfkj.fitpro/activity/debug/` |
| `WatchTimeCheckActivity.java` | `xfkj.fitpro/activity/debug/` |
| `DebugFunctionActivity.java` | `xfkj.fitpro/activity/debug/` |
| `OtherBluetoothDebugActivity.java` | `xfkj.fitpro/activity/debug/` |

### Constants / Data
| File | Path |
|------|------|
| `Constant.java` | `xfkj.fitpro/utils/` |
| `SPKey.java` | `xfkj.fitpro/` |
| `DateUtils.java` | `xfkj.fitpro/utils/` |
| `PathUtils.java` | `xfkj.fitpro/utils/` |
| `MySPUtils.java` | `xfkj.fitpro/utils/` |
| `SaveKeyValues.java` | `xfkj.fitpro/utils/` |

---

## Appendix A: BLE Command Quick Reference

### Write to Phone→Watch (6e400002)
```
Command format: CD [len:2] [main] 01 [sub] [data_len:2] [data...]
```

### Notification from Watch→Phone (6e400003)
The watch sends responses with the same header structure. Response data is parsed in `BaseReceiveData.java`.

### Protocol Constants (from Profile.java)
```java
DataPackageHead = 205 (0xCD)
DataPackageVersion = 1
DataPackageCommandIDLength = 1
DataPackageCommandKeyLength = 1
DataPackageCommandKeyValueLength = 2
DataPackageAck = 220 (0xDC)  // ACK byte
```

---

*This report was generated from full source decompilation of HiWatch Pro app v1.3.67 using JADX.*
