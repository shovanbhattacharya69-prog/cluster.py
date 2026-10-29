"""
Hardware abstraction layer for virtual CAN networking.

Uses native Linux SocketCAN ('vcan0') when available. On Windows and platforms
without kernel CAN drivers, it provides a shared-memory ring buffer (ShmCanBus)
so separate processes (e.g. ECU node + instrument cluster) can exchange raw
CAN frames without network sockets or third-party drivers.
"""

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

log = logging.getLogger("can_bus")

# IPC ring buffer layout:
# Header: magic (8B) | capacity (4B) | slot_size (4B) | write_seq (8B) -> 24B
# Slot:   seq (8B) | arb_id (4B) | dlc (1B) | flags (1B) | reserved (2B) | timestamp (8B) | data (8B) -> 32B
HEADER_STRUCT = struct.Struct("!8sIIQ")
SLOT_STRUCT = struct.Struct("!QIBBHd8s")
RING_MAGIC = b"VCANRING"
DEFAULT_CAPACITY = 2048


class ShmCanBus(can.BusABC):
    """
    Lightweight multi-process CAN bus implemented over an mmap-backed ring buffer.
    Allows concurrent SIL processes to produce and consume frames locally.
    """

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
        self.channel_info = f"ShmCanBus:{channel}"

        # Map buffer file into temp directory
        slug = "".join(c if c.isalnum() else "_" for c in str(channel))
        self.file_path = os.path.join(tempfile.gettempdir(), f"vcan_{slug}.ipc")

        file_size = HEADER_STRUCT.size + self.capacity * SLOT_STRUCT.size
        if not os.path.exists(self.file_path):
            try:
                with open(self.file_path, "x+b") as f:
                    f.write(HEADER_STRUCT.pack(RING_MAGIC, self.capacity, SLOT_STRUCT.size, 0))
                    f.write(b"\x00" * (self.capacity * SLOT_STRUCT.size))
                    f.flush()
            except FileExistsError:
                pass

        self._file = open(self.file_path, "r+b")
        self._mmap = mmap.mmap(self._file.fileno(), file_size)

        _, _, _, head_seq = HEADER_STRUCT.unpack_from(self._mmap, 0)
        self._read_seq = head_seq
        self._is_open = True

    def send(self, msg: can.Message, timeout: Optional[float] = None) -> None:
        if not self._is_open:
            raise can.CanOperationError("Cannot write to closed CAN interface")

        payload = bytes(msg.data)[:8].ljust(8, b"\x00")
        dlc = min(len(msg.data), 8)
        flags = (1 if msg.is_extended_id else 0) | ((1 if msg.is_error_frame else 0) << 1)
        ts = msg.timestamp or time.time()

        _, _, _, write_seq = HEADER_STRUCT.unpack_from(self._mmap, 0)
        next_seq = write_seq + 1
        slot_idx = next_seq % self.capacity
        slot_offset = HEADER_STRUCT.size + slot_idx * SLOT_STRUCT.size

        slot_bytes = SLOT_STRUCT.pack(
            next_seq,
            msg.arbitration_id,
            dlc,
            flags,
            0,
            ts,
            payload,
        )
        self._mmap[slot_offset : slot_offset + SLOT_STRUCT.size] = slot_bytes
        struct.pack_into("!Q", self._mmap, 16, next_seq)
        self._mmap.flush()

    def _recv_internal(
        self, timeout: Optional[float]
    ) -> tuple[Optional[can.Message], bool]:
        if not self._is_open:
            raise can.CanOperationError("Cannot read from closed CAN interface")

        start = time.monotonic()
        while True:
            write_seq = struct.unpack_from("!Q", self._mmap, 16)[0]

            if write_seq > self._read_seq:
                # Catch up if reader lagged behind buffer wrap-around
                if write_seq - self._read_seq > self.capacity:
                    self._read_seq = write_seq - self.capacity

                target_seq = self._read_seq + 1
                slot_idx = target_seq % self.capacity
                slot_offset = HEADER_STRUCT.size + slot_idx * SLOT_STRUCT.size
                raw = self._mmap[slot_offset : slot_offset + SLOT_STRUCT.size]
                seq, arb_id, dlc, flags, _, ts, payload = SLOT_STRUCT.unpack(raw)

                if seq == target_seq:
                    self._read_seq = target_seq
                    msg = can.Message(
                        arbitration_id=arb_id,
                        data=payload[:dlc],
                        is_extended_id=bool(flags & 1),
                        is_error_frame=bool(flags & 2),
                        timestamp=ts,
                        channel=self.channel_info,
                    )
                    return msg, False

                self._read_seq = write_seq

            if timeout is not None and (time.monotonic() - start) >= timeout:
                return None, False

            time.sleep(0.002)

    def shutdown(self) -> None:
        if self._is_open:
            self._is_open = False
            try:
                self._mmap.close()
                self._file.close()
            except OSError:
                pass
        super().shutdown()


def create_bus(channel: str = "vcan0") -> can.BusABC:
    """
    Open the primary CAN interface for the platform.
    Uses SocketCAN on Linux when available, otherwise falls back to ShmCanBus.
    """
    if platform.system() == "Windows":
        try:
            return ShmCanBus(channel=channel)
        except Exception as exc:
            log.warning("Shared-memory bus failed (%s), falling back to in-memory virtual bus", exc)
            return can.Bus(interface="virtual", channel=channel)

    try:
        return can.Bus(interface="socketcan", channel=channel)
    except (can.CanError, OSError, ValueError):
        log.info("SocketCAN unavailable on %s; using shared-memory backend", channel)
        return ShmCanBus(channel=channel)
