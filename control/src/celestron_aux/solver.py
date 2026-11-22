"""Plate solving: from a StarSense star list to where the camera points.

This wraps cedar-solve (github.com/smroid/cedar-solve, Apache-2.0), a fork of
ESA's tetra3. It needs the optional `solve` extra; `import celestron_aux`
works without it, and so do `save_stars` and `load_stars`.

The pattern database is built here from the Hipparcos main catalogue (CDS
I/239). Neither file is in git. From `control/`:

    uv run python -m celestron_aux --build-database

fetches the catalogue into `control/data/`, checks its sha256 and builds the
database next to it (80 s on one Mac in Nov 2026).

A solve is one attempt with one database and one parity. When it fails, or
an answer fails a gate, `NoSolution` says which. Nothing here retries with the
other parity, a second database or a looser threshold.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .packet import Star
from .starsense import SENSOR_PIXELS

DATA_DIR = Path(__file__).resolve().parents[2] / "data"  # control/data in the source tree
CATALOGUE_URL = "https://vizier.cfa.harvard.edu/ftp/cats/I/239/hip_main.dat"  # VizieR's Harvard mirror of CDS
CATALOGUE_SHA256 = "58ceabb104d647160d9437ce6e513a02a036bb4ad9f8879a5a22fd52943616e0"
CATALOGUE_FILE = DATA_DIR / "hip_main.dat"  # the name tells tetra3 which catalogue format it is
DATABASE_FILE = DATA_DIR / "hip_fov5-10.npz"
BUILD_COMMAND = "uv run python -m celestron_aux --build-database (from control/)"

# The database covers horizontal fields of 5 to 10 degrees: the camera's field was believed to be
# about 7 degrees, uncertain by 30 percent, and the recorded frame measured 6.90.
MIN_FOV = 5.0
MAX_FOV = 10.0
PROPER_MOTION_EPOCH = 2026  # star positions are moved to this year; fixed so a rebuild gives the same file

# Gates on an answer. With cedar-solve's default threshold (1e-5) and this database, the recorded
# frame flipped in x "solved" to a wrong place 93 degrees away: 21 matches, probability 4.8e-7,
# 178 arcsec rms. The true answer has probability 1.6e-96 and 10 arcsec rms.
MATCH_THRESHOLD = 1e-15  # the library's false-positive probability, already scaled by the pattern count
MAX_RMSE_ARCSEC = 30.0  # three times the true answer's residual; the false one was six times this


class NoSolution(Exception):
    """A solve that found nothing, ran out of time, or found an answer that failed a gate."""


@dataclass(frozen=True)
class Solution:
    """Where the camera points.

    `ra` and `dec` are the centre of the sensor in degrees, J2000 (Hipparcos
    is on ICRS), with star positions moved to `PROPER_MOTION_EPOCH`. `roll` is
    in degrees as cedar-solve gives it: the angle of celestial north from the
    image's up (towards y = 0), counter-clockwise positive, 0 to 360. `fov` is
    the fitted horizontal field in degrees. `prob` is the library's
    probability that the match is chance, scaled by the database's pattern
    count.
    """

    ra: float
    dec: float
    roll: float
    fov: float
    matches: int
    rmse_arcsec: float
    prob: float


@dataclass(frozen=True)
class SavedStars:
    """A star list as `save_stars` writes it."""

    finished: datetime
    exposure: int
    stars: list[Star]


def save_stars(path: Path, stars: Sequence[Star], *, finished: datetime, exposure: int) -> None:
    """Write a star list as JSON: when it was received (UTC), the exposure setting, and [x, y] in list order."""
    if finished.utcoffset() is None:
        raise ValueError("finished must carry a time zone")
    record = {
        "finished_utc": finished.astimezone(UTC).isoformat(),
        "exposure": exposure,
        "stars": [[star.x, star.y] for star in stars],
    }
    path.write_text(json.dumps(record, indent=1) + "\n")


def load_stars(path: Path) -> SavedStars:
    record = json.loads(path.read_text())
    return SavedStars(
        finished=datetime.fromisoformat(record["finished_utc"]),
        exposure=int(record["exposure"]),
        stars=[Star(float(x), float(y)) for x, y in record["stars"]],
    )


class Database:
    """A loaded pattern database. Loading takes a few seconds, so load once and solve many times."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.library = _Library.load(path)

    @property
    def pattern_count(self) -> int:
        return self.library.pattern_count()


def load_database(path: Path = DATABASE_FILE) -> Database:
    if not path.exists():
        raise FileNotFoundError(f"no pattern database at {path}; build it with: {BUILD_COMMAND}")
    return Database(path)


def solve(
    stars: Sequence[Star],
    database: Database,
    *,
    mirrored: bool = False,
    fov_estimate: float | None = None,
    timeout: float = 5.0,
) -> Solution:
    """Solve one star list, as given or with x flipped (`mirrored`). One attempt; `NoSolution` when it fails.

    `stars` are on the 1280 by 960 sensor, in the camera's order, which was
    brightest first in the recorded frame. `fov_estimate` is the horizontal
    field in degrees; without it the database's whole range is searched.
    `timeout` is in seconds.
    """
    width, height = SENSOR_PIXELS
    centroids = [[star.y, width - star.x if mirrored else star.x] for star in stars]
    result = database.library.solve(centroids, (height, width), fov_estimate=fov_estimate, timeout=timeout)
    status = result["status"]
    if status == _TIMEOUT:
        raise NoSolution(f"timeout: no match within {timeout} s")
    if status == _TOO_FEW:
        raise NoSolution(f"no match: {len(stars)} stars are too few to try")
    if status != _MATCH_FOUND:
        raise NoSolution(f"no match (library status {status})")
    solution = Solution(
        ra=float(result["RA"]),
        dec=float(result["Dec"]),
        roll=float(result["Roll"]),
        fov=float(result["FOV"]),
        matches=int(result["Matches"]),
        rmse_arcsec=float(result["RMSE"]),
        prob=float(result["Prob"]),
    )
    if not solution.prob < MATCH_THRESHOLD:
        raise NoSolution(f"probability: {solution.prob:.2g} is not below {MATCH_THRESHOLD:g}")
    if not solution.rmse_arcsec <= MAX_RMSE_ARCSEC:
        raise NoSolution(f"RMSE: {solution.rmse_arcsec:.1f} arcsec is over {MAX_RMSE_ARCSEC:g}")
    return solution


def fetch_catalogue(path: Path = CATALOGUE_FILE) -> None:
    """Download the Hipparcos main catalogue from `CATALOGUE_URL` and check it against `CATALOGUE_SHA256`.

    A failed download or a wrong checksum raises; nothing is kept and no other mirror is tried.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name, suffix=".part", delete=False) as part:
        partial = Path(part.name)
        try:
            with urllib.request.urlopen(CATALOGUE_URL, timeout=60) as response:
                while chunk := response.read(1 << 20):
                    digest.update(chunk)
                    part.write(chunk)
        except BaseException:
            partial.unlink()
            raise
    if digest.hexdigest() != CATALOGUE_SHA256:
        partial.unlink()
        raise ValueError(f"{CATALOGUE_URL} has sha256 {digest.hexdigest()}, expected {CATALOGUE_SHA256}; nothing kept")
    partial.replace(path)


def check_catalogue(path: Path = CATALOGUE_FILE) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != CATALOGUE_SHA256:
        raise ValueError(f"{path} has sha256 {digest}, expected {CATALOGUE_SHA256}")


def build_database(catalogue: Path = CATALOGUE_FILE, path: Path = DATABASE_FILE) -> int:
    """Build the pattern database from a checked catalogue; returns the pattern count.

    The settings are cedar-solve's defaults except the field range and the
    proper-motion year. Asking for 150 stars per 5 degree field is more than
    Hipparcos holds, so the library warns and keeps every star in it.
    """
    check_catalogue(catalogue)
    path.parent.mkdir(parents=True, exist_ok=True)
    return _Library.build(catalogue, path)


# The untyped surface of cedar-solve stays below this line.

_MATCH_FOUND, _TIMEOUT, _TOO_FEW = 1, 3, 5  # tetra3.py: MATCH_FOUND, TIMEOUT, TOO_FEW


class _Library:
    def __init__(self, tetra: Any) -> None:
        self._tetra = tetra

    @staticmethod
    def _new() -> Any:
        try:
            import tetra3  # pyright: ignore[reportMissingTypeStubs]
        except ImportError as error:
            raise ImportError("plate solving needs the 'solve' extra: uv sync --extra solve") from error
        return tetra3.Tetra3(load_database=None)  # pyright: ignore[reportArgumentType]  # the library types it str but takes None

    @classmethod
    def load(cls, path: Path) -> _Library:
        tetra = cls._new()
        tetra.load_database(path)  # a Path is used as given; a str would be looked up in the library's own folder
        return cls(tetra)

    @classmethod
    def build(cls, catalogue: Path, path: Path) -> int:
        tetra = cls._new()
        tetra.generate_database(
            max_fov=MAX_FOV,
            min_fov=MIN_FOV,
            save_as=path,
            star_catalog=catalogue,
            epoch_proper_motion=PROPER_MOTION_EPOCH,
        )
        return int(tetra.database_properties["num_patterns"])  # its num_patterns stays None until a load

    def pattern_count(self) -> int:
        return int(self._tetra.database_properties["num_patterns"])

    def solve(
        self, centroids: list[list[float]], size: tuple[int, int], *, fov_estimate: float | None, timeout: float
    ) -> dict[str, Any]:
        result: dict[str, Any] = self._tetra.solve_from_centroids(
            centroids,
            size,
            fov_estimate=fov_estimate,
            match_threshold=MATCH_THRESHOLD,
            solve_timeout=timeout * 1000,
            distortion=0,
        )
        return result
