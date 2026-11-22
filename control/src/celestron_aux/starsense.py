"""The StarSense AutoAlign camera (the original one, at 0xB4): status and star lists.

The command ids, the capture sequence and the meaning of the replies come from
the celestron-aux toolkit (github.com/platini2/celestron-aux: catalog.py,
decoding.py, starsense.py), which names community reverse engineering as its
source. Run against our camera over the mount's WiFi on 2026-11-22: exposures
were taken and star lists read, and about one list in four arrived a byte
short, which is why `capture` asks again.

Nothing here writes the camera's stored centre calibration (command 0x3E), and
nothing here moves the mount.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .client import AuxClient, AuxProtocolError, AuxTimeout
from .packet import Command, Device, Packet, Star, StarFrame

SENSOR_PIXELS = (1280, 960)  # celestron-aux starsense.py, SENSOR_RESOLUTION
# The reset carries a 16-bit number and a zero byte. celestron-aux sends 1000.
# On our camera the number acts as an exposure setting: in a daylit room 1000
# and 500 found nothing and 100 found about 80 points of a string of lights.
# Its unit is not known.
TOOLKIT_EXPOSURE = 1000
START_DATA = b"\x00"
# As seen on our camera: 1 after power-on and after an exposure that found no stars (celestron-aux
# calls it "Error"), 3 after a reset, 9 after an exposure that found stars.
STATUS_NAMES = {1: "nothing found", 3: "ready", 9: "finished"}


@dataclass(frozen=True)
class CameraStatus:
    code: int
    stars: int

    @property
    def name(self) -> str:
        return STATUS_NAMES.get(self.code, f"unknown ({self.code})")


@dataclass(frozen=True)
class Capture:
    """One exposure: the camera's status and star count, its stars, and everything that came back.

    `fetches` is how many times the list had to be asked for. `events` holds
    every frame with its time in seconds.
    """

    status: CameraStatus
    stars: list[Star]
    fetches: int
    events: list[tuple[float, Packet | StarFrame]]


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


def capture(
    camera: AuxClient,
    *,
    exposure: int = TOOLKIT_EXPOSURE,
    reset_wait: float = 10.0,
    exposure_wait: float = 40.0,
    fetch_wait: float = 15.0,
    list_wait: float = 2.0,
    fetches: int = 3,
) -> Capture:
    """Take one exposure and fetch its star list: reset, start, fetch, each waiting for the camera's reply.

    Seen on our camera: the reset is answered after 1 to 3 s and the start
    after about 10 s, and the camera answers nothing else in between. The
    replies to start and fetch carry a status and the star count. The list
    follows the fetch's reply within half a second. Over the mount's WiFi it
    sometimes arrives a byte short, so its checksum never matches; the same
    list can be fetched again without a new exposure (answered after about
    5 s), and this does so up to `fetches` times before giving up.
    """
    began = time.monotonic()
    events: list[tuple[float, Packet | StarFrame]] = []
    star_list: StarFrame | None = None

    def gather(seconds: float, until: Command | None = None) -> Packet | None:
        """Listen for `seconds`, or until the camera's reply to `until` (or, without one, a star list) has come."""
        nonlocal star_list
        deadline = time.monotonic() + seconds
        reply: Packet | None = None
        while reply is None and (remaining := deadline - time.monotonic()) > 0:
            for frame in camera.listen(min(0.25, remaining)):  # run to its end, so nothing read is left behind
                events.append((time.monotonic() - began, frame))
                if isinstance(frame, StarFrame):
                    star_list = frame
                elif reply is None and (frame.source, frame.command) == (Device.STARSENSE_CAMERA, until):
                    reply = frame
            if until is None and star_list is not None:
                break
        return reply

    def step(command: Command, data: bytes, wait: float) -> Packet:
        camera.send(Device.STARSENSE_CAMERA, command, data)
        reply = gather(wait, until=command)
        if reply is None:
            raise AuxTimeout(f"the camera did not answer command 0x{command:02x} within {wait:g} s")
        return reply

    step(Command.SS_RESET_CAPTURE, exposure.to_bytes(2, "big") + b"\x00", reset_wait)
    step(Command.SS_START_CAPTURE, START_DATA, exposure_wait)
    lost = 0
    for attempt in range(1, fetches + 1):
        star_list = None
        fetched = step(Command.SS_GET_CAPTURE_DATA, b"", fetch_wait).data
        if len(fetched) != 2:
            raise AuxProtocolError(f"reply to the fetch has {len(fetched)} bytes, expected 2: {fetched.hex()}")
        result = CameraStatus(fetched[0], fetched[1])
        if result.stars == 0:
            return Capture(result, [], attempt, events)
        if star_list is None:
            gather(list_wait)
        if star_list is not None:
            return Capture(result, star_list.stars(), attempt, events)
        lost += camera.discard_incomplete()
    raise AuxProtocolError(
        f"the camera reported stars, but no intact star list arrived in {fetches} fetches ({lost} bytes of broken lists dropped)"
    )
