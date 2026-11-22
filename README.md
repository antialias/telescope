# telescope

Software for a Celestron NexStar Evolution 8 HD with StarSense AutoAlign. So
far: a small Python client for the mount's AUX bus over its WiFi, which can
also take exposures with the StarSense camera and read back its star lists.

This is not Celestron's software and has nothing to do with Celestron. What it
knows about the protocol comes from the open-source projects listed under
Sources and from what one mount answered.

## What works

Everything here was tried on one NexStar Evolution (model `0x1687`), over its
WiFi, joined to a home network. Another mount may answer differently.

- 2026-11-21: which devices answer, firmware versions, axis positions,
  battery; a slow goto of one axis and back.
- 2026-11-22: the original StarSense AutoAlign camera (`0xB4`): version,
  status, stored centre, exposures, and star lists. About one list in six
  arrived a byte short over WiFi; the same list can be fetched again, and the
  client does that.

Not done yet: turning a star list into a sky position, alignment, tracking.

## Try it

Needs [uv](https://docs.astral.sh/uv/). From `control/`:

    uv run python -m celestron_aux <mount address>              # reads only: devices, positions, battery
    uv run python -m celestron_aux <mount address> --camera     # reads only: the StarSense camera
    uv run python -m celestron_aux <mount address> --listen 60  # sends nothing: prints the bus
    uv run python -m celestron_aux <mount address> --capture --exposure 100   # one exposure and its star list
    uv run pytest && uv run pyright

Without an address it tries `1.2.3.4`, the mount's address on its own
hotspot. The tests run against an emulator and a stand-in for the camera;
they need no hardware and prove nothing about a real mount.

## Notes

[`docs/aux-protocol.md`](docs/aux-protocol.md) is the record: what is known
about the protocol, where each fact comes from, what was measured on the real
mount and camera, and what is still unknown.

## Sources

- [indi-celestronaux](https://github.com/indilib/indi-3rdparty/tree/master/indi-celestronaux):
  INDI's driver for this protocol. Packet format, addresses and motor commands.
- [caux-simulator](https://github.com/jochym/caux-simulator): the emulator the
  tests run against.
- [celestron-aux](https://github.com/platini2/celestron-aux): a
  reverse-engineered catalogue of AUX devices and commands. Everything here
  about the StarSense camera started from its notes and recordings.

## Licence

GPL-3.0. See [`LICENSE`](LICENSE).
