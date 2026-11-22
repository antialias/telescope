"""Probe a mount's AUX bus. Nothing here moves the mount.

    python -m celestron_aux [host] [--port 2000]     what answers on the bus, positions, battery
    python -m celestron_aux [host] --camera          the StarSense camera's version, status and stored centre
    python -m celestron_aux [host] --listen 60       everything on the bus for 60 seconds; sends nothing
    python -m celestron_aux [host] --capture         one exposure: everything the camera says, and its star list
    python -m celestron_aux --discover

Without a host it tries the mount's address on its own hotspot. `--discover`
waits for a mount on this network to announce itself. The first two only read
and `--listen` sends nothing at all. `--capture` makes the camera take an
exposure.
"""

from __future__ import annotations

import argparse
import time

from . import starsense
from .client import DEFAULT_PORT, DIRECT_CONNECT_HOST, AuxClient, AuxTimeout, discover
from .packet import Device, Packet, StarFrame

MODELS = {0x1687: "NexStar Evolution"}  # indi-celestronaux celestronaux.h, MountVersion


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("host", nargs="?", default=DIRECT_CONNECT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--discover", action="store_true", help="find the mount on this network first")
    what = parser.add_mutually_exclusive_group()
    what.add_argument("--camera", action="store_true", help="read the StarSense camera's version, status and centre")
    what.add_argument("--listen", type=float, metavar="SECONDS", help="print everything on the bus, send nothing")
    what.add_argument("--capture", action="store_true", help="have the StarSense camera take one exposure")
    args = parser.parse_args()

    host = args.host
    if args.discover:
        host = discover()
        print(f"a mount announced itself at {host}")

    with AuxClient(host, args.port) as mount:
        if args.camera:
            _camera(mount)
        elif args.listen is not None:
            began = time.monotonic()
            for frame in mount.listen(args.listen):
                _show(time.monotonic() - began, frame)
        elif args.capture:
            _capture(mount)
        else:
            _bus(mount)


def _bus(mount: AuxClient) -> None:
    for device in Device:
        if device is Device.APP:
            continue
        try:
            print(f"{device.name:22} 0x{device:02x}  version {mount.version(device)}")
        except AuxTimeout:
            print(f"{device.name:22} 0x{device:02x}  no reply")
    model = mount.model()
    print(f"model 0x{model:04x} ({MODELS.get(model, 'not in our table')})")
    print(f"azimuth encoder  {mount.position(Device.AZM):9.4f} deg, slewing: {not mount.slew_done(Device.AZM)}")
    print(f"altitude encoder {mount.position(Device.ALT):9.4f} deg, slewing: {not mount.slew_done(Device.ALT)}")
    try:
        battery = mount.battery()
        print(f"battery {battery.volts:.2f} V, {battery.level}, {battery.state}")
    except AuxTimeout:
        print("battery: no reply")


def _camera(mount: AuxClient) -> None:
    print(f"camera version {mount.version(Device.STARSENSE_CAMERA)}")
    status = starsense.status(mount)
    print(f"status {status.name}, {status.stars} stars")
    x, y = starsense.align_center(mount)
    print(f"stored centre x {x}, y {y} (sensor is {starsense.SENSOR_PIXELS[0]} by {starsense.SENSOR_PIXELS[1]})")


def _capture(mount: AuxClient) -> None:
    result = starsense.capture(mount)
    for seconds, frame in result.events:
        _show(seconds, frame)
    if result.stars is None:
        print("no star list arrived")


def _show(seconds: float, frame: Packet | StarFrame) -> None:
    if isinstance(frame, Packet):
        print(f"{seconds:7.2f}s  {frame.source:02x}->{frame.destination:02x} cmd {frame.command:02x} data {frame.data.hex(' ')}", flush=True)
        return
    stars = frame.stars()
    print(f"{seconds:7.2f}s  star list, {len(frame.payload)} bytes, {len(stars)} stars (x y in pixels):")
    for star in stars:
        print(f"            {star.x:8.2f} {star.y:8.2f}")
    print(end="", flush=True)


if __name__ == "__main__":
    main()
