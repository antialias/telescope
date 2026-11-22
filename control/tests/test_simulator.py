"""The client against caux-simulator, a published emulator of the AUX bus.

This shows the client and the emulator agree. It is not evidence about the
real mount.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from collections.abc import Iterator

import pytest

from celestron_aux import AuxClient, AuxTimeout, Command, Device

AXES = (Device.AZM, Device.ALT)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def mount() -> Iterator[AuxClient]:
    simulator = shutil.which("caux-sim")
    assert simulator, "caux-sim is not installed; run `uv sync`"
    port = _free_port()
    process = subprocess.Popen(
        [simulator, "--text", "--perfect", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        client = AuxClient("127.0.0.1", port)
        deadline = time.monotonic() + 15
        while True:
            try:
                client.connect()
                break
            except ConnectionRefusedError:
                assert process.poll() is None, "caux-sim exited before listening"
                assert time.monotonic() < deadline, "caux-sim did not start listening"
                time.sleep(0.1)
        yield client
        client.close()
    finally:
        process.terminate()
        process.wait(timeout=10)


def _wait_until_stopped(mount: AuxClient, seconds: float = 60) -> None:
    deadline = time.monotonic() + seconds
    while not all(mount.slew_done(axis) for axis in AXES):
        assert time.monotonic() < deadline, "slew did not finish"
        time.sleep(0.1)


def test_motor_controllers_report_versions_and_a_model(mount: AuxClient) -> None:
    for axis in AXES:
        major, minor, *_ = mount.version(axis).split(".")
        assert major.isdigit() and minor.isdigit()
    assert 0 < mount.model() <= 0xFFFF


def test_an_absent_device_times_out(mount: AuxClient) -> None:
    with pytest.raises(AuxTimeout):
        mount.request(0x77, Command.GET_VER)


def test_goto_reaches_the_requested_encoder_angles(mount: AuxClient) -> None:
    mount.goto(Device.AZM, 10.0)
    mount.goto(Device.ALT, 5.0)
    _wait_until_stopped(mount)
    assert mount.position(Device.AZM) == pytest.approx(10.0, abs=0.05)
    assert mount.position(Device.ALT) == pytest.approx(5.0, abs=0.05)


def test_move_runs_until_stop(mount: AuxClient) -> None:
    start = mount.position(Device.AZM)
    mount.move(Device.AZM, 7)
    time.sleep(1.0)
    mount.stop()
    time.sleep(0.5)
    stopped_at = mount.position(Device.AZM)
    assert stopped_at != pytest.approx(start, abs=0.01)
    time.sleep(0.5)
    assert mount.position(Device.AZM) == pytest.approx(stopped_at, abs=0.01)


def test_battery_reports_a_plausible_voltage(mount: AuxClient) -> None:
    assert 9.0 < mount.battery().volts < 15.0
