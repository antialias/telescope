"""Celestron AUX packets: framing, checksum and a stream parser.

The format is taken from INDI's indi-celestronaux driver (auxproto.cpp):

    0x3B  length  source  destination  command  data...  checksum

`length` counts source, destination, command and data. The checksum is the
two's complement of the sum of every byte from `length` to the last data byte.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

PREAMBLE = 0x3B
_HEADER = 3  # source, destination, command


class Device(IntEnum):
    """Addresses on the AUX bus (indi-celestronaux auxproto.h, AUXTargets)."""

    MAIN_BOARD = 0x01
    HAND_CONTROL = 0x04
    HAND_CONTROL_PLUS = 0x0D
    AZM = 0x10
    ALT = 0x11
    FOCUSER = 0x12
    APP = 0x20
    GPS = 0xB0
    WIFI = 0xB5
    BATTERY = 0xB6
    CHARGE_PORT = 0xB7
    LIGHTS = 0xBF


class Command(IntEnum):
    """Command ids (indi-celestronaux auxproto.h, AUXCommands)."""

    MC_GET_POSITION = 0x01
    MC_GOTO_FAST = 0x02
    MC_GET_MODEL = 0x05
    MC_SLEW_DONE = 0x13
    MC_GOTO_SLOW = 0x17
    MC_MOVE_POS = 0x24
    MC_MOVE_NEG = 0x25
    GET_VOLTAGE = 0x10  # to the battery controller only
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


class Parser:
    """Turns a byte stream into packets.

    Bytes that are not part of a packet with a correct checksum are dropped
    one at a time until the stream lines up again; `dropped` counts them.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.dropped = 0

    def feed(self, chunk: bytes) -> list[Packet]:
        self._buffer += chunk
        packets: list[Packet] = []
        while True:
            start = self._buffer.find(PREAMBLE)
            if start < 0:
                self.dropped += len(self._buffer)
                self._buffer.clear()
                return packets
            self.dropped += start
            del self._buffer[:start]
            if len(self._buffer) < 2:
                return packets
            length = self._buffer[1]
            end = length + 3  # preamble, length byte, body, checksum
            if length < _HEADER:
                self._drop_one()
                continue
            if len(self._buffer) < end:
                return packets
            body = bytes(self._buffer[1 : end - 1])
            if checksum(body) != self._buffer[end - 1]:
                self._drop_one()
                continue
            packets.append(Packet(body[1], body[2], body[3], body[4:]))
            del self._buffer[:end]

    def _drop_one(self) -> None:
        self.dropped += 1
        del self._buffer[:1]
