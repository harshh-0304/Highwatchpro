# HiWatch Pro Watch Face Binary Format Specification

**Derived from:** `xfkj.fitpro` app source code (v1.3.67)  
**Source files analyzed:** WatchThemeHelper.java, WatchThemeTools.java, BmpConvertTools.java, SendData.java, NumberUtils.java, BitmapConverter.java, Profile.java, ClockDialInfoBody.java  
**Native library:** `libbmp-lib.so` (24-bit BMP → 16-bit RGB565 conversion, Beken format conversion)  
**Chip targets:** Jieli 6621D/6620 (primary), Beken (secondary)

---

## Table of Contents

1. [Overview of Format Selection](#1-overview-of-format-selection)
2. [Pipeline: 24-bit Bitmap to Watch Format](#2-pipeline-24-bit-bitmap-to-watch-format)
3. [Format A: Standard RGB565 (Algorithm 0 / default)](#3-format-a-standard-rgb565-algorithm-0--default)
4. [Format B: Yizhaowei with Header (Algorithm 2)](#4-format-b-yizhaowei-with-header-algorithm-2)
5. [Format C: Beken (Algorithm 1)](#5-format-c-beken-algorithm-1)
6. [Format D: 8-bit Dial (Algorithm 3/4)](#6-format-d-8-bit-dial-algorithm-34)
7. [Thumbnail Format](#7-thumbnail-format)
8. [Font Format](#8-font-format)
9. [Complete File Assembly (BLE Transfer)](#9-complete-file-assembly-ble-transfer)
10. [Endianness Reference](#10-endianness-reference)
11. [RGB565 Color Encoding](#11-rgb565-color-encoding)
12. [rotatDerection: BMP to Watch Byte Order](#12-rotatderection-bmp-to-watch-byte-order)
13. [Specification for Generating a Watch Face from Scratch](#13-specification-for-generating-a-watch-face-from-scratch)

---

## 1. Overview of Format Selection

The watch face format is selected at runtime based on the `ClockDialInfoBody` fields retrieved from the watch via BLE command `0x20, 0x02` (DialReadInfo). The critical fields are:

| Field | Type | Purpose |
|-------|------|---------|
| `algorithm` | byte | Selects conversion algorithm (0, 1, 2, 3, 4) |
| `config` | int | Bitfield of feature flags (see below) |
| `width` | short | Display width in pixels |
| `height` | short | Display height in pixels |
| `pictureNums` | int | Number of picture slots |
| `thumbPercent` | int | Thumbnail scale percentage (10-100) |

### Config Bitfield (`config` field)

Parsed into bits 0-7 via `NumberUtils.intToBinary(config)`:

| Bit | Meaning |
|-----|---------|
| `[0]` | Remove BMP header flag (1 = strip header, 0 = keep) |
| `[1]` | BLE chunk size (1 = 120 bytes, 0 = 200 bytes) |
| `[5]` | Thumbnail supported (1 = prepend thumbnail) |

### Algorithm Selection

```java
// WatchThemeHelper.convertWatchThemeBin(Bitmap)
algorithm == 1 → BmpConvertTools.convertBKBin(bitmap)        // Beken format
algorithm == 2 → BmpConvertTools.convert24To16Bin(bitmap, false) // Yizhaowei with header
algorithm == 3 || 4 → // 8-bit dial (server-side conversion)
default → BmpConvertTools.convert24To16Bin(bitmap, config[0]==0) // Standard RGB565
```

---

## 2. Pipeline: 24-bit Bitmap to Watch Format

All formats start with the same initial steps:

### Step 1: Bitmap → 24-bit BMP File

The `BitmapConverter` class creates a **24-bit Windows BMP file** (BGR byte order, bottom-up rows, row padding to 4-byte boundary).

**BMP File Structure (created by BitmapConverter):**

```
Offset  Size  Field
------  ----  -----
0       2     Signature: "BM" (0x42, 0x4D)
2       4     File size (little-endian)
6       4     Reserved (zeros)
10      4     Pixel data offset = 54 (always, since 24-bit has no color table)
14      4     Info header size = 40
18      4     Width (pixels, little-endian)  ← NOTE: has off-by-one padding adjustment
22      4     Height (pixels, little-endian)
26      2     Planes = 1
28      2     Bits per pixel = 24
30      4     Compression = 0 (BI_RGB)
34      4     Image data size
38      4     H-resolution (0)
42      4     V-resolution (0)
46      4     Colors used = 0
50      4     Important colors = 0
54      N     Pixel data (BGR, bottom-up, padded to 4-byte rows)
```

**Pixel byte order in 24-bit BMP:**
- Each pixel = 3 bytes: Blue, Green, Red (BGR order)
- Rows stored bottom-up (last row of image is first in file)
- Each row padded to 4-byte boundary with 0x00 bytes (the BitmapConverter pads with 0xFF = -1)

**Row padding formula:** `padded_row_size = ((width * 3 + 3) / 4) * 4`

### Step 2: 24-bit BMP → 16-bit RGB565 Binary

Native JNI function `Bmp24ConvertBmp16(String inputBmpPath, String outputBinPath, int removeHeader)`:

- **Input:** 24-bit BMP file path
- **Output:** 16-bit RGB565 binary file
- **Parameter `removeHeader`:** 
  - `0` = output includes BMP header (54 bytes + optional color table)
  - `1` = output is raw pixel data only (no header)

The native library performs RGB565 conversion:
```
R5 = (red_8bit   * 249 + 1014) >> 11  (or equivalently red_8bit   >> 3)
G6 = (green_8bit * 253 + 505)  >> 10  (or equivalently green_8bit >> 2)
B5 = (blue_8bit  * 249 + 1014) >> 11  (or equivalently blue_8bit  >> 3)

RGB565 = (R5 << 11) | (G6 << 5) | B5
```

**BMP-endian RGB565 storage (little-endian):**
```
Byte 0 (low):  [G2 G1 G0 B4 B3 B2 B1 B0]  = ((G & 0x07) << 5) | B
Byte 1 (high): [R4 R3 R2 R1 R0 G5 G4 G3]   = (R << 3) | (G >> 3)
```

The output 16-bit BMP (when `removeHeader=0`):
- Standard 54-byte BMP header
- 16-bit pixel data in BMP format: little-endian RGB565, bottom-up rows
- Row padding to 4-byte boundary (since width×2 may not be multiple of 4)

When `removeHeader=1`: only raw pixel data, tightly packed (no row padding).

### Step 3: Post-processing (Per-Format)

Depends on the algorithm. Details in each section below.

---

## 3. Format A: Standard RGB565 (Algorithm 0 / default)

**Used when:** `algorithm != 1 && algorithm != 2 && !isSupport8BitDial()`

### Pipeline

```
Bitmap → 24-bit BMP → native 16-bit BMP (removeHeader = config[0]==0)
  → if config[0]==1:
       strip BMP header (getNotHeaderBmp)
       → byte-swap (rotatDerection) → big-endian RGB565
  → if config[0]==0:
       keep BMP file as-is (16-bit BMP with header)
```

### Case A1: `config[0] == 1` (strip header, big-endian output)

**`getNotHeaderBmp(width, height, fileBytes)`:**
1. Calculates: `headerSize = fileBytes.length - (width * height * 2)`
2. Returns: `fileBytes[headerSize .. end]` = raw pixel data
3. Assumes tightly-packed 16-bit pixels (no row padding). **Width must be even** for correct operation.

**`rotatDerection(width, height, pixelBytes)`:**
1. Reverses all bytes (end-to-end byte reversal of entire pixel array)
2. Within each row, swaps byte pairs of each 16-bit pixel
3. **Net effect:** Converts from BMP format (little-endian, bottom-up) to watch-native format (big-endian, top-down)

**Watch-native RGB565 byte order (after rotatDerection):**
```
Pixel bytes (top-left first, left-to-right, top-to-bottom):
  Byte 0: [R4 R3 R2 R1 R0 G5 G4 G3]   ← high byte of RGB565
  Byte 1: [G2 G1 G0 B4 B3 B2 B1 B0]   ← low byte of RGB565
```

This is **big-endian RGB565**: each pixel stored as high-byte then low-byte.

**Row order:** Top-down (first pixel in file = top-left of image)

### Case A2: `config[0] == 0` (keep BMP header)

The image data is a **complete 16-bit BMP file** with:
- 54-byte BMP header (magic "BM", size fields, etc.)
- Standard BMP pixel data: bottom-up rows, little-endian RGB565

The watch must parse the BMP header to extract dimensions and pixel data.

### Custom Theme Assembly (with font)

```
Final binary = [font_bin] + [image_data]
```
No additional headers, no separators. The watch knows where font ends and image begins from the expected sizes.

---

## 4. Format B: Yizhaowei with Header (Algorithm 2)

**Used when:** `algorithm == 2`

This format wraps the image data in a custom 10-byte header. It is used for Yizhaowei (Y zw)-branded devices.

### Pipeline

```
Bitmap → 24-bit BMP → native 16-bit BMP (removeHeader = 0)
  → strip BMP header (getNotHeaderBmp)       // width, height from ClockDialInfoBody
  → byte-swap (rotatDerection)                // → big-endian RGB565
  → wrap with convertYiZhaoWeiBin header      // 10-byte prefix
  → final = font_bin + header + image_data
```

### Yizhaowei 10-byte Header

```
Offset  Size  Field           Value/Encoding
------  ----  -----           -------------
0       2     Magic marker    0x16 0x01
2       2     Width           Little-endian uint16 (e.g., 0xF0 0x01 for 496)
4       2     Height          Little-endian uint16 (e.g., 0x20 0x01 for 288)
6       4     Unknown flags   0x00 0x00 0x0A 0x00
```

**Construction code:**
```java
byte[] header = combineBytes(
    hexString2Bytes("1601"),           // magic
    shortToBytesLittle(width),          // width LE
    shortToBytesLittle(height),         // height LE
    hexString2Bytes("00000a00")         // flags
);
```

Total header size: **10 bytes exactly**

### Custom Theme Assembly (with font)

```
Final binary = [font_bin] + [10-byte Yizhaowei header] + [big-endian RGB565 pixel data]
```

Note: The Yizhaowei header contains width/height in **little-endian**, while the pixel data following it is **big-endian** RGB565.

---

## 5. Format C: Beken (Algorithm 1)

**Used when:** `algorithm == 1`

This format uses the Beken chip-specific encoding via a second native conversion step.

### Pipeline

```
Bitmap → (same as Format A) → 16-bit BMP (removeHeader = 0)
  → native convertBKBin(input_16bit_bin, output_bk_bin)
  → final = font_bin + bk_image_data
```

### Native `convertBKBin()`

```java
public static native int convertBKBin(String str, String str2);
// str = path to 16-bit RGB565 binary (with BMP header)
// str2 = output path for Beken-format binary
// Returns: 1 on success
```

The Beken format is a proprietary encoding used by Beken Corporation (BK7231/BK7251 series chips). The exact encoding is inside `libbmp-lib.so` and cannot be determined from Java sources alone.

**Known properties inferred from code:**
- Input is a standard 16-bit BMP file (header + pixel data)
- Output is a Beken-specific `.bin` format
- No additional preprocessing (no header stripping, no byte swapping)
- The output is later combined with font data

**Assembly:** `final = font_bin + bk_image_data` (algorithm 1 path in `startFile()`)

```java
if (clockDialInfo.getAlgorithm() == 1) {
    this.mFileData = NumberUtils.combineBytes(file2BytesByStream2, file2BytesByStream);
    // file2BytesByStream2 = image data (Beken format)
    // file2BytesByStream = font data
}
```

**Note:** In algorithm 1, the config[0] BMP header removal is NOT applied (the `if (bArrIntToBinary[0] == 1)` block only runs for non-algorithm-1, non-algorithm-2 paths). The Beken library handles the 16-bit BMP internally.

---

## 6. Format D: 8-bit Dial (Algorithm 3/4)

**Used when:** `algorithm == 3 || algorithm == 4` (checked via `isSupport8BitDial()`)

### Characteristics

- **No font data** is combined: `mFileData = file2BytesByStream2` (image data only)
- **No pixel processing**: no `getNotHeaderBmp`, no `rotatDerection`, no Yizhaowei header
- Image is converted via `convert24To16Bin(bitmap, config[0]==0)` → 16-bit BMP
- The full 16-bit BMP is sent as-is (header + pixels)
- Thumbnails use 8-bit format and are server-converted

### 8-bit Thumbnail Conversion

For 8-bit dials, thumbnails go through a **network-based conversion**:

```java
// WatchThemeHelper.handleNetThumBin()
1. Bitmap → 24-bit BMP file (BitmapConverter)
2. Upload BMP to server: HttpHelper.bmp16Convert8BitByNetwork(file, ...)
3. Server converts to 8-bit (256-color) format
4. Result is "THU8.bin" downloaded back
```

The server-side 8-bit format is unknown from the client code.

---

## 7. Thumbnail Format

Thumbnails are **optionally prepended** to the main binary when `config[5] == 1` (thumbnail supported).

### Thumbnail Dimensions

```java
thumbWidth  = (int)(width * (thumbPercent / 100.0f)) + 1
thumbHeight = (int)(height * (thumbPercent / 100.0f))
```

- `thumbPercent` is typically 20-30 (meaning ~20-30% of main display size)
- `thumbRoundAngle` can apply rounded corners (via `ImageUtils.toRoundCorner`)

### Thumbnail Pipeline

**For algorithm 2 (Yizhaowei):**
```
1. Bitmap → 24-bit BMP → native 16-bit BMP
2. getNotHeaderBmp(thumbWidth, thumbHeight, ...)
3. rotatDerection(thumbWidth, thumbHeight, ...)  → big-endian RGB565
4. convertYiZhaoWeiBin(thumbWidth, thumbHeight, ...) → 10-byte header prepended
```

**For other algorithms:**
```
1. Bitmap → convertWatchThemeBin(bitmap) → 16-bit bin path
2. Contents used as-is
```

**For 8-bit dial (algorithm 3/4):**
Server-side conversion, result is "THU8.bin" format (unknown)

### Position in Final Binary

```
Final binary = [thumbnail_data] + [font_bin] + [image_data]
```

The thumbnail is **prepended** (concatenated before the main data).

---

## 8. Font Format

Fonts are downloaded from the server as `.bin` files. The app does not process or transform them — they are sent to the watch as-is.

```java
byte[] fontBytes = FileIOUtils.readFile2BytesByStream(watchThemeDetailsResponse.getFonBinPath());
// fontBytes are used raw
```

**Properties:**
- Font is a **proprietary binary format** for the watch's display controller
- The watch knows how to parse it based on font position and theme type
- Font position (`fontPosition` byte) is sent in the start command, indicating where/how the font data is used
- Font size varies by theme; the server provides a `size` field

The font binary structure could not be determined from the Java code alone — it is rendered entirely on the watch's MCU.

---

## 9. Complete File Assembly (BLE Transfer)

### File Assembly Logic (`WatchThemeTools.startFile()`)

```
Algorithm 1 (Beken):
  mFileData = [thumbnail?] + [beken_image_data] + [font_data]

Algorithm 2 (Yizhaowei):
  mFileData = [thumbnail?] + [font_data] + [yizhaowei_header(10)] + [big-endian_rgb565_pixels]

Algorithm 3/4 (8-bit):
  mFileData = [thumbnail?] + [16-bit_bmp_bytes]   // no font

Default:
  mFileData = [thumbnail?] + [font_data] + [image_data]
    (image_data: 16-bit BMP if config[0]==0, or big-endian RGB565 if config[0]==1)
```

### BLE Transfer Protocol

**BLE Service:** `00001810-0000-1000-8000-00805f9b34fb`  
**Characteristic:** `00002a30-0000-1000-8000-00805f9b34fb` (read/write/notify)

**Protocol envelope (all commands):**
```
0xCD  [len-3:2 big-endian]  [main_cmd]  0x01  [sub_cmd]  [data_len:2 big-endian]  [data...]
```

**Main command: 0x1F (31) = Dial Update**

#### Command 1: Start (0x1F, 0x02)

```
Payload: [font_position:1] [is_custom:1] [bg_R:1] [bg_G:1] [bg_B:1] [pic_pos:1]?
```

| Field | Size | Description |
|-------|------|-------------|
| `font_position` | 1 byte | Font index/position on watch |
| `is_custom` | 1 byte | 1 = custom theme, 0 = fixed theme |
| `bg_R`, `bg_G`, `bg_B` | 3 bytes | Background color (RGB from `Color.red(-1)` = 0xFF for white default) |
| `pic_pos` | 1 byte | Replace picture position (only if `pictureNums > 0`) |

#### Command 2: File Data (0x1F, 0x01) — Sent in chunks

```
Payload: [seq_num:2 big-endian] [chunk_data:N] [checksum:2 big-endian]
```

| Field | Size | Description |
|-------|------|-------------|
| `seq_num` | 2 bytes | Sequence number (starting from 1), big-endian |
| `chunk_data` | 120 or 200 bytes | (last chunk may be smaller) |
| `checksum` | 2 bytes | Sum of all bytes in seq_num + chunk_data, big-endian |

**Chunk size:** 120 bytes if config[1]==1, otherwise 200 bytes.

**Checksum calculation:**
```java
short calculateCheckcode(byte[] data) {
    short sum = 0;
    for (byte b : data) sum += (b & 0xFF);
    return sum;  // stored big-endian (NumberUtils.shortToBytes)
}
```

#### Command 3: Finish (0x1F, 0x03) — Sent after all chunks

```
Payload: [total_file_size:4 big-endian] [total_checksum:4 big-endian]
```

| Field | Size | Description |
|-------|------|-------------|
| `total_file_size` | 4 bytes | Total bytes of `mFileData` (big-endian) |
| `total_checksum` | 4 bytes | Sum of all bytes in `mFileData` (big-endian) |

**Total checksum calculation:**
```java
byte[] calculateFinishCheckcode() {
    int sum = 0;
    for (byte b : mFileData) sum += (b & 0xFF);
    return combineBytes(intToBytes(mFileData.length), intToBytes(sum));
}
```

#### Command 4: Read Status (0x20, 0x01)

```
Payload: empty (just protocol header)
```

Used to poll the watch for transfer status. The watch responds with:
- `1000 + packet_number` = ACK (continue with next or resend)
- `1` = Checksum error (resend chunk)
- `2` = SUCCESS (transfer complete)
- `3` = Battery low
- `4` = Charging required
- `5` = Out of memory

### Full Transfer Sequence

```
Phone                                      Watch
  │                                          │
  ├── 0x1F 0x02 (Start, metadata) ─────────►│
  │                                          │
  │◄── 0x20 0x01 (ACK = 1000) ──────────────┤
  │                                          │
  ├── 0x1F 0x01 (Chunk 1, seq=1) ──────────►│
  │◄── 0x20 0x01 (ACK = 1001) ──────────────┤
  │                                          │
  ├── 0x1F 0x01 (Chunk 2, seq=2) ──────────►│
  │◄── 0x20 0x01 (ACK = 1002) ──────────────┤
  │         ...                               │
  │                                          │
  ├── 0x1F 0x03 (Finish, total size+sum) ──►│
  │◄── 0x20 0x01 (ACK = 2, success) ────────┤
```

Error recovery: On checksum mismatch (response `1`) or sequence mismatch, the phone resends the last chunk.

---

## 10. Endianness Reference

| Data | Endianness | Function |
|------|-----------|----------|
| BLE protocol length field | Big-endian | `intToBytes` (big-endian, 4 bytes, bytes [2..3] used for 2-byte length) |
| BLE protocol data length | Big-endian | `intToBytes`, bytes [2..3] used |
| Sequence number in chunk | Big-endian | `shortToBytes` |
| Chunk checksum | Big-endian | `shortToBytes` |
| Total file size in finish | Big-endian | `intToBytes` |
| Total checksum in finish | Big-endian | `intToBytes` |
| BMP file header fields | Little-endian | `BitmapConverter.writeInt/writeShort` |
| RGB565 pixel in BMP | Little-endian | (BMP standard) |
| Watch-native RGB565 pixel | **Big-endian** | After `rotatDerection` |
| Yizhaowei header width/height | **Little-endian** | `shortToBytesLittle` |
| Yizhaowei header magic/flags | As-is | Fixed bytes |

### Key Conversion Functions

```java
// Big-endian short (used for BLE protocol)
shortToBytes(short s)         → {(byte)(s >> 8), (byte)(s & 0xFF)}

// Little-endian short (used for Yizhaowei header)
shortToBytesLittle(short s)   → {(byte)(s & 0xFF), (byte)(s >> 8)}

// Big-endian int (used for BLE protocol)
intToBytes(int i)             → {(byte)(i>>24), (byte)(i>>16), (byte)(i>>8), (byte)i}

// Little-endian int (used for BMP writing)
intToBytes_Little(int i)      → {(byte)i, (byte)(i>>8), (byte)(i>>16), (byte)(i>>24)}
```

---

## 11. RGB565 Color Encoding

### Conversion from 24-bit RGB to 16-bit RGB565

```
R5 = (R8 * 31 + 127) / 255   // Round to nearest; equivalent to R8 >> 3
G6 = (G8 * 63 + 127) / 255   // Round to nearest; equivalent to G8 >> 2
B5 = (B8 * 31 + 127) / 255   // Round to nearest; equivalent to B8 >> 3

RGB565_word = (R5 << 11) | (G6 << 5) | B5
```

### BMP Format (Little-Endian) — Before rotatDerection

```
Low byte  (byte 0): [G2 G1 G0 B4 B3 B2 B1 B0]  = ((G & 0x07) << 5) | B
High byte (byte 1): [R4 R3 R2 R1 R0 G5 G4 G3]   = (R << 3) | (G >> 3)

Pixel as uint16 LE: high_byte << 8 | low_byte
```

### Watch Format (Big-Endian) — After rotatDerection

```
First byte  (byte 0): [R4 R3 R2 R1 R0 G5 G4 G3]  = (R << 3) | (G >> 3)   [HIGH byte]
Second byte (byte 1): [G2 G1 G0 B4 B3 B2 B1 B0]  = ((G & 0x07) << 5) | B  [LOW byte]

Pixel as uint16 BE: first_byte << 8 | second_byte
```

### Round-trip Verification

```
24-bit RGB pixel (R=128, G=64, B=32):

Standard RGB565:
  R5 = 128 >> 3 = 16     (0b10000)
  G6 = 64 >> 2 = 16      (0b010000)
  B5 = 32 >> 3 = 4       (0b00100)
  
RGB565 = 0b10000_010000_00100 = 0x8414

BMP (little-endian) bytes:  0x14, 0x84
Watch (big-endian) bytes:   0x84, 0x14
```

---

## 12. rotatDerection: BMP to Watch Byte Order

The `rotatDerection()` function is critical for converting BMP-native byte order to watch-native byte order.

### Algorithm

```java
private byte[] rotatDerection(int width, int height, byte[] bmpPixelData) {
    int totalBytes = bmpPixelData.length;             // = width * height * 2
    byte[] reversed = new byte[totalBytes];
    
    // Step 1: Reverse all bytes end-to-end
    for (int i = 0; i < totalBytes; i++) {
        reversed[i] = bmpPixelData[totalBytes - 1 - i];
    }
    
    // Step 2: Per-row byte-pair swap
    byte[] output = new byte[totalBytes];
    int bytesPerRow = width * 2;
    
    for (int row = 0; row < height; row++) {
        int rowStart = row * bytesPerRow;
        int rowEnd   = rowStart + bytesPerRow - 1;
        
        for (int byteIdx = 1; byteIdx < bytesPerRow; byteIdx += 2) {
            int fromEnd = rowEnd - byteIdx;
            output[rowStart + byteIdx]     = reversed[fromEnd + 1];  // even position
            output[rowStart + byteIdx - 1] = reversed[fromEnd];      // odd position
        }
    }
    
    return output;
}
```

### What it does

| Transformation | Effect |
|---------------|--------|
| Byte reverse (entire array) | Reverses row order (bottom-up → top-down), reverses pixel order within each row |
| Byte-pair swap (per row) | Swaps byte pair within each pixel (LE → BE), un-reverses pixels within row |

### Net effect

| BMP Input Property | Watch Output Property |
|-------------------|----------------------|
| Row order | Bottom-up → **Top-down** |
| Pixel order within row | Left-to-right (unchanged) |
| Pixel byte order | Little-endian → **Big-endian** |
| First byte in file | Bottom-left pixel low-byte → Top-left pixel high-byte |

### Step-by-step Example

**Input (BMP, 2×2 image, little-endian RGB565):**
```
Row 0 (bottom): [P0_lo, P0_hi, P1_lo, P1_hi]
Row 1 (top):    [P2_lo, P2_hi, P3_lo, P3_hi]
Array: [P0_lo, P0_hi, P1_lo, P1_hi, P2_lo, P2_hi, P3_lo, P3_hi]
```

**After byte-reverse:**
```
[P3_hi, P3_lo, P2_hi, P2_lo, P1_hi, P1_lo, P0_hi, P0_lo]
```

**After per-row byte-pair swap (rows of 4 bytes):**
```
Row 0: [P3_hi, P3_lo, P2_hi, P2_lo] → [P2_hi, P2_lo, P3_hi, P3_lo]
Row 1: [P1_hi, P1_lo, P0_hi, P0_lo] → [P0_hi, P0_lo, P1_hi, P1_lo]

Output: [P2_hi, P2_lo, P3_hi, P3_lo, P0_hi, P0_lo, P1_hi, P1_lo]
```

**Result:** Pixels P2 (top-left), P3 (top-right), P0 (bottom-left), P1 (bottom-right) — RGB565 big-endian, top-down, left-to-right.

---

## 13. Specification for Generating a Watch Face from Scratch

This section provides a complete, step-by-step procedure to generate a valid watch face binary that can be sent to a HiWatch Pro device.

### Prerequisites

- Source image (PNG, JPEG, or similar) at the exact watch display resolution (e.g., 240×240, 320×320, 360×360, 390×390, 454×454)
- Display dimensions and algorithm from `ClockDialInfoBody` (read from watch via BLE command `0x20, 0x02`)

### Generating Standard RGB565 Format (Algorithm 0, config[0]=1)

This is the most likely format for most devices. Here's the exact algorithm:

```
function generateWatchFace(image, width, height):
    // Step 1: Ensure correct dimensions
    assert image.width == width
    assert image.height == height
    assert width % 2 == 0          // even width required for no-padding assumption
    
    // Step 2: Convert to RGB565 pixel array
    pixels = []
    for y in 0..height-1:           // top-down row order
        for x in 0..width-1:        // left-to-right
            r, g, b = image.getPixel(x, y)
            
            // RGB565 conversion
            r5 = (r * 31 + 127) / 255    // or r >> 3
            g6 = (g * 63 + 127) / 255    // or g >> 2
            b5 = (b * 31 + 127) / 255    // or b >> 3
            
            rgb565 = (r5 << 11) | (g6 << 5) | b5
            
            // Store big-endian (high byte first)
            pixels.append((rgb565 >> 8) & 0xFF)   // high byte
            pixels.append(rgb565 & 0xFF)           // low byte
    
    // Step 3: Assemble final binary
    return bytes(pixels)
```

### Generating Yizhaowei Format (Algorithm 2)

```
function generateYizhaoweiWatchFace(image, width, height, fontBytes):
    // Step 1: Convert image to big-endian RGB565 (same as above)
    imageData = generateWatchFace(image, width, height)
    
    // Step 2: Create 10-byte Yizhaowei header
    header = bytearray(10)
    header[0] = 0x16
    header[1] = 0x01
    header[2] = width & 0xFF           // width little-endian
    header[3] = (width >> 8) & 0xFF
    header[4] = height & 0xFF          // height little-endian
    header[5] = (height >> 8) & 0xFF
    header[6] = 0x00
    header[7] = 0x00
    header[8] = 0x0A
    header[9] = 0x00
    
    // Step 3: Assemble
    return fontBytes + header + imageData
```

### Generating Thumbnail + Full Theme (Algorithm 0, with thumb)

```
function generateWithThumbnail(image, width, height, thumbPercent, fontBytes):
    // Step 1: Generate thumb dimensions
    thumbWidth = int(width * (thumbPercent / 100.0)) + 1
    thumbHeight = int(height * (thumbPercent / 100.0))
    
    // Step 2: Scale image to thumb size
    thumbImage = image.resize(thumbWidth, thumbHeight)
    
    // Step 3: Convert thumb to big-endian RGB565
    thumbData = generateWatchFace(thumbImage, thumbWidth, thumbHeight)
    
    // Step 4: Convert full image to big-endian RGB565
    mainData = generateWatchFace(image, width, height)
    
    // Step 5: Assemble (thumb PREPENDED)
    fontData = fontBytes  // as-is from server
    
    return thumbData + fontData + mainData
```

Note: For Yizhaowei (algorithm 2), the thumbnail also gets the 10-byte header.

### Complete BLE Transfer Packet Construction

```python
# Protocol constants
HEADER = 0xCD

def build_protocol_packet(main_cmd, sub_cmd, payload):
    """Build the 0xCD protocol envelope."""
    length = len(payload) + 5  # 3 (header+len) + 1 (main) + 1 (version) + payload_len_field(2) = ...?
    # Actually from SendData.java:
    # packet length = 8 + payload.length  (base = 8 bytes for header/version/sub/data_len)
    # Length field in packet = packet_length - 3
    
    packet_length = 8 + len(payload)
    length_field = packet_length - 3
    
    packet = bytearray()
    packet.append(HEADER)
    packet.append((length_field >> 8) & 0xFF)    # length big-endian (high byte of 2)
    packet.append(length_field & 0xFF)            # length big-endian (low byte)
    packet.append(main_cmd)
    packet.append(0x01)                           # version
    packet.append(sub_cmd)
    packet.append((len(payload) >> 8) & 0xFF)     # data length big-endian
    packet.append(len(payload) & 0xFF)
    packet.extend(payload)
    
    return bytes(packet)

def build_start_command(font_position, is_custom, bg_rgb=(255,255,255), pic_pos=0, has_pic_pos=False):
    payload = bytearray()
    payload.append(font_position)
    payload.append(1 if is_custom else 0)
    payload.extend(bg_rgb)  # R, G, B bytes
    if has_pic_pos:
        payload.append(pic_pos)
    return build_protocol_packet(0x1F, 0x02, payload)

def build_file_chunk(sequence_number, chunk_data):
    # payload = seq_num(2) + chunk_data + checksum(2)
    seq_bytes = [(sequence_number >> 8) & 0xFF, sequence_number & 0xFF]
    
    # checksum = sum of seq_bytes + chunk_data
    checksum = sum(seq_bytes) + sum(chunk_data)
    checksum &= 0xFFFF
    
    payload = bytearray(seq_bytes)
    payload.extend(chunk_data)
    payload.append((checksum >> 8) & 0xFF)
    payload.append(checksum & 0xFF)
    
    return build_protocol_packet(0x1F, 0x01, payload)

def build_finish_command(total_file_size, total_checksum):
    payload = bytearray()
    payload.append((total_file_size >> 24) & 0xFF)  # size big-endian
    payload.append((total_file_size >> 16) & 0xFF)
    payload.append((total_file_size >> 8) & 0xFF)
    payload.append(total_file_size & 0xFF)
    payload.append((total_checksum >> 24) & 0xFF)   # checksum big-endian  
    payload.append((total_checksum >> 16) & 0xFF)
    payload.append((total_checksum >> 8) & 0xFF)
    payload.append(total_checksum & 0xFF)
    
    return build_protocol_packet(0x1F, 0x03, payload)

def build_status_command():
    return build_protocol_packet(0x20, 0x01, b'')  # no payload

# Full transfer
def send_watch_face(ble_connection, watch_face_data, chunk_size=200):
    total_size = len(watch_face_data)
    total_checksum = sum(watch_face_data) & 0xFFFFFFFF
    
    # Send start (simplified - real values come from theme metadata)
    start_cmd = build_start_command(0, True)
    ble_connection.write(start_cmd)
    
    # Wait for ACK 1000
    ack = ble_connection.read()
    assert ack_value(ack) == 1000
    
    # Send chunks
    seq = 1
    for offset in range(0, total_size, chunk_size):
        chunk = watch_face_data[offset:offset + chunk_size]
        pkt = build_file_chunk(seq, chunk)
        ble_connection.write(pkt)
        
        # Wait for ACK
        ack = ble_connection.read()
        ack_num = ack_value(ack)
        assert ack_num == 1000 + seq or ack_num == 1000 + seq - 1  # allow resend
        seq += 1
    
    # Send finish
    finish_cmd = build_finish_command(total_size, total_checksum)
    ble_connection.write(finish_cmd)
    
    # Wait for success
    ack = ble_connection.read()
    assert ack_value(ack) == 2  # success

def ack_value(response_packet):
    # Parse watch response - need to extract ACK value
    # Response is also 0xCD protocol; parse accordingly
    pass
```

### Autogeneration Example (Python)

```python
from PIL import Image
import struct

def create_watch_face_bin(image_path, width, height, algorithm=0, 
                          config_bit0=1, font_bytes=None, 
                          thumb_percent=None):
    """
    Generate a complete watch face binary for BLE transfer.
    
    Args:
        image_path: Path to source image
        width, height: Display dimensions
        algorithm: 0=standard, 1=Beken, 2=Yizhaowei
        config_bit0: 1=strip BMP header, 0=keep BMP header
        font_bytes: Font binary data (None for fixed themes)
        thumb_percent: Thumbnail scale (None for no thumbnail)
    
    Returns:
        bytes: Complete watch face binary ready for BLE transfer
    """
    img = Image.open(image_path).convert('RGB')
    img = img.resize((width, height))
    
    # Convert to big-endian RGB565
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            r, g, b = img.getpixel((x, y))
            r5 = (r * 31 + 127) // 255
            g6 = (g * 63 + 127) // 255
            b5 = (b * 31 + 127) // 255
            rgb565 = (r5 << 11) | (g6 << 5) | b5
            pixels.append((rgb565 >> 8) & 0xFF)  # high byte
            pixels.append(rgb565 & 0xFF)          # low byte
    
    result = bytearray()
    
    # Optional thumbnail
    if thumb_percent is not None:
        tw = int(width * (thumb_percent / 100.0)) + 1
        th = int(height * (thumb_percent / 100.0))
        thumb = img.resize((tw, th))
        thumb_bytes = bytearray()
        for y in range(th):
            for x in range(tw):
                r, g, b = thumb.getpixel((x, y))
                r5 = (r * 31 + 127) // 255
                g6 = (g * 63 + 127) // 255
                b5 = (b * 31 + 127) // 255
                rgb565 = (r5 << 11) | (g6 << 5) | b5
                thumb_bytes.append((rgb565 >> 8) & 0xFF)
                thumb_bytes.append(rgb565 & 0xFF)
        if algorithm == 2:
            # Yizhaowei header for thumbnail too
            hdr = bytearray([0x16, 0x01])
            hdr.extend(struct.pack('<H', tw))  # width LE
            hdr.extend(struct.pack('<H', th))  # height LE
            hdr.extend([0x00, 0x00, 0x0A, 0x00])
            result.extend(hdr + thumb_bytes)
        else:
            result.extend(thumb_bytes)
    
    # Font data (custom themes)
    if font_bytes is not None:
        result.extend(font_bytes)
    
    # Image data
    if algorithm == 2:
        # Yizhaowei header + big-endian RGB565
        hdr = bytearray([0x16, 0x01])
        hdr.extend(struct.pack('<H', width))
        hdr.extend(struct.pack('<H', height))
        hdr.extend([0x00, 0x00, 0x0A, 0x00])
        result.extend(hdr + pixels)
    elif algorithm == 1:
        # Beken format: use native library or 16-bit BMP
        # Fall through to standard with BMP header
        bmp = _create_16bit_bmp(pixels, width, height)
        result.extend(bmp)
    else:
        # Standard
        if config_bit0 == 1:
            # Raw big-endian pixels (no header)
            result.extend(pixels)
        else:
            # 16-bit BMP with header
            bmp = _create_16bit_bmp(pixels, width, height)
            result.extend(bmp)
    
    return bytes(result)

def _create_16bit_bmp(rgb565_be_pixels, width, height):
    """
    Create a 16-bit BMP file from big-endian RGB565 pixel data.
    Converts back to little-endian for BMP compliance.
    """
    total_pixels = width * height
    row_size = width * 2
    padded_row_size = ((row_size + 3) // 4) * 4
    padding = padded_row_size - row_size
    
    # BMP header (54 bytes)
    pixel_data_size = padded_row_size * height
    file_size = 54 + pixel_data_size
    
    bmp = bytearray()
    # File header
    bmp.extend(b'BM')
    bmp.extend(struct.pack('<I', file_size))
    bmp.extend(struct.pack('<HH', 0, 0))
    bmp.extend(struct.pack('<I', 54))
    # Info header
    bmp.extend(struct.pack('<I', 40))
    bmp.extend(struct.pack('<i', width))
    bmp.extend(struct.pack('<i', height))
    bmp.extend(struct.pack('<H', 1))
    bmp.extend(struct.pack('<H', 16))
    bmp.extend(struct.pack('<I', 0))
    bmp.extend(struct.pack('<I', pixel_data_size))
    bmp.extend(struct.pack('<i', 0))
    bmp.extend(struct.pack('<i', 0))
    bmp.extend(struct.pack('<I', 0))
    bmp.extend(struct.pack('<I', 0))
    
    # Pixel data (bottom-up, little-endian)
    for y in range(height - 1, -1, -1):
        row_start = y * width * 2
        for x in range(width):
            hi = rgb565_be_pixels[row_start + x * 2]
            lo = rgb565_be_pixels[row_start + x * 2 + 1]
            # Convert BE to LE: swap bytes back
            bmp.append(lo)  # low byte first (BMP LE)
            bmp.append(hi)  # high byte second
        # Padding
        bmp.extend(b'\x00' * padding)
    
    return bytes(bmp)
```

### Verification Checklist

To verify a generated watch face binary will work:

1. **Dimensions:** Width must be even (required by `getNotHeaderBmp` assumption)
2. **Pixel format:** Big-endian RGB565 (high byte first, low byte second)
3. **Row order:** Top-down (first pixel in file = top-left of image)
4. **Color range:** R5 (0-31), G6 (0-63), B5 (0-31)
5. **File size** (raw pixels only): exactly `width × height × 2` bytes
6. **Yizhaowei header:** 10 bytes, little-endian width/height, magic `16 01`, flags `00 00 0A 00`
7. **Thumbnail:** Same format as main image, prepended, at `(width×percent/100+1) × (height×percent/100)` resolution
8. **Font:** Any `.bin` from the official server — pass-through, no transformation
9. **Checksums:** Per-chunk additive 16-bit, total additive 32-bit

---

## References

- **Source files:** 
  - `xfkj/fitpro/activity/clockDial/WatchThemeHelper.java` — algorithm selection
  - `xfkj/fitpro/utils/WatchThemeTools.java` — file assembly, byte order, BLE transfer
  - `xfkj/fitpro/jni/BmpConvertTools.java` — JNI bridge to `libbmp-lib.so`
  - `xfkj/fitpro/bluetooth/SendData.java` — BLE command packet construction
  - `xfkj/fitpro/utils/NumberUtils.java` — endianness conversion functions
  - `xfkj/fitpro/utils/bmp/BitmapConverter.java` — 24-bit BMP writer
  - `xfkj/fitpro/model/sever/body/ClockDialInfoBody.java` — device config model
- **Native library:** `libbmp-lib.so` (24→16 bit conversion, Beken format)
- **BLE service UUID:** `00001810-0000-1000-8000-00805f9b34fb`
- **Characteristic UUID:** `00002a30-0000-1000-8000-00805f9b34fb`
