# Plate solving

Plate solving turns a StarSense star list into the place on the sky the camera
points at. `control/src/celestron_aux/solver.py` does it with
[cedar-solve](https://github.com/smroid/cedar-solve), a fork of ESA's tetra3.
It takes the list of star positions the camera already sends, so no image is
needed. It needs no starting guess of position or time ("lost in space").

So far it has solved one recorded list, from another person's camera. No list
from our camera has been solved yet.

## How it works

cedar-solve compares groups of four stars in the list with groups of four
stars in a pattern database, which is built from a star catalogue. When the
shapes agree it fits a rotation and a field of view, then counts how many
listed stars land on catalogue stars. It reports how likely that count is by
chance, and the rms distance between matched stars and their catalogue
positions.

## Settings, and why

- **Library**: cedar-solve at commit `607e3f8` (Aug 2026), from git. PyPI's
  0.5.1 is from 2024 and is older code. Licence Apache-2.0; it is a dependency,
  not copied in. ESA's tetra3 has had no commit since Dec 2023.
- **Python dependencies**: cedar-solve pins Pillow below 9 and numpy below 2,
  which have no wheels for current Python. `pyproject.toml` overrides both
  pins. The recorded frame solved to the same answer with numpy 2.5.
- **Catalogue**: the Hipparcos main catalogue (CDS I/239, `hip_main.dat`,
  118,218 stars, 53 MB), from VizieR's Harvard mirror. CDS Strasbourg did not
  answer from here on 2026-11-22. The file is checked against its sha256 and
  nothing else is tried if the download or the check fails.
- **Database**: patterns for horizontal fields of 5 to 10 degrees, at scales of
  5, 7.07 and 10 degrees, with cedar-solve's other defaults and star positions
  moved to 2026. The camera's field was believed to be about 7 degrees, give or
  take 30 percent. The database bundled with cedar-solve is for 10 to 30
  degrees and solved fewer than half of simulated 6.9 degree fields (below).
- **Gates**: an answer is kept only if its chance probability is below 1e-15
  and its rms residual is at most 30 arcseconds. cedar-solve's own default
  threshold, 1e-5, let a wrong answer through (below).
- **One attempt**: a solve uses one parity and one database. `mirrored=True`
  flips x first. Nothing retries with the other parity or a looser setting; a
  failure raises `NoSolution`, which says which gate failed.
- **Order**: cedar-solve tries the first stars of the list first and expects
  brightest first. The recorded list is in that order (below).

## Building the database

From `control/`:

    uv run python -m celestron_aux --build-database

This fetches the catalogue into `control/data/` and builds
`control/data/hip_fov5-10.npz` (79 MB). Neither file is in git. Without the
database the solving tests skip and say this command.

Then:

    uv run python -m celestron_aux <mount address> --capture --save list.json --solve
    uv run python -m celestron_aux --solve-file list.json [--mirrored]

## Measured

All on one Mac, 2026-11-22.

### The recorded frame

The frame is `control/tests/fixtures/starsense_frame.hex`, from the
celestron-aux toolkit's tests. It is from someone else's camera. Its time and
place are unknown. It holds 99 stars.

- Solved as given, without a field estimate: RA 159.2292, Dec +38.6414 degrees
  (J2000), roll 267.38 degrees, field 6.899 by about 5.18 degrees (19.41
  arcseconds a pixel), 67 stars matched, chance probability 1.6e-96, rms 9.9
  arcseconds (about half a pixel), largest 26.5. The search took about 2 ms
  once the database was loaded.
- Checked without cedar-solve, from the catalogue file: 45 of the 47
  Hipparcos stars of magnitude 8.5 or brighter in that field lie within 2
  pixels of a listed star. At 2000 random places and rolls, the same count
  averaged 0.05, and was at most 2.
- The list is brightest first: for matched stars, list position against
  catalogue magnitude has a rank correlation of 0.96.
- With the image flipped in x, at cedar-solve's default threshold of 1e-5, it
  gave a wrong answer: RA 213.58, Dec -40.22, 93 degrees away, field 9.04
  degrees, 21 matches, probability 4.8e-7, rms 178 arcseconds. The same
  check found 2 coincidences, which is chance. At 1e-15 the flipped list finds
  nothing.
- So the camera that made this list does not mirror the sky. Whether ours
  does is not known yet.
- Building the database gave 4,750,804 patterns. It took 534 seconds in the
  trial (Python 3.12, numpy 1.26) and 80 seconds with this project's
  dependencies (Python 3.14, numpy 2.5).

### Simulated skies

300 evenly spread fields at 6.9 degrees, made from the same Hipparcos
catalogue, with 0.5 pixel noise, one star in ten dropped and five false
points added, solved without a field estimate:

| Database | Stars to magnitude 8 (median 34 a field) | to magnitude 9 (median 65) | Wrong answers |
|---|---|---|---|
| 5 to 10 degrees (ours) | 300 of 300 | 300 of 300 | 0 |
| cedar-solve's bundled one | 127 of 300 | 111 of 300 | 0 |

The slowest solve with our database took 363 ms. These fields come from the
same catalogue as the database. They do not model our camera's limiting
magnitude, its colour response or its false detections, so they say the
database covers the sky, not that our camera's lists will solve.

## Not known yet

- Whether lists from our camera solve, and our camera's field and parity.
- How many stars our camera lists under a dark sky.
- How the roll relates to the mount's axes. Nothing here moves the mount or
  aligns it.
