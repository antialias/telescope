"""Celestron AUX packets and StarSense star lists: framing, checksum and a stream parser.

The packet format is taken from INDI's indi-celestronaux driver (auxproto.cpp):

    0x3B  length  source  destination  command  data...  checksum

`length` counts source, destination, command and data. The checksum is the
two's complement of the sum of every byte from `length` to the last data byte.

The StarSense camera returns the stars of an exposure in a second kind of
frame, described by the celestron-aux toolkit (github.com/platini2/celestron-aux,
protocol/packets.py and starsense.py), which carries no addresses:

    0x3C  length (4 bytes, big-endian)  payload...  checksum

Every 0x3B inside the length and payload is sent as 3B 02 02, which no packet
can begin with. The checksum covers the length and payload before that
escaping. The payload is 8 bytes per star: x and y on the sensor in pixels as
two little-endian 32-bit floats. A record of eight zero bytes is not a star.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

PREAMBLE = 0x3B
STAR_PREAMBLE = 0x3C
MAX_STAR_PAYLOAD = 0xFFFF  # the toolkit's limit; a recorded list of 100 stars is 800 bytes
_HEADER = 3  # source, destination, command
_PREAMBLES = bytes([PREAMBLE, STAR_PREAMBLE])
_ESCAPED_PREAMBLE = bytes([PREAMBLE, 0x02, 0x02])
_STAR_LENGTH = 4
_STAR_RECORD = struct.Struct("<ff")


class Device(IntEnum):
    """Addresses on the AUX bus (indi-celestronaux auxproto.h, AUXTargets; StarSense ones from celestron-aux)."""

    MAIN_BOARD = 0x01
    HAND_CONTROL = 0x04
    HAND_CONTROL_PLUS = 0x0D
    STARSENSE_HAND_CONTROL = 0x0E
    AZM = 0x10
    ALT = 0x11
    FOCUSER = 0x12
    APP = 0x20
    GPS = 0xB0
    STARSENSE_CAMERA = 0xB4
    WIFI = 0xB5
    BATTERY = 0xB6
    CHARGE_PORT = 0xB7
    LIGHTS = 0xBF


class Command(IntEnum):
    """Command ids (indi-celestronaux auxproto.h, AUXCommands; SS_ ones from celestron-aux)."""

    MC_GET_POSITION = 0x01
    MC_GOTO_FAST = 0x02
    MC_GET_MODEL = 0x05
    MC_SLEW_DONE = 0x13
    MC_GOTO_SLOW = 0x17
    MC_MOVE_POS = 0x24
    MC_MOVE_NEG = 0x25
    GET_VOLTAGE = 0x10  # to the battery controller only
    SS_GET_ALIGN_CENTER = 0x3F  # the SS_ commands go to the StarSense camera only
    SS_RESET_CAPTURE = 0x90
    SS_GET_STATUS = 0x91
    SS_GET_CAPTURE_DATA = 0x92
    SS_START_CAPTURE = 0x94
    GET_VER = 0xFE


def checksum(body: bytes) -> int:
    return -sum(body) & 0xFF


@dataclass(frozen=True)
class Packet:
    source: int
    destination: int
    command: int
    data: bytes = b""

    def encode(self) -> bytes:
        body = bytes([len(self.data) + _HEADER, self.source, self.destination, self.command]) + self.data
        return bytes([PREAMBLE]) + body + bytes([checksum(body)])


@dataclass(frozen=True)
class Star:
    """A star's place on the StarSense sensor, in pixels."""

    x: float
    y: float


@dataclass(frozen=True)
class StarFrame:
    """A star list as the StarSense camera puts it on the bus."""

    payload: bytes

    def stars(self) -> list[Star]:
        size = _STAR_RECORD.size
        records = (self.payload[start : start + size] for start in range(0, len(self.payload) - size + 1, size))
        return [Star(*_STAR_RECORD.unpack(record)) for record in records if any(record)]

    def encode(self) -> bytes:
        body = len(self.payload).to_bytes(_STAR_LENGTH, "big") + self.payload
        escaped = body.replace(bytes([PREAMBLE]), _ESCAPED_PREAMBLE)
        return bytes([STAR_PREAMBLE]) + escaped + bytes([checksum(body)])

    @classmethod
    def of(cls, stars: list[Star]) -> StarFrame:
        return cls(b"".join(_STAR_RECORD.pack(star.x, star.y) for star in stars))


class _NotAFrame(Exception):
    """The bytes at the head of the buffer do not begin a frame."""


class Parser:
    """Turns a byte stream into packets and star lists, in the order they arrived.

    Bytes that are not part of a frame with a correct checksum are dropped
    one at a time until the stream lines up again; `dropped` counts them.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.dropped = 0

    def feed(self, chunk: bytes) -> list[Packet | StarFrame]:
        self._buffer += chunk
        frames: list[Packet | StarFrame] = []
        while self._buffer:
            if self._buffer[0] not in _PREAMBLES:
                self._drop(next((i for i, byte in enumerate(self._buffer) if byte in _PREAMBLES), len(self._buffer)))
                continue
            try:
                taken = self._packet() if self._buffer[0] == PREAMBLE else self._star_frame()
            except _NotAFrame:
                self._drop(1)
                continue
            if taken is None:  # the frame at the head is not complete yet
                break
            frame, size = taken
            frames.append(frame)
            del self._buffer[:size]
        return frames

    def _drop(self, count: int) -> None:
        self.dropped += count
        del self._buffer[:count]

    def _packet(self) -> tuple[Packet, int] | None:
        if len(self._buffer) < 2:
            return None
        length = self._buffer[1]
        end = length + 3  # preamble, length byte, body, checksum
        if length < _HEADER:
            raise _NotAFrame
        if len(self._buffer) < end:
            return None
        body = bytes(self._buffer[1 : end - 1])
        if checksum(body) != self._buffer[end - 1]:
            raise _NotAFrame
        return Packet(body[1], body[2], body[3], body[4:]), end

    def _star_frame(self) -> tuple[StarFrame, int] | None:
        header = self._unescaped(1, _STAR_LENGTH)
        if header is None:
            return None
        length_bytes, position = header
        length = int.from_bytes(length_bytes, "big")
        if length > MAX_STAR_PAYLOAD:
            raise _NotAFrame
        body = self._unescaped(position, length)
        if body is None:
            return None
        payload, position = body
        if position >= len(self._buffer):
            return None
        if checksum(length_bytes + payload) != self._buffer[position]:
            raise _NotAFrame
        return StarFrame(payload), position + 1

    def _unescaped(self, start: int, count: int) -> tuple[bytes, int] | None:
        """Read `count` bytes from `start`, undoing the escaping; None when more bytes are needed."""
        out = bytearray()
        position = start
        while len(out) < count:
            if position >= len(self._buffer):
                return None
            byte = self._buffer[position]
            if byte == PREAMBLE:
                escape = bytes(self._buffer[position : position + len(_ESCAPED_PREAMBLE)])
                if escape != _ESCAPED_PREAMBLE[: len(escape)]:
                    raise _NotAFrame  # a bare 0x3B: a packet begins here, so this was not a star list
                if len(escape) < len(_ESCAPED_PREAMBLE):
                    return None
                position += len(_ESCAPED_PREAMBLE)
            else:
                position += 1
            out.append(byte)
        return bytes(out), position
