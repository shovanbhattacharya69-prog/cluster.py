"""Cross-platform CAN bus factory supporting Linux SocketCAN and Windows IPC."""

from __future__ import annotations

import logging
import mmap
import os
import platform
import struct
import tempfile
import time
from typing import Optional

import can

LOGGER = logging.getLogger("can_bus")

HEADER_FORMAT = "!8sIIQ"  # magic (8s), capacity (I), slot_size (I), write_seq (Q)
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 24 bytes
SLOT_FORMAT = "!QIBBHd8s"  # seq (Q), arb_id (I), dlc (B), flags (B), reserved (H), timestamp (d), data (8s)
SLOT_SIZE = struct.calcsize(SLOT_FORMAT)  # 32 bytes
DEFAULT_CAPACITY = 2048
MAGIC = b"VCANRING"


class ShmCanBus(can.BusABC):
    """Zero-dependency, cross-process virtual CAN bus using a memory-mapped ring buffer."""

    def __init__(
        self,
        channel: str = "vcan0",
        capacity: int = DEFAULT_CAPACITY,
        receive_own_messages: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(channel=channel, **kwargs)
        self.capacity = capacity
        self.receive_own_messages = receive_own_messages
        self.channel_info = f"ShmCanBus(channel={channel})"

        temp_dir = tempfile.gettempdir()
        safe_chan = "".join(c if c.isalnum() else "_" for c in str(channel))
        self.file_path = os.path.join(temp_dir, f"vcan_{safe_chan}.ipc")

        file_size = HEADER_SIZE + self.capacity * SLOT_SIZE
        if not os.path.exists(self.file_path):
            try:
                with open(self.file_path, "x+b") as f:
                    f.write(struct.pack(HEADER_FORMAT, MAGIC, self.capacity, SLOT_SIZE, 0))
                    f.write(b"\x00" * (self.capacity * SLOT_SIZE))
                    f.flush()
            except FileExistsError:
                pass

        self._f = open(self.file_path, "r+b")
        self._mmap = mmap.mmap(self._f.fileno(), file_size)

        magic, cap, s_size, current_seq = struct.unpack_from(HEADER_FORMAT, self._mmap, 0)
        self._read_seq = current_seq
        self._is_open = True

    def send(self, msg: can.Message, timeout: Optional[float] = None) -> None:
        if not self._is_open:
            raise can.CanOperationError("Bus is closed")

        data_bytes = bytes(msg.data)[:8].ljust(8, b"\x00")
        dlc = len(msg.data)
        flags = (1 if msg.is_extended_id else 0) | ((1 if msg.is_error_frame else 0) << 1)
        ts = msg.timestamp if msg.timestamp else time.time()

        magic, cap, s_size, write_seq = struct.unpack_from(HEADER_FORMAT, self._mmap, 0)
        next_seq = write_seq + 1
        slot_idx = next_seq % self.capacity
        slot_offset = HEADER_SIZE + slot_idx * SLOT_SIZE

        slot_data = struct.pack(
            SLOT_FORMAT,
            next_seq,
            msg.arbitration_id,
            dlc,
            flags,
            0,
            ts,
            data_bytes,
        )
        self._mmap[slot_offset : slot_offset + SLOT_SIZE] = slot_data
        struct.pack_into("!Q", self._mmap, 16, next_seq)
        self._mmap.flush()

    def _recv_internal(
        self, timeout: Optional[float]
    ) -> tuple[Optional[can.Message], bool]:
        if not self._is_open:
            raise can.CanOperationError("Bus is closed")

        start_time = time.monotonic()
        while True:
            current_write_seq = struct.unpack_from("!Q", self._mmap, 16)[0]

            if current_write_seq > self._read_seq:
                if current_write_seq - self._read_seq > self.capacity:
                    self._read_seq = current_write_seq - self.capacity

                next_seq = self._read_seq + 1
                slot_idx = next_seq % self.capacity
                slot_offset = HEADER_SIZE + slot_idx * SLOT_SIZE
                slot_bytes = self._mmap[slot_offset : slot_offset + SLOT_SIZE]
                seq, arb_id, dlc, flags, _, ts, data_bytes = struct.unpack(
                    SLOT_FORMAT, slot_bytes
                )

                if seq == next_seq:
                    self._read_seq = next_seq
                    msg = can.Message(
                        arbitration_id=arb_id,
                        data=data_bytes[:dlc],
                        is_extended_id=bool(flags & 1),
                        is_error_frame=bool(flags & 2),
                        timestamp=ts,
                        channel=self.channel_info,
                    )
                    return msg, False
                else:
                    self._read_seq = current_write_seq

            if timeout is not None:
                if (time.monotonic() - start_time) >= timeout:
                    return None, False
                time.sleep(0.002)
            else:
                time.sleep(0.002)

    def shutdown(self) -> None:
        if self._is_open:
            self._is_open = False
            try:
                self._mmap.close()
                self._f.close()
            except OSError:
                pass
        super().shutdown()


def create_bus(channel: str = "vcan0") -> can.BusABC:
    """Open virtual CAN interface, using ShmCanBus on Windows or SocketCAN on Linux."""
    if platform.system() == "Windows":
        LOGGER.info("Using shared-memory virtual CAN bus channel '%s' on Windows.", channel)
        try:
            return ShmCanBus(channel=channel)
        except Exception as exc:
            LOGGER.warning("Could not open ShmCanBus (%s), falling back to in-memory virtual bus.", exc)
            return can.Bus(interface="virtual", channel=channel)

    try:
        return can.Bus(interface="socketcan", channel=channel)
    except (can.CanError, OSError, ValueError):
        LOGGER.info("SocketCAN unavailable, falling back to ShmCanBus '%s'.", channel)
        return ShmCanBus(channel=channel)
