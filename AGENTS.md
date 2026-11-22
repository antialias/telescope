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
- Not yet confirmed: the StarSense generation. The original (#94005) comes
  with a StarSense hand control; V2 (#94034) comes with a NexStar+ hand
  control. This decides which manual's alignment and calibration steps apply.

## Rules
- Procedures come from the maker's manuals in `docs/manuals`. Cite the manual
  and section for each step, and say plainly when a step is general practice
  the manual does not cover.
- Never point the telescope or the StarSense camera at the Sun without a
  proper full-aperture solar filter (the manuals' solar warning).

## Layout
- `docs/`: documentation. `docs/manuals` holds Celestron's PDFs, which stay
  out of git; its README lists where each came from.
- `control/`, `collection/`, `processing/`: created with the first code for
  each.
