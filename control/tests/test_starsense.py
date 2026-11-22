"""The camera commands against a stand-in for the mount's WiFi bridge with a StarSense camera on it.

The stand-in echoes what it is sent, as the real bridge does, and answers as
the celestron-aux toolkit describes the camera. This shows our client and that
description agree. It is not evidence about the real camera.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator

import pytest

from celestron_aux import AuxClient, AuxTimeout, Command, Device, Packet, Parser, Star, StarFrame, starsense

STARS = [Star(269.0, 800.25), Star(1025.8515625, 12.5), Star(640.0, 480.0)]  # the second holds a 0x3B byte
VERSION = bytes.fromhex("0102341f")  # what a real camera answered in the toolkit's recording


def _answers(packet: Packet) -> bytes:
    def reply(data: bytes = b"") -> bytes:
        return Packet(Device.STARSENSE_CAMERA, packet.source, packet.command, data).encode()

    if packet.destination != Device.STARSENSE_CAMERA:
        return b""
    match packet.command:
        case Command.GET_VER:
            return reply(VERSION)
        case Command.SS_GET_STATUS:
            return reply(bytes([3, 0]))
        case Command.SS_GET_ALIGN_CENTER:
            return reply((652).to_bytes(4, "little") + (471).to_bytes(4, "little"))
        case Command.SS_RESET_CAPTURE:
            return reply()
        case Command.SS_START_CAPTURE:
            return reply(bytes([3, len(STARS)]))
        case Command.SS_GET_CAPTURE_DATA:
            # The reply and the star list leave in one write, so they can arrive in one read.
            return reply(bytes([9, len(STARS)])) + StarFrame.of(STARS).encode()
        case _:
            return b""


def _serve(listener: socket.socket) -> None:
    connection, _ = listener.accept()
    parser = Parser()
    with connection:
        while chunk := connection.recv(4096):
            for frame in parser.feed(chunk):
                assert isinstance(frame, Packet)
                connection.sendall(frame.encode() + _answers(frame))


@pytest.fixture
def camera() -> Iterator[AuxClient]:
    with socket.create_server(("127.0.0.1", 0)) as listener:
        thread = threading.Thread(target=_serve, args=(listener,), daemon=True)
        thread.start()
        with AuxClient("127.0.0.1", listener.getsockname()[1], timeout=0.5) as client:
            yield client
        thread.join(timeout=5)


def test_version_status_and_centre(camera: AuxClient) -> None:
    assert camera.version(Device.STARSENSE_CAMERA) == "1.02.13343"
    assert starsense.status(camera) == starsense.CameraStatus(3, 0)
    assert starsense.status(camera).name == "ready"
    assert starsense.align_center(camera) == (652, 471)


def test_capture_returns_the_stars_and_everything_that_was_said(camera: AuxClient) -> None:
    assert b"\x3b\x02\x02" in StarFrame.of(STARS).encode()  # the list on the wire holds an escaped byte
    result = starsense.capture(camera, reset_wait=0.5, exposure_wait=0.5, list_wait=0.5)
    assert result.stars == STARS
    packets = [frame for _, frame in result.events if isinstance(frame, Packet)]
    answered = [(p.command, p.data) for p in packets if p.source == Device.STARSENSE_CAMERA]
    assert answered == [
        (Command.SS_RESET_CAPTURE, b""),
        (Command.SS_START_CAPTURE, bytes([3, 3])),
        (Command.SS_GET_CAPTURE_DATA, bytes([9, 3])),
    ]
    assert [frame for _, frame in result.events if isinstance(frame, StarFrame)] == [StarFrame.of(STARS)]


def test_a_star_list_that_arrives_with_a_reply_is_kept_for_later(camera: AuxClient) -> None:
    reply = camera.request(Device.STARSENSE_CAMERA, Command.SS_GET_CAPTURE_DATA)
    assert reply.data == bytes([9, 3])
    assert camera.star_frame(timeout=0.5).stars() == STARS
    with pytest.raises(AuxTimeout):
        camera.star_frame(timeout=0.1)


def test_capture_says_which_step_the_camera_did_not_answer() -> None:
    """A camera that takes the reset and then goes quiet: the failure names the start command."""

    def serve(listener: socket.socket) -> None:
        connection, _ = listener.accept()
        parser = Parser()
        with connection:
            while chunk := connection.recv(4096):
                for frame in parser.feed(chunk):
                    assert isinstance(frame, Packet)
                    if frame.command == Command.SS_RESET_CAPTURE:
                        connection.sendall(Packet(Device.STARSENSE_CAMERA, frame.source, frame.command).encode())

    with socket.create_server(("127.0.0.1", 0)) as listener:
        thread = threading.Thread(target=serve, args=(listener,), daemon=True)
        thread.start()
        with AuxClient("127.0.0.1", listener.getsockname()[1], timeout=0.5) as client:
            with pytest.raises(AuxTimeout, match="0x94"):
                starsense.capture(client, reset_wait=0.5, exposure_wait=0.3)
        thread.join(timeout=5)
