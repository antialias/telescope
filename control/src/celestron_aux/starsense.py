"""The StarSense AutoAlign camera (the original one, at 0xB4): status and star lists.

The command ids, the capture sequence and the meaning of the replies come from
the celestron-aux toolkit (github.com/platini2/celestron-aux: catalog.py,
decoding.py, starsense.py), which names community reverse engineering as its
source. None of this has been run against our camera yet. `capture` therefore
keeps everything that came back, so a first run shows what the camera really
says.

Nothing here writes the camera's stored centre calibration (command 0x3E), and
nothing here moves the mount.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .client import AuxClient, AuxProtocolError
from .packet import Command, Device, Packet, Star, StarFrame

SENSOR_PIXELS = (1280, 960)  # celestron-aux starsense.py, SENSOR_RESOLUTION
# The data celestron-aux sends with the reset. 0x03E8 is 1000: perhaps the
# exposure in milliseconds, which is our guess and not the toolkit's claim.
RESET_DATA = bytes.fromhex("03e800")
START_DATA = b"\x00"
STATUS_NAMES = {1: "error", 3: "ready", 9: "finished"}  # celestron-aux decoding.py; a real idle camera answered 1


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


def capture(camera: AuxClient, *, pause: float = 4.0) -> Capture:
    """Ask for one exposure and its star list, the way celestron-aux does: reset, start, fetch.

    celestron-aux waits four seconds after each step, and so does this, while
    listening. The commands are sent without requiring a reply, because the
    replies are not known yet; whatever arrives is in `events`.
    """
    began = time.monotonic()
    events: list[tuple[float, Packet | StarFrame]] = []
    stars: list[Star] | None = None

    def gather(seconds: float) -> None:
        nonlocal stars
        for frame in camera.listen(seconds):
            events.append((time.monotonic() - began, frame))
            if isinstance(frame, StarFrame):
                stars = frame.stars()

    steps = (
        (Command.SS_RESET_CAPTURE, RESET_DATA),
        (Command.SS_START_CAPTURE, START_DATA),
        (Command.SS_GET_CAPTURE_DATA, b""),
    )
    for command, data in steps:
        camera.send(Device.STARSENSE_CAMERA, command, data)
        gather(pause)
    return Capture(events, stars)
