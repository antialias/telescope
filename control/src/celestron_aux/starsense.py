"""The StarSense AutoAlign camera (the original one, at 0xB4): status and star lists.

The command ids, the capture sequence and the meaning of the replies come from
the celestron-aux toolkit (github.com/platini2/celestron-aux: catalog.py,
decoding.py, starsense.py), which names community reverse engineering as its
source. Run against our camera on 2026-11-22 as far as an exposure that found
no stars; a star list from it has not been seen yet, so `capture` keeps
everything that came back.

Nothing here writes the camera's stored centre calibration (command 0x3E), and
nothing here moves the mount.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .client import AuxClient, AuxProtocolError, AuxTimeout
from .packet import Command, Device, Packet, Star, StarFrame

SENSOR_PIXELS = (1280, 960)  # celestron-aux starsense.py, SENSOR_RESOLUTION
# The data celestron-aux sends with the reset. 0x03E8 is 1000: perhaps the
# exposure in milliseconds, which is our guess and not the toolkit's claim.
RESET_DATA = bytes.fromhex("03e800")
START_DATA = b"\x00"
# celestron-aux decoding.py. Our own camera answers 1 when idle after power-on, so 1 is not a fault.
STATUS_NAMES = {1: "error", 3: "ready", 9: "finished"}


@dataclass(frozen=True)
class CameraStatus:
    code: int
    stars: int

    @property
    def name(self) -> str:
        return STATUS_NAMES.get(self.code, f"unknown ({self.code})")


@dataclass(frozen=True)
class Capture:
    """What came back during one capture: every frame with its time in seconds, and the star list if one came."""

    events: list[tuple[float, Packet | StarFrame]]
    stars: list[Star] | None


def status(camera: AuxClient) -> CameraStatus:
    data = camera.request(Device.STARSENSE_CAMERA, Command.SS_GET_STATUS).data
    if len(data) != 2:
        raise AuxProtocolError(f"camera status has {len(data)} bytes, expected 2: {data.hex()}")
    return CameraStatus(data[0], data[1])


def align_center(camera: AuxClient) -> tuple[int, int]:
    """The stored centre calibration: where on the sensor the telescope's own centre falls, in pixels.

    Both are zero on a camera that was never calibrated (seen in a recording of a real one).
    """
    data = camera.request(Device.STARSENSE_CAMERA, Command.SS_GET_ALIGN_CENTER, b"\x00").data
    if len(data) != 8:
        raise AuxProtocolError(f"camera centre has {len(data)} bytes, expected 8: {data.hex()}")
    return int.from_bytes(data[:4], "little"), int.from_bytes(data[4:], "little")


def capture(camera: AuxClient, *, reset_wait: float = 10.0, exposure_wait: float = 40.0, list_wait: float = 5.0) -> Capture:
    """Take one exposure and fetch its star list: reset, start, fetch, each waiting for the camera's reply.

    On our camera (2026-11-22) the reset was answered after about 3 s and the
    start after about 10 s, and the camera answered nothing else in between.
    The reply to the fetch carries the star count; when it is not zero the
    star list is waited for as well. Everything that arrived is in `events`.
    """
    began = time.monotonic()
    events: list[tuple[float, Packet | StarFrame]] = []
    stars: list[Star] | None = None

    def gather(seconds: float, until: Command | None = None) -> Packet | None:
        """Listen for `seconds`, or until the camera's reply to `until` (or, without one, a star list) has come."""
        nonlocal stars
        deadline = time.monotonic() + seconds
        reply: Packet | None = None
        while reply is None and (remaining := deadline - time.monotonic()) > 0:
            for frame in camera.listen(min(0.25, remaining)):  # run to its end, so nothing read is left behind
                events.append((time.monotonic() - began, frame))
                if isinstance(frame, StarFrame):
                    stars = frame.stars()
                elif reply is None and (frame.source, frame.command) == (Device.STARSENSE_CAMERA, until):
                    reply = frame
            if until is None and stars is not None:
                break
        return reply

    def step(command: Command, data: bytes, wait: float) -> Packet:
        camera.send(Device.STARSENSE_CAMERA, command, data)
        reply = gather(wait, until=command)
        if reply is None:
            raise AuxTimeout(f"the camera did not answer command 0x{command:02x} within {wait:g} s")
        return reply

    step(Command.SS_RESET_CAPTURE, RESET_DATA, reset_wait)
    step(Command.SS_START_CAPTURE, START_DATA, exposure_wait)
    fetched = step(Command.SS_GET_CAPTURE_DATA, b"", reset_wait).data
    if len(fetched) != 2:
        raise AuxProtocolError(f"reply to the fetch has {len(fetched)} bytes, expected 2: {fetched.hex()}")
    if fetched[1] and stars is None:
        gather(list_wait)
    return Capture(events, stars)
