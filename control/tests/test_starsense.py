"""The camera commands against a stand-in for the mount's WiFi board with a StarSense camera on it.

The stand-in answers the way our camera was seen to on 2026-11-22: no echo, a
reply to each command, and the star list after the fetch's reply. It can lose
a byte from the list, as the real WiFi board sometimes does. This shows the
client handles that exchange. It is not the real camera.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Generator
from contextlib import contextmanager

import pytest

from celestron_aux import AuxClient, AuxProtocolError, AuxTimeout, Command, Device, Packet, Parser, Star, StarFrame, starsense

STARS = [Star(269.0, 800.25), Star(1025.8515625, 12.5), Star(640.0, 480.0)]  # the second holds a 0x3B byte
VERSION = bytes.fromhex("0102341f")  # what our camera answers
FOUND = bytes([9, len(STARS)])


def capture(camera: AuxClient, exposure: int = starsense.TOOLKIT_EXPOSURE) -> starsense.Capture:
    """A capture with waits short enough for a stand-in that answers at once."""
    return starsense.capture(camera, exposure=exposure, reset_wait=0.5, exposure_wait=0.5, fetch_wait=0.5, list_wait=0.3)


class StandIn:
    """`broken_lists` lists arrive a byte short before an intact one; `deaf_to` is a command it never answers."""

    def __init__(self, *, broken_lists: int = 0, stars: list[Star] | None = None, deaf_to: int | None = None) -> None:
        self.broken_lists = broken_lists
        self.stars = STARS if stars is None else stars
        self.deaf_to = deaf_to
        self.asked: list[tuple[int, bytes]] = []

    def answers(self, packet: Packet) -> bytes:
        def reply(data: bytes = b"") -> bytes:
            return Packet(Device.STARSENSE_CAMERA, packet.source, packet.command, data).encode()

        self.asked.append((packet.command, packet.data))
        found = bytes([9, len(self.stars)]) if self.stars else bytes([1, 0])
        if packet.destination != Device.STARSENSE_CAMERA or packet.command == self.deaf_to:
            return b""
        match packet.command:
            case Command.GET_VER:
                return reply(VERSION)
            case Command.SS_GET_STATUS:
                return reply(bytes([1, 0]))
            case Command.SS_GET_ALIGN_CENTER:
                return reply((640).to_bytes(4, "little") + (480).to_bytes(4, "little"))
            case Command.SS_RESET_CAPTURE:
                return reply()
            case Command.SS_START_CAPTURE:
                return reply(found)
            case Command.SS_GET_CAPTURE_DATA:
                if not self.stars:
                    return reply(found)
                star_list = StarFrame.of(self.stars).encode()
                if self.broken_lists:
                    self.broken_lists -= 1
                    star_list = star_list[:20] + star_list[21:]
                return reply(found) + star_list  # one write, so reply and list can arrive in one read
            case _:
                return b""

    def serve(self, listener: socket.socket) -> None:
        connection, _ = listener.accept()
        parser = Parser()
        with connection:
            while chunk := connection.recv(4096):
                for frame in parser.feed(chunk):
                    assert isinstance(frame, Packet)
                    connection.sendall(self.answers(frame))


@contextmanager
def connected(stand_in: StandIn) -> Generator[AuxClient]:
    with socket.create_server(("127.0.0.1", 0)) as listener:
        thread = threading.Thread(target=stand_in.serve, args=(listener,), daemon=True)
        thread.start()
        with AuxClient("127.0.0.1", listener.getsockname()[1], timeout=0.5) as client:
            yield client
        thread.join(timeout=5)


def test_version_status_and_centre() -> None:
    with connected(StandIn()) as camera:
        assert camera.version(Device.STARSENSE_CAMERA) == "1.02.13343"
        assert starsense.status(camera) == starsense.CameraStatus(1, 0)
        assert starsense.align_center(camera) == (640, 480)


def test_capture_returns_the_stars_and_everything_that_was_said() -> None:
    assert b"\x3b\x02\x02" in StarFrame.of(STARS).encode()  # the list on the wire holds an escaped byte
    stand_in = StandIn()
    with connected(stand_in) as camera:
        result = capture(camera, exposure=100)
    assert result.stars == STARS
    assert (result.status, result.fetches) == (starsense.CameraStatus(9, 3), 1)
    assert stand_in.asked == [
        (Command.SS_RESET_CAPTURE, bytes.fromhex("006400")),
        (Command.SS_START_CAPTURE, b"\x00"),
        (Command.SS_GET_CAPTURE_DATA, b""),
    ]
    frames = [frame for _, frame in result.events]
    assert frames == [
        Packet(Device.STARSENSE_CAMERA, Device.APP, Command.SS_RESET_CAPTURE),
        Packet(Device.STARSENSE_CAMERA, Device.APP, Command.SS_START_CAPTURE, FOUND),
        StarFrame.of(STARS),
        Packet(Device.STARSENSE_CAMERA, Device.APP, Command.SS_GET_CAPTURE_DATA, FOUND),
    ] or frames == [
        Packet(Device.STARSENSE_CAMERA, Device.APP, Command.SS_RESET_CAPTURE),
        Packet(Device.STARSENSE_CAMERA, Device.APP, Command.SS_START_CAPTURE, FOUND),
        Packet(Device.STARSENSE_CAMERA, Device.APP, Command.SS_GET_CAPTURE_DATA, FOUND),
        StarFrame.of(STARS),
    ]


def test_the_toolkits_exposure_is_the_default() -> None:
    stand_in = StandIn()
    with connected(stand_in) as camera:
        capture(camera)
    assert stand_in.asked[0] == (Command.SS_RESET_CAPTURE, bytes.fromhex("03e800"))


def test_an_exposure_that_finds_nothing_returns_no_stars_and_asks_once() -> None:
    stand_in = StandIn(stars=[])
    with connected(stand_in) as camera:
        result = capture(camera)
    assert (result.status, result.stars, result.fetches) == (starsense.CameraStatus(1, 0), [], 1)


def test_a_list_that_arrives_a_byte_short_is_fetched_again() -> None:
    stand_in = StandIn(broken_lists=2)
    with connected(stand_in) as camera:
        result = capture(camera)
        assert (result.stars, result.fetches) == (STARS, 3)
        assert [command for command, _ in stand_in.asked].count(Command.SS_GET_CAPTURE_DATA) == 3
        # The broken lists are gone from the line: the next request gets its reply.
        assert camera.version(Device.STARSENSE_CAMERA) == "1.02.13343"


def test_capture_gives_up_loudly_when_no_list_arrives_whole() -> None:
    with connected(StandIn(broken_lists=5)) as camera:
        with pytest.raises(AuxProtocolError, match="no intact star list arrived in 3 fetches"):
            capture(camera)
        assert camera.version(Device.STARSENSE_CAMERA) == "1.02.13343"


def test_capture_says_which_step_the_camera_did_not_answer() -> None:
    with connected(StandIn(deaf_to=Command.SS_START_CAPTURE)) as camera:
        with pytest.raises(AuxTimeout, match="0x94"):
            capture(camera)


def test_a_star_list_that_arrives_with_a_reply_is_kept_for_later() -> None:
    with connected(StandIn()) as camera:
        reply = camera.request(Device.STARSENSE_CAMERA, Command.SS_GET_CAPTURE_DATA)
        assert reply.data == FOUND
        assert camera.star_frame(timeout=0.5).stars() == STARS
        with pytest.raises(AuxTimeout):
            camera.star_frame(timeout=0.1)
