"""
``rotatDerection`` — BMP byte order to watch-native byte order.

This is the critical transformation that converts a 16-bit BMP image
(little-endian RGB565, bottom-up rows) into the format the watch requires
(big-endian RGB565, top-down rows).

Algorithm (from ``WatchThemeTools.rotatDerection()``)::

    1. Reverse all bytes end-to-end (entire pixel array).
    2. Within each row, swap adjacent byte pairs (pixel byte swapping).

Net effect
----------
+---------------------------+---------------------------+
| BMP Input                 | Watch Output              |
+===========================+===========================+
| Row order: bottom-up      | Row order: top-down       |
| Pixel order: left-to-right| Pixel order: left-to-right|
| Pixel endian: little      | Pixel endian: big         |
| First byte: bottom-left LO| First byte: top-left HI   |
+---------------------------+---------------------------+

Reference
---------
``WatchThemeTools.rotatDerection(int width, int height, byte[] bmpPixels)``
"""

from __future__ import annotations

import array


def rotat_derection(width: int, height: int, bmp_pixels: bytes) -> bytearray:
    """Convert BMP-native pixel data to watch-native byte order.

    Parameters
    ----------
    width:
        Image width in pixels. **Must be even** (required by the
        ``getNotHeaderBmp`` assumption that ``width * 2`` is a valid
        row-byte-count with no padding).
    height:
        Image height in pixels.
    bmp_pixels:
        Raw 16-bit RGB565 pixel data in **BMP format**:
        little-endian byte order, bottom-up rows, tightly packed
        (2 bytes per pixel, no row padding). This is what you get
        after stripping the 54-byte BMP header.

    Returns
    -------
    ``bytearray``
        Watch-native format: **big-endian** RGB565, **top-down** rows,
        tightly packed, ``width * height * 2`` bytes.
    """
    total_bytes = width * height * 2
    if len(bmp_pixels) != total_bytes:
        raise ValueError(
            f"Expected {total_bytes} bytes ({width}×{height}×2), "
            f"got {len(bmp_pixels)}"
        )

    # Step 1: Reverse all bytes end-to-end.
    # This flips bottom-up → top-down row order AND reverses
    # pixel order within each row.
    #
    # Using array('B') for fast byte reversal via memoryview slice.
    src = array.array("B", bmp_pixels)
    src.reverse()

    # Step 2: Per-row byte-pair swap.
    # For each row, swap adjacent byte pairs (pixel bytes).
    # This un-reverses the pixels within each row AND converts
    # from little-endian to big-endian.
    dst = array.array("B", b"\x00") * total_bytes
    bytes_per_row = width * 2

    for row in range(height):
        row_start = row * bytes_per_row
        row_end = row_start + bytes_per_row - 1

        for byte_idx in range(1, bytes_per_row, 2):
            from_end = row_end - byte_idx
            dst[row_start + byte_idx] = src[from_end + 1]  # even position
            dst[row_start + byte_idx - 1] = src[from_end]  # odd position

    return bytearray(dst)


def rotat_derection_inverse(width: int, height: int, watch_pixels: bytes) -> bytearray:
    """Reverse of :func:`rotat_derection`.

    Converts watch-native big-endian top-down pixels back to BMP format
    (little-endian bottom-up). Useful for verifying round-trip fidelity.
    """
    total_bytes = width * height * 2
    if len(watch_pixels) != total_bytes:
        raise ValueError(
            f"Expected {total_bytes} bytes, got {len(watch_pixels)}"
        )

    src = array.array("B", watch_pixels)
    bytes_per_row = width * 2

    # Step 1: Undo per-row byte-pair swap
    # Forward: dst[row_start + byte_idx]     = src[from_end + 1]
    #          dst[row_start + byte_idx - 1] = src[from_end]
    # Inverse: src[from_end + 1] = watch[row_start + byte_idx]
    #          src[from_end]     = watch[row_start + byte_idx - 1]
    tmp = array.array("B", b"\x00") * total_bytes
    for row in range(height):
        row_start = row * bytes_per_row
        row_end = row_start + bytes_per_row - 1

        for byte_idx in range(1, bytes_per_row, 2):
            from_end = row_end - byte_idx
            tmp[from_end + 1] = src[row_start + byte_idx]
            tmp[from_end] = src[row_start + byte_idx - 1]

    # Step 2: Reverse all bytes end-to-end to get back to BMP order
    tmp.reverse()
    return bytearray(tmp)
