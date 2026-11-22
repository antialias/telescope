"""Read-only probe: list what answers on the mount's AUX bus. Moves nothing.

    python -m celestron_aux [host] [--port 2000]
"""

from __future__ import annotations

import argparse

from .client import DEFAULT_PORT, DIRECT_CONNECT_HOST, AuxClient, AuxTimeout
from .packet import Device

MODELS = {0x1687: "NexStar Evolution"}  # indi-celestronaux celestronaux.h, MountVersion


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("host", nargs="?", default=DIRECT_CONNECT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    with AuxClient(args.host, args.port) as mount:
        for device in Device:
            if device is Device.APP:
                continue
            try:
                print(f"{device.name:18} 0x{device:02x}  version {mount.version(device)}")
            except AuxTimeout:
                print(f"{device.name:18} 0x{device:02x}  no reply")
        model = mount.model()
        print(f"model 0x{model:04x} ({MODELS.get(model, 'not in our table')})")
        print(f"azimuth encoder  {mount.position(Device.AZM):9.4f} deg, slewing: {not mount.slew_done(Device.AZM)}")
        print(f"altitude encoder {mount.position(Device.ALT):9.4f} deg, slewing: {not mount.slew_done(Device.ALT)}")
        try:
            battery = mount.battery()
            print(f"battery {battery.volts:.2f} V, {battery.level}, {battery.state}")
        except AuxTimeout:
            print("battery: no reply")


if __name__ == "__main__":
    main()
