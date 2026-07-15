#!/usr/bin/env python3
"""
Upload a watch face image to the Ultra3 smartwatch via BLE GATT (D-Bus).

Uses the D-Bus GATT transport directly (bypassing Bleak, which cannot
discover this device).  The transfer protocol matches the Java app::

    1. Start  (0x1F, 0x02) — metadata (font pos, custom flag, bg colour)
    2. Chunks (0x1F, 0x01) — file data with seq number + checksum
    3. Finish (0x1F, 0x03) — total size + total checksum

Usage
-----

    # Convert and upload in one step
    python diagnostics/upload_face.py --image my_design.png

    # Upload pre-existing .bin
    python diagnostics/upload_face.py --binary watchface.bin

    # Convert only (save .bin, don't upload)
    python diagnostics/upload_face.py --image my_design.png --no-upload

    # Custom MAC / chunk-size / thumbnail
    python diagnostics/upload_face.py --image my_design.png \\
        --mac 66:22:AA:00:42:78 --chunk-size 120 --no-thumbnail
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional, Tuple

# Add the HiWatchToolkit package to sys.path so we can import its modules.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HITOOLKIT = _PROJECT_ROOT / "HiWatchToolkit"
sys.path.insert(0, str(_HITOOLKIT))

from PIL import Image

from src.hiwatch_toolkit.ble.dbus_transport import DBusGATTTransport
from src.hiwatch_toolkit.protocol.commands import (
    build_dial_start,
    build_dial_file_chunk,
    build_dial_finish,
)
from src.hiwatch_toolkit.protocol.constants import (
    RESP_ACK_BASE,
    RESP_SUCCESS,
    RESP_CHECK_FAILED,
    RESP_BATTERY_LOW,
    RESP_CHARGE_REQUIRED,
    RESP_OUT_OF_MEMORY,
)
from src.hiwatch_toolkit.protocol.packet import Packet
from src.hiwatch_toolkit.watchface.builder import WatchFaceBuilder
from src.hiwatch_toolkit.watchface.models import WatchFaceFormat

logger = logging.getLogger("upload_face")

# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

DEFAULT_MAC = "66:22:AA:00:42:78"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Upload a watch face to an Ultra3 smartwatch via BLE GATT.",
    )

    # Input source (mutually exclusive-ish — checked after parsing)
    inp = p.add_mutually_exclusive_group()
    inp.add_argument("--image", help="Source image path (PNG, JPG, …)")
    inp.add_argument("--binary", help="Pre-built .bin watch face file")

    # Watch / display parameters
    p.add_argument("--mac", default=DEFAULT_MAC, help="Watch BLE MAC address")
    p.add_argument("--width", type=int, default=240, help="Display width (px)")
    p.add_argument("--height", type=int, default=240, help="Display height (px)")
    p.add_argument(
        "--algorithm",
        type=int,
        default=0,
        choices=[0, 1, 2, 3],
        help="Conversion format (0 = standard RGB565)",
    )

    # Thumbnail
    p.add_argument(
        "--thumbnail",
        type=int,
        default=25,
        metavar="PCT",
        help="Thumbnail scale percent (0 = none, default 25)",
    )
    p.add_argument(
        "--no-thumbnail",
        dest="thumbnail",
        action="store_const",
        const=0,
        help="Disable thumbnail generation",
    )

    # Transfer options
    p.add_argument(
        "--chunk-size",
        type=int,
        default=200,
        choices=[120, 200],
        help="BLE write chunk size (120 or 200, default 200)",
    )
    p.add_argument("--font-position", type=int, default=0, help="Font slot index")
    p.add_argument(
        "--custom",
        action="store_true",
        default=True,
        help="Mark as custom theme (default)",
    )
    p.add_argument("--no-custom", dest="custom", action="store_false")

    # Background colour
    p.add_argument("--bg-r", type=int, default=0xFF, help="Background red (0-255)")
    p.add_argument("--bg-g", type=int, default=0xFF, help="Background green (0-255)")
    p.add_argument("--bg-b", type=int, default=0xFF, help="Background blue (0-255)")

    # Actions
    p.add_argument(
        "--no-upload",
        action="store_true",
        help="Convert image only; do not upload",
    )
    p.add_argument(
        "--output",
        "-o",
        help="Output .bin path (auto-derived from --image by default)",
    )

    # Debug
    p.add_argument("--verbose", "-v", action="store_true", help="Debug logging")

    return p


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = build_parser()
    args = p.parse_args(argv)
    if not args.image and not args.binary:
        p.error("Specify --image or --binary")
    return args


# ---------------------------------------------------------------------------
# Image conversion
# ---------------------------------------------------------------------------


def convert_image(args: argparse.Namespace) -> Tuple[bytes, int]:
    """Convert source image to watch-native binary.

    Returns
    -------
    ``(binary_blob, additive_checksum_32)``
    """
    print(f"\n{'=' * 50}")
    print(f"  Image:  {args.image}")
    print(f"  Size:   {args.width} x {args.height}")
    print(f"  Algo:   {args.algorithm} ({WatchFaceFormat(args.algorithm).name})")
    print(f"{'=' * 50}")

    img = Image.open(args.image).convert("RGB")
    builder = WatchFaceBuilder(
        img,
        args.width,
        args.height,
        name=Path(args.image).stem,
    )

    if args.thumbnail and args.thumbnail > 0:
        builder.set_thumbnail(percent=min(args.thumbnail, 100))

    algorithm = WatchFaceFormat(args.algorithm)
    binary_data, meta = builder.build(algorithm=algorithm)

    print(f"  Binary: {len(binary_data):,} bytes")
    print(f"  CRC32:  0x{meta.checksum:08X}")
    print(f"  Thumb:  {meta.has_thumbnail} ({meta.thumb_percent}%)")
    print(f"  Font:   {meta.has_font}")
    print()

    return binary_data, meta.checksum


def save_binary(args: argparse.Namespace, data: bytes) -> str:
    """Write binary to disk and return the file path."""
    if args.output:
        path = args.output
    elif args.image:
        stem = Path(args.image).stem
        path = f"{stem}_watch.bin"
    else:
        path = "watchface.bin"

    Path(path).write_bytes(data)
    print(f"  💾 Saved → {path}")
    return path


# ---------------------------------------------------------------------------
# BLE transfer
# ---------------------------------------------------------------------------


async def transfer_to_watch(
    mac: str,
    data: bytes,
    checksum_32: int,
    args: argparse.Namespace,
) -> bool:
    """Run the full dial-update protocol over D-Bus BLE GATT.

    Returns ``True`` on success, ``False`` on any failure.
    """
    print(f"\n{'=' * 50}")
    print(f"  Target: {mac}")
    print(f"  Chunks: {args.chunk_size} B")
    print(f"  Total:  {len(data):,} bytes")
    print(f"{'=' * 50}\n")

    try:
        async with DBusGATTTransport(mac) as transport:
            print("  ✅  BLE GATT connected\n")

            # ---- Step 1: Start -------------------------------------------------
            print("  [1/3] Sending START ...", end=" ")
            sys.stdout.flush()

            start_pkt = build_dial_start(
                font_position=args.font_position,
                is_custom=args.custom,
                bg_r=args.bg_r,
                bg_g=args.bg_g,
                bg_b=args.bg_b,
            )
            await transport.write(start_pkt.data)
            resp = await transport.wait_for_notification(timeout=10.0)

            if resp is None:
                print("⏱  no response")
                return False
            ack = _parse_ack_seq(resp)
            if ack != 0:
                print(f"NACK (expected ACK 0, got {ack})")
                return False
            print("✅")

            # ---- Step 2: Chunks ------------------------------------------------
            chunk_sz = args.chunk_size
            total_chunks = (len(data) + chunk_sz - 1) // chunk_sz
            print(f"  [2/3] Sending {total_chunks} chunk(s) ...")

            for seq in range(1, total_chunks + 1):
                offset = (seq - 1) * chunk_sz
                chunk = data[offset : offset + chunk_sz]

                chunk_pkt = build_dial_file_chunk(seq, chunk)
                await transport.write(chunk_pkt.data)
                resp = await transport.wait_for_notification(timeout=10.0)

                if resp is None:
                    print(f"\n        ⏱  Chunk {seq}/{total_chunks} — no response")
                    return False

                ack = _parse_ack_seq(resp)
                if ack != seq:
                    # One automatic retry
                    print(f"\n        ⚠  Chunk {seq} NACK — retrying ...", end=" ")
                    await transport.write(chunk_pkt.data)
                    resp = await transport.wait_for_notification(timeout=10.0)
                    if resp is None:
                        print("⏱  still no response")
                        return False
                    ack = _parse_ack_seq(resp)
                    if ack != seq:
                        print(f"still NACK (seq={ack})")
                        return False
                    print("✅")

                _show_progress(seq, total_chunks)

            print("        ✅  All chunks sent\n")

            # ---- Step 3: Finish ------------------------------------------------
            print("  [3/3] Sending FINISH ...", end=" ")
            sys.stdout.flush()

            finish_pkt = build_dial_finish(len(data), checksum_32)
            await transport.write(finish_pkt.data)
            resp = await transport.wait_for_notification(timeout=15.0)

            if resp is None:
                print("⏱  no response")
                return False

            result = _parse_finish_response(resp)
            if result == "success":
                print("✅  Watch face installed!\n")
                return True
            else:
                print(f"❌  {result}\n")
                return False

    except Exception as exc:
        logger.exception("Transfer crashed")
        print(f"\n  ❌  Error: {exc}")
        return False


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def _parse_ack_seq(raw: bytes) -> int:
    """Extract ACK sequence number (0-based) from a notification.

    Returns ``-1`` if the payload is not a valid ACK.
    """
    try:
        parsed = Packet.parse_response(raw)
        if not parsed["is_valid"]:
            return -1
        payload = parsed["payload"]
        if not payload:
            return -1
        val = payload[0]
        if val >= RESP_ACK_BASE:
            return val - RESP_ACK_BASE
        if val < 0x80:  # some firmware omits the base
            return val
        return -1
    except Exception:
        return -1


def _parse_finish_response(raw: bytes) -> str:
    """Interpret the watch's reply to the Finish command."""
    try:
        parsed = Packet.parse_response(raw)
        if not parsed["is_valid"]:
            return "invalid packet"
        payload = parsed["payload"]
        if not payload:
            return "empty payload"
        code = payload[0]
        return {
            RESP_SUCCESS: "success",
            RESP_CHECK_FAILED: "checksum error",
            RESP_BATTERY_LOW: "battery too low",
            RESP_CHARGE_REQUIRED: "watch is charging",
            RESP_OUT_OF_MEMORY: "out of memory",
        }.get(code, f"unknown code {code}")
    except Exception as exc:
        return f"parse error: {exc}"


# ---------------------------------------------------------------------------
# Progress bar
# ---------------------------------------------------------------------------


def _show_progress(current: int, total: int, width: int = 30) -> None:
    """Print an in-place progress bar."""
    filled = int(width * current / total)
    bar = "█" * filled + "░" * (width - filled)
    pct = 100.0 * current / total
    print(f"\r        [{bar}] {current:>3}/{total} ({pct:5.1f}%)", end="")
    if current == total:
        print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def amain(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )

    # ---- 1. Obtain binary data ------------------------------------------------
    if args.binary:
        data = Path(args.binary).read_bytes()
        checksum_32 = sum(data) & 0xFFFFFFFF
        print(f"\n{'=' * 50}")
        print(f"  Binary: {args.binary}")
        print(f"  Size:   {len(data):,} bytes")
        print(f"  CRC32:  0x{checksum_32:08X}")
        print(f"{'=' * 50}\n")
    else:
        data, checksum_32 = convert_image(args)
        out = save_binary(args, data)

    # ---- 2. Upload (unless --no-upload) ---------------------------------------
    if args.no_upload:
        print("  ⏭  --no-upload set; skipping BLE transfer\n")
        return 0

    ok = await transfer_to_watch(args.mac, data, checksum_32, args)

    print()
    print("=" * 50)
    print(f"  {'✅  UPLOAD SUCCESSFUL' if ok else '❌  UPLOAD FAILED'}")
    print("=" * 50)
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(amain(argv))


if __name__ == "__main__":
    sys.exit(main())
