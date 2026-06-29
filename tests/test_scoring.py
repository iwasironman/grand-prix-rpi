"""Tests for the selectable scoring methods."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pinewood.models import LaneResult, Racer  # noqa: E402
from pinewood.ranking import compute_standings  # noqa: E402

PEN = 9.999


def _racers(n):
    return {i: Racer(i, f"car{i}", i) for i in range(1, n + 1)}


def _by_id(standings):
    return {s.racer.id: s for s in standings}


def test_best_time_rewards_single_fast_run():
    racers = _racers(2)
    # car1: one blazing run + one slow; car2: two medium runs
    results = [
        LaneResult(0, 1, 2.0, heat_id=1), LaneResult(1, 1, 5.0, heat_id=2),
        LaneResult(0, 2, 3.0, heat_id=1), LaneResult(1, 2, 3.0, heat_id=2),
    ]
    best = _by_id(compute_standings(racers, results, 4, PEN, method="best"))
    assert best[1].rank == 1                       # car1 wins on best time
    avg = _by_id(compute_standings(racers, results, 4, PEN, method="average"))
    assert avg[2].rank == 1                        # car2 wins on average


def test_drop_worst_ignores_one_bad_run():
    racers = _racers(2)
    # car1 is fast twice but has a DNF; car2 is steady
    results = [
        LaneResult(0, 1, 3.0, heat_id=1),
        LaneResult(1, 1, 3.0, heat_id=2),
        LaneResult(2, 1, None, dnf=True, heat_id=3),
        LaneResult(0, 2, 3.4, heat_id=1),
        LaneResult(1, 2, 3.4, heat_id=2),
        LaneResult(2, 2, 3.4, heat_id=3),
    ]
    avg = _by_id(compute_standings(racers, results, 4, PEN, method="average"))
    assert avg[2].rank == 1                        # DNF sinks car1 on plain average
    drop = _by_id(compute_standings(racers, results, 4, PEN, method="drop_worst"))
    assert drop[1].rank == 1                       # dropping the DNF, car1 wins


def test_total_matches_average_order_when_runs_equal():
    racers = _racers(3)
    results = []
    for rid, base in ((1, 3.0), (2, 3.5), (3, 4.0)):
        results += [LaneResult(0, rid, base, heat_id=1),
                    LaneResult(1, rid, base, heat_id=2)]
    tot = compute_standings(racers, results, 4, PEN, method="total")
    avg = compute_standings(racers, results, 4, PEN, method="average")
    assert [s.racer.id for s in tot] == [s.racer.id for s in avg] == [1, 2, 3]


def test_place_points_low_total_wins():
    racers = _racers(3)
    # Heat 1 order: c1 < c2 < c3 ; Heat 2 order: c1 < c2 < c3
    results = [
        LaneResult(0, 1, 3.0, heat_id=1), LaneResult(1, 2, 3.5, heat_id=1),
        LaneResult(2, 3, 4.0, heat_id=1),
        LaneResult(0, 1, 3.1, heat_id=2), LaneResult(1, 2, 3.6, heat_id=2),
        LaneResult(2, 3, 4.1, heat_id=2),
    ]
    pts = _by_id(compute_standings(racers, results, 4, PEN, method="points"))
    assert pts[1].points == 2 and pts[1].rank == 1     # two firsts = 2 pts
    assert pts[2].points == 4
    assert pts[3].points == 6


def test_place_points_dnf_gets_worst_place():
    racers = _racers(2)
    results = [
        LaneResult(0, 1, 3.0, heat_id=1),
        LaneResult(1, 2, None, dnf=True, heat_id=1),
    ]
    pts = _by_id(compute_standings(racers, results, 4, PEN, method="points"))
    assert pts[1].points == 1          # winner
    assert pts[2].points == 4          # DNF = worst place (= lanes)
