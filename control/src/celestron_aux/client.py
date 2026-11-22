"""A client for a Celestron mount's AUX bus over its WiFi bridge (TCP 2000).

The bridge passes AUX packets through unchanged. The addressed device replies
with the same command id, source and destination swapped. The simulator also
echoes everything we send; our mount's WiFi board was seen not to. A device
that is not on the bus does not reply.
A star list from the StarSense camera has no address; whatever arrives is kept
for `star_frame`.
"""

from __future__ import annotations

import socket
import time
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from types import TracebackType
from typing import Self

from .packet import Command, Device, Packet, Parser, StarFrame

DEFAULT_PORT = 2000
DISCOVERY_PORT = 55555
DIRECT_CONNECT_HOST = "1.2.3.4"  # the mount's address on its own hotspot
STEPS_PER_REVOLUTION = 1 << 24
MAX_MOVE_RATE = 9

_CHARGE_STATES = {0: "discharging", 1: "charging", 2: "full"}
_CHARGE_LEVELS = {0: "low", 1: "medium", 2: "high"}


class AuxTimeout(TimeoutError):
    """The addressed device did not reply in time."""


class AuxProtocolError(Exception):
    """A reply arrived that does not have the expected shape."""


@dataclass(frozen=True)
class Battery:
    state: str
    level: str
    volts: float


def discover(timeout: float = 15.0, port: int = DISCOVERY_PORT) -> str:
    """Wait for a mount's WiFi board to announce itself, and return its address.

    The board broadcasts a UDP datagram to this port every few seconds. The
    payload differs between generations of the board, so only the sender's
    address is used; anything else that broadcasts here would be returned too.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("", port))
        listener.settimeout(timeout)
        try:
            _, (host, _) = listener.recvfrom(1024)
        except TimeoutError:
            raise AuxTimeout(f"nothing announced itself on UDP port {port} within {timeout:g} s") from None
        return host


class AuxClient:
    def __init__(self, host: str, port: int = DEFAULT_PORT, *, timeout: float = 1.0) -> None:
        self._address = (host, port)
        self._timeout = timeout
        self._socket: socket.socket | None = None
        self._parser = Parser()
        self._star_frames: deque[StarFrame] = deque()

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    def connect(self) -> None:
        self._socket = socket.create_connection(self._address, timeout=self._timeout)
        self._parser = Parser()
        self._star_frames.clear()

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def send(self, destination: int, command: int, data: bytes = b"") -> None:
        """Send one command without waiting for anything."""
        if self._socket is None:
            raise ConnectionError("not connected")
        self._socket.sendall(Packet(Device.APP, destination, command, data).encode())

    def request(self, destination: int, command: int, data: bytes = b"") -> Packet:
        """Send one command and return the reply addressed back to us."""
        self.send(destination, command, data)
        deadline = time.monotonic() + self._timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AuxTimeout(f"no reply from device 0x{destination:02x} to command 0x{command:02x}")
            for packet in self._receive(remaining):
                if (packet.source, packet.destination, packet.command) == (destination, Device.APP, command):
                    return packet

    def listen(self, seconds: float) -> Iterator[Packet | StarFrame]:
        """Yield everything that arrives in the next `seconds`: echoes, replies, other traffic, star lists."""
        deadline = time.monotonic() + seconds
        while (remaining := deadline - time.monotonic()) > 0:
            packets = self._receive(remaining)
            while self._star_frames:
                yield self._star_frames.popleft()
            yield from packets

    def discard_incomplete(self) -> int:
        """Drop a frame that stopped arriving part way (see `Parser.discard`); returns the bytes dropped."""
        return self._parser.discard()

    def star_frame(self, timeout: float) -> StarFrame:
        """The oldest star list not yet taken, waiting up to `timeout` seconds for one."""
        deadline = time.monotonic() + timeout
        while not self._star_frames:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AuxTimeout(f"no star list arrived within {timeout:g} s")
            self._receive(remaining)
        return self._star_frames.popleft()

    def _receive(self, timeout: float) -> list[Packet]:
        """Read once. Star lists go to the queue; the packets are returned. Empty when nothing came."""
        if self._socket is None:
            raise ConnectionError("not connected")
        self._socket.settimeout(timeout)
        try:
            chunk = self._socket.recv(4096)
        except TimeoutError:
            return []
        if not chunk:
            raise ConnectionError("the mount closed the connection")
        packets: list[Packet] = []
        for frame in self._parser.feed(chunk):
            if isinstance(frame, StarFrame):
                self._star_frames.append(frame)
            else:
                packets.append(frame)
        return packets

    def version(self, device: int) -> str:
        data = self.request(device, Command.GET_VER).data
        if len(data) == 2:
            return f"{data[0]}.{data[1]:02d}"
        if len(data) == 4:
            return f"{data[0]}.{data[1]:02d}.{int.from_bytes(data[2:], 'big')}"
        raise AuxProtocolError(f"version reply from 0x{device:02x} has {len(data)} bytes: {data.hex()}")

    def model(self) -> int:
        return int.from_bytes(self._reply(Device.AZM, Command.MC_GET_MODEL, size=2), "big")

    def position(self, axis: Device) -> float:
        """The axis encoder as degrees in [0, 360). Zero is wherever the axis was last told zero is."""
        steps = int.from_bytes(self._reply(axis, Command.MC_GET_POSITION, size=3), "big")
        return steps * 360.0 / STEPS_PER_REVOLUTION

    def slew_done(self, axis: Device) -> bool:
        return self._reply(axis, Command.MC_SLEW_DONE, size=1) == b"\xff"

    def battery(self) -> Battery:
        data = self._reply(Device.BATTERY, Command.GET_VOLTAGE, size=6)
        state, level = data[0], data[1]
        if state not in _CHARGE_STATES or level not in _CHARGE_LEVELS:
            raise AuxProtocolError(f"unknown battery state or level in {data.hex()}")
        return Battery(_CHARGE_STATES[state], _CHARGE_LEVELS[level], int.from_bytes(data[2:], "big") / 1e6)

    def goto(self, axis: Device, degrees: float, *, slow: bool = False) -> None:
        """Start a slew of one axis to an encoder angle. Returns at once; poll `slew_done`."""
        steps = round(degrees % 360.0 * STEPS_PER_REVOLUTION / 360.0) % STEPS_PER_REVOLUTION
        command = Command.MC_GOTO_SLOW if slow else Command.MC_GOTO_FAST
        self._reply(axis, command, steps.to_bytes(3, "big"), size=0)

    def move(self, axis: Device, rate: int) -> None:
        """Move one axis at a fixed rate from -9 to 9. Zero stops it."""
        if not -MAX_MOVE_RATE <= rate <= MAX_MOVE_RATE:
            raise ValueError(f"rate must be from -{MAX_MOVE_RATE} to {MAX_MOVE_RATE}, got {rate}")
        command = Command.MC_MOVE_NEG if rate < 0 else Command.MC_MOVE_POS
        self._reply(axis, command, bytes([abs(rate)]), size=0)

    def stop(self) -> None:
        for axis in (Device.AZM, Device.ALT):
            self.move(axis, 0)

    def _reply(self, destination: int, command: int, data: bytes = b"", *, size: int) -> bytes:
        reply = self.request(destination, command, data).data
        if len(reply) != size:
            raise AuxProtocolError(
                f"reply to command 0x{command:02x} from 0x{destination:02x} has {len(reply)} bytes, expected {size}: {reply.hex()}"
            )
        return reply
