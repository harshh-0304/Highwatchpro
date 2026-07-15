"""
Watch face transfer orchestrator.

Implements the full dial-update protocol matching ``WatchThemeTools``::

    1. Send Start (0x1F, 0x02) with metadata
    2. Wait for ACK (response = 1000)
    3. Send chunks   (0x1F, 0x01) with seq_num and checksum
    4. Wait for ACK after each chunk
    5. Send Finish   (0x1F, 0x03) with total size and checksum
    6. Watch responds 2 (success)

Chunk size is controlled by config bit 1 (120 or 200 bytes).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional

from ..protocol.commands import (
    build_dial_start,
    build_dial_file_chunk,
    build_dial_finish,
    build_dial_read_status,
)
from ..protocol.constants import (
    RESP_ACK_BASE,
    RESP_CHECK_FAILED,
    RESP_SUCCESS,
    RESP_BATTERY_LOW,
    RESP_CHARGE_REQUIRED,
    RESP_OUT_OF_MEMORY,
)
from ..protocol.packet import Packet
from .connection import WatchConnection

logger = logging.getLogger(__name__)


class TransferState(Enum):
    IDLE = auto()
    STARTING = auto()
    SENDING = auto()
    FINISHING = auto()
    SUCCESS = auto()
    FAILED = auto()


@dataclass
class TransferProgress:
    """Current transfer progress."""

    state: TransferState = TransferState.IDLE
    total_bytes: int = 0
    sent_bytes: int = 0
    chunk_size: int = 200
    sequence: int = 0
    error_message: str = ""

    @property
    def percent(self) -> float:
        if self.total_bytes == 0:
            return 0.0
        return min(self.sent_bytes / self.total_bytes, 1.0)

    @property
    def is_done(self) -> bool:
        return self.state in (TransferState.SUCCESS, TransferState.FAILED)


ProgressCallback = Callable[[TransferProgress], None]


class WatchFaceTransfer:
    """
    Orchestrates sending a watch face binary to the device.

    Usage::

        transfer = WatchFaceTransfer(connection)
        progress = await transfer.run(binary_data, font_position=0, is_custom=True)
    """

    def __init__(
        self,
        connection: WatchConnection,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> None:
        self._conn = connection
        self._callback = progress_callback
        self._progress = TransferProgress()
        self._pending_resend: Optional[asyncio.Future] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        binary_data: bytes,
        font_position: int = 0,
        is_custom: bool = True,
        bg_r: int = 0xFF,
        bg_g: int = 0xFF,
        bg_b: int = 0xFF,
        replace_pic_pos: Optional[int] = None,
        chunk_size: int = 200,
    ) -> TransferProgress:
        """Execute the full transfer sequence.

        Parameters
        ----------
        binary_data:
            The assembled watch face binary (thumbnail + font + image).
        font_position:
            Font slot index on the watch.
        is_custom:
            Whether this is a custom theme (has separate font data).
        bg_r, bg_g, bg_b:
            Background colour (default white).
        replace_pic_pos:
            Picture-slot index (``None`` if not applicable).
        chunk_size:
            BLE write chunk size (120 or 200, config bit 1).

        Returns
        -------
        ``TransferProgress`` with final state.
        """
        self._progress = TransferProgress(
            total_bytes=len(binary_data),
            chunk_size=chunk_size,
        )

        try:
            # --- Step 1: Send Start ---
            self._progress.state = TransferState.STARTING
            self._emit_progress()

            start_pkt = build_dial_start(
                font_position=font_position,
                is_custom=is_custom,
                bg_r=bg_r,
                bg_g=bg_g,
                bg_b=bg_b,
                replace_pic_pos=replace_pic_pos,
            )
            response = await self._write_and_wait(start_pkt, timeout=10.0)
            if not self._is_ack(response, 0):
                raise TransferError(f"Start ACK failed: {_response_summary(response)}")

            # --- Step 2: Send file chunks ---
            self._progress.state = TransferState.SENDING
            self._emit_progress()

            seq = 1
            for offset in range(0, len(binary_data), chunk_size):
                chunk = binary_data[offset : offset + chunk_size]
                chunk_pkt = build_dial_file_chunk(seq, chunk)

                response = await self._write_and_wait(chunk_pkt, timeout=10.0)
                if not self._is_ack(response, seq):
                    # Checksum error or sequence mismatch — resend
                    logger.warning("Chunk %d NACK, resending...", seq)
                    response = await self._write_and_wait(chunk_pkt, timeout=10.0)
                    if not self._is_ack(response, seq):
                        raise TransferError(f"Chunk {seq} failed after resend")

                self._progress.sequence = seq
                self._progress.sent_bytes = offset + len(chunk)
                self._emit_progress()
                seq += 1

            # --- Step 3: Send Finish ---
            self._progress.state = TransferState.FINISHING
            self._emit_progress()

            total_checksum = sum(binary_data) & 0xFFFFFFFF
            finish_pkt = build_dial_finish(len(binary_data), total_checksum)
            response = await self._write_and_wait(finish_pkt, timeout=10.0)

            if self._is_success(response):
                self._progress.state = TransferState.SUCCESS
            else:
                code = _parse_response_code(response)
                error_msg = _error_message(code)
                raise TransferError(f"Finish failed: {error_msg} (code={code})")

        except TransferError:
            self._progress.state = TransferState.FAILED
            self._progress.error_message = str(sys.exc_info()[1])  # noqa: F821
        except Exception as exc:
            self._progress.state = TransferState.FAILED
            self._progress.error_message = str(exc)
            logger.error("Transfer error: %s", exc)

        self._emit_progress()
        return self._progress

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _write_and_wait(self, packet: Packet, timeout: float) -> Optional[bytearray]:
        await self._conn.write(packet.data)
        return await self._conn.wait_for_notification(timeout=timeout)

    @staticmethod
    def _is_ack(response: Optional[bytearray], seq: int) -> bool:
        if response is None or len(response) < 8:
            return False
        parsed = Packet.parse_response(bytes(response))
        if not parsed["is_valid"]:
            return False
        payload = parsed["payload"]
        if len(payload) < 1:
            return False
        val = payload[0]
        # ACK base + seq means watch confirms receipt of packet `seq`
        # The watch may respond with 1000 + seq
        # Or in some cases just seq
        if val >= RESP_ACK_BASE and (val - RESP_ACK_BASE) == seq:
            return True
        if val == seq:  # some firmwares omit the base
            return True
        return False

    @staticmethod
    def _is_success(response: Optional[bytearray]) -> bool:
        if response is None:
            return False
        parsed = Packet.parse_response(bytes(response))
        if not parsed["is_valid"]:
            return False
        payload = parsed["payload"]
        return len(payload) >= 1 and payload[0] == RESP_SUCCESS

    def _emit_progress(self) -> None:
        if self._callback:
            self._callback(self._progress)


def _parse_response_code(data: Optional[bytearray]) -> int:
    if data is None or len(data) < 8:
        return -1
    parsed = Packet.parse_response(bytes(data))
    if not parsed["is_valid"] or len(parsed["payload"]) < 1:
        return -1
    return parsed["payload"][0]


def _response_summary(data: Optional[bytearray]) -> str:
    if data is None:
        return "no-response"
    return data.hex()[:20]


def _error_message(code: int) -> str:
    return {
        RESP_CHECK_FAILED: "Checksum error",
        RESP_BATTERY_LOW: "Battery too low",
        RESP_CHARGE_REQUIRED: "Device charging",
        RESP_OUT_OF_MEMORY: "Out of memory",
    }.get(code, f"Unknown code {code}")


# Need to import sys for exc_info — fix by importing at top
import sys  # noqa: E402


class TransferError(Exception):
    """Raised when a transfer step fails."""
