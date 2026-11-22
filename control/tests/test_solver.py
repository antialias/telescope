"""Plate solving the recorded star list from the celestron-aux toolkit (see fixtures/README.md).

The solving tests need the pattern database, which is not in git; without it
they skip and say how to build it. The answer they check is the one found in
the trial on 2026-11-22 and checked there against the catalogue by hand: 45 of
the 47 Hipparcos stars brighter than magnitude 8.5 in that field lie within 2
pixels of a listed star. The frame is from another camera, not ours.
"""

from __future__ import annotations

import random
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from celestron_aux import Parser, Star, StarFrame, solver
from celestron_aux.starsense import SENSOR_PIXELS

FIXTURE = Path(__file__).parent / "fixtures" / "starsense_frame.hex"
WIDTH, HEIGHT = SENSOR_PIXELS


def recorded_stars() -> list[Star]:
    frames = Parser().feed(bytes.fromhex(FIXTURE.read_text().strip()))
    assert len(frames) == 1
    frame = frames[0]
    assert isinstance(frame, StarFrame)
    stars = frame.stars()
    assert len(stars) == 99
    return stars


def flipped(stars: list[Star]) -> list[Star]:
    return [Star(WIDTH - star.x, star.y) for star in stars]


@pytest.fixture(scope="module")
def database() -> solver.Database:
    if not solver.DATABASE_FILE.exists():
        pytest.skip(f"no pattern database at {solver.DATABASE_FILE}; build it with: {solver.BUILD_COMMAND}")
    return solver.load_database()


def test_the_recorded_frame_solves_to_its_known_place(database: solver.Database) -> None:
    found = solver.solve(recorded_stars(), database)
    assert found.ra == pytest.approx(159.229, abs=0.01)
    assert found.dec == pytest.approx(38.641, abs=0.01)
    assert found.fov == pytest.approx(6.90, abs=0.02)
    assert found.roll == pytest.approx(267.38, abs=0.2)
    assert found.matches >= 50
    assert found.rmse_arcsec < 15
    assert found.prob < solver.MATCH_THRESHOLD


def test_the_frame_flipped_in_x_does_not_solve(database: solver.Database) -> None:
    # At cedar-solve's default threshold this list gave a wrong answer; the gates must refuse it.
    with pytest.raises(solver.NoSolution):
        solver.solve(flipped(recorded_stars()), database, timeout=5.0)


def test_mirrored_undoes_a_flip_in_x(database: solver.Database) -> None:
    found = solver.solve(flipped(recorded_stars()), database, mirrored=True)
    assert found.ra == pytest.approx(159.229, abs=0.01)
    assert found.dec == pytest.approx(38.641, abs=0.01)
    assert found.fov == pytest.approx(6.90, abs=0.02)


def test_random_points_do_not_solve(database: solver.Database) -> None:
    rng = random.Random(20261122)
    points = [Star(rng.uniform(0, WIDTH), rng.uniform(0, HEIGHT)) for _ in range(100)]
    with pytest.raises(solver.NoSolution):
        solver.solve(points, database, timeout=5.0)


def test_a_missing_database_names_the_build_command(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="--build-database"):
        solver.load_database(tmp_path / "absent.npz")


def test_a_saved_list_reads_back_the_same(tmp_path: Path) -> None:
    stars = recorded_stars()
    finished = datetime(2026, 11, 22, 21, 30, 5, 250000, tzinfo=timezone(timedelta(hours=-6)))
    path = tmp_path / "list.json"
    solver.save_stars(path, stars, finished=finished, exposure=100)
    saved = solver.load_stars(path)
    assert saved.stars == stars
    assert saved.exposure == 100
    assert saved.finished == finished
    assert saved.finished.utcoffset() == timedelta(0)
    assert '"finished_utc": "2026-11-23T03:30:05.250000+00:00"' in path.read_text()


def test_a_time_without_a_zone_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="time zone"):
        solver.save_stars(tmp_path / "list.json", [], finished=datetime(2026, 11, 22), exposure=100)


def test_the_package_imports_without_loading_the_solver_library() -> None:
    code = "import sys, celestron_aux, celestron_aux.solver; assert 'tetra3' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)
