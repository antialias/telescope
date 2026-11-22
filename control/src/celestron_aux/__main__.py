"""Probe a mount's AUX bus. Nothing here moves the mount.

    python -m celestron_aux [host] [--port 2000]     what answers on the bus, positions, battery
    python -m celestron_aux [host] --camera          the StarSense camera's version, status and stored centre
    python -m celestron_aux [host] --listen 60       everything on the bus for 60 seconds; sends nothing
    python -m celestron_aux [host] --capture         one exposure: everything the camera says, and its star list
    python -m celestron_aux [host] --capture --save list.json --solve   ...kept as JSON, and plate solved
    python -m celestron_aux --solve-file list.json   plate solve a saved list; opens no connection
    python -m celestron_aux --build-database         fetch the star catalogue and build the solver's database
    python -m celestron_aux --discover

Without a host it tries the mount's address on its own hotspot. `--discover`
waits for a mount on this network to announce itself. The first two only read
and `--listen` sends nothing at all. `--capture` makes the camera take an
exposure. Solving needs the `solve` extra and the database; `--mirrored`
flips x before solving.
"""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime
from pathlib import Path

from . import solver, starsense
from .client import DEFAULT_PORT, DIRECT_CONNECT_HOST, AuxClient, AuxTimeout, discover
from .packet import Device, Packet, Star, StarFrame

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
    what.add_argument("--solve-file", type=Path, metavar="FILE", help="plate solve a list saved with --save; no connection")
    what.add_argument("--build-database", action="store_true", help="fetch the catalogue and build the solver's database; no connection")
    parser.add_argument(
        "--exposure",
        type=int,
        default=starsense.TOOLKIT_EXPOSURE,
        help="the number sent with the capture's reset (default %(default)s; 100 suited a daylit room)",
    )
    parser.add_argument("--save", type=Path, metavar="FILE", help="with --capture: write the star list as JSON")
    parser.add_argument("--solve", action="store_true", help="with --capture: plate solve the list just taken")
    parser.add_argument("--mirrored", action="store_true", help="flip x before solving")
    args = parser.parse_args()
    if (args.save or args.solve) and not args.capture:
        parser.error("--save and --solve go with --capture")
    if args.mirrored and not (args.solve or args.solve_file):
        parser.error("--mirrored goes with --solve or --solve-file")

    if args.build_database:
        _build_database()
        return
    if args.solve_file:
        saved = solver.load_stars(args.solve_file)
        print(f"{len(saved.stars)} stars, received {saved.finished.isoformat()}, exposure {saved.exposure}")
        _solve(saved.stars, args.mirrored)
        return

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
            stars = _capture(mount, args.exposure)
            if args.save:
                solver.save_stars(args.save, stars, finished=datetime.now(UTC), exposure=args.exposure)
                print(f"saved {len(stars)} stars to {args.save}")
            if args.solve:
                _solve(stars, args.mirrored)
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
    print(f"status {status.code} ({status.name}), {status.stars} stars")
    x, y = starsense.align_center(mount)
    print(f"stored centre x {x}, y {y} (sensor is {starsense.SENSOR_PIXELS[0]} by {starsense.SENSOR_PIXELS[1]})")


def _capture(mount: AuxClient, exposure: int) -> list[Star]:
    result = starsense.capture(mount, exposure=exposure)
    for seconds, frame in result.events:
        _show(seconds, frame)
    print(f"status {result.status.code} ({result.status.name}), {len(result.stars)} stars, list asked for {result.fetches} time(s)")
    return result.stars


def _solve(stars: list[Star], mirrored: bool) -> None:
    database = solver.load_database()
    began = time.monotonic()
    try:
        found = solver.solve(stars, database, mirrored=mirrored)
    except solver.NoSolution as failure:
        raise SystemExit(f"not solved ({'x flipped' if mirrored else 'as given'}): {failure}") from failure
    print(f"solved ({'x flipped' if mirrored else 'as given'}) in {time.monotonic() - began:.2f} s, J2000:")
    print(f"  RA  {_hms(found.ra)}  ({found.ra:.4f} deg)")
    print(f"  Dec {_dms(found.dec)}  ({found.dec:+.4f} deg)")
    print(f"  roll {found.roll:.2f} deg, field {found.fov:.3f} deg wide")
    print(f"  {found.matches} stars matched, RMSE {found.rmse_arcsec:.1f} arcsec, chance {found.prob:.1e}")


def _build_database() -> None:
    if solver.CATALOGUE_FILE.exists():
        solver.check_catalogue()
        print(f"catalogue {solver.CATALOGUE_FILE} is there and its sha256 matches")
    else:
        print(f"fetching {solver.CATALOGUE_URL}")
        solver.fetch_catalogue()
        print(f"catalogue saved to {solver.CATALOGUE_FILE}, sha256 matches")
    began = time.monotonic()
    count = solver.build_database()
    print(f"built {solver.DATABASE_FILE}: {count} patterns in {time.monotonic() - began:.0f} s")


def _hms(degrees: float) -> str:
    seconds = round(degrees % 360 / 15 * 3600, 1)
    return f"{int(seconds // 3600):02d}h {int(seconds % 3600 // 60):02d}m {seconds % 60:04.1f}s"


def _dms(degrees: float) -> str:
    arcseconds = round(abs(degrees) * 3600)
    return f"{'-' if degrees < 0 else '+'}{arcseconds // 3600:02d}d {arcseconds % 3600 // 60:02d}m {arcseconds % 60:02d}s"


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
