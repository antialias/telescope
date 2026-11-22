# telescope

Home for work with the household telescope: control, data collection,
processing and documentation.

## The instrument
- Celestron NexStar Evolution 8 HD with StarSense, Celestron model #12096
  (sold as "NexStar Evolution 8 EdgeHD"): an EdgeHD 8" optical tube on the
  NexStar Evolution single fork arm alt-az mount.
- The mount has a built-in LiFePO4 battery, four AUX ports and its own WiFi
  network (named "Celestron-xx" or "SkyQLink-xx", depending on the manual's
  edition). Celestron's SkyPortal app is the maker's control path over WiFi.
- Bought new in March 2025, bundled with a Celestron Eyepiece Accessory Kit.
  Also owned: a NexYZ DX smartphone adapter and Celestron's deluxe case for
  8" tubes.
- StarSense is the original generation (#94005): the hand control is a
  StarSense hand control (seen 2026-11-21); V2 (#94034) comes with a NexStar+
  one. Alignment and calibration steps come from the #94005 manual.

## Rules
- Procedures come from the maker's manuals in `docs/manuals`. Cite the manual
  and section for each step, and say plainly when a step is general practice
  the manual does not cover.
- Never point the telescope or the StarSense camera at the Sun without a
  proper full-aperture solar filter (the manuals' solar warning).

## This repository is public
- It is published at github.com/antialias/telescope under GPL-3.0 (owner's
  decision, 2026-11-22). Keep the owner's address, location, network
  addresses and anything else personal out of files and commit messages, and
  ask before adding a photo of the house.
- Commits use the GitHub no-reply address set in this repository's git
  config. Pushing is on the owner's word.

## Layout
- `docs/`: documentation. `docs/manuals` holds Celestron's PDFs, which stay
  out of git; its README lists where each came from.
- `control/`: Python package `celestron_aux`, a client for the mount's AUX
  protocol over its WiFi (`docs/aux-protocol.md` says what is known and how).
- `collection/`, `processing/`: created with the first code for each.

## Working in `control/`
- Tests and type check, from `control/`: `uv run pytest` and `uv run pyright`.
  The tests start `caux-simulator`, an emulator of the mount's bus, so they
  need no hardware and prove nothing about the real mount.
- `uv run python -m celestron_aux <host>` is a read-only probe of a mount.
  `--camera` reads the StarSense camera, `--listen <seconds>` prints the bus
  and sends nothing, and `--capture [--exposure N]` has the camera take an
  exposure and prints its star list. It moves nothing and works on ours over
  WiFi (2026-11-22; `--exposure 100` suited a daylit room).
- Plate solving (`solver.py`, `docs/plate-solving.md`) needs the `solve`
  extra, which the dev group includes, and a database built once with
  `uv run python -m celestron_aux --build-database` into `control/data/`
  (not in git; 80 s here). Without it the solving tests skip.
  `--capture --save FILE --solve` and `--solve-file FILE` solve; `--mirrored`
  flips x. A solve is one attempt: never add a retry with the other parity,
  another database or a looser gate.
- A motion command to the real mount is sent on the owner's word.
