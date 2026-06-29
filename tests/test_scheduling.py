"""Tests for the lane-rotation scheduler and ranking."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pinewood.models import LaneResult, Racer  # noqa: E402
from pinewood.ranking import compute_standings, heat_winner  # noqa: E402
from pinewood.scheduling import (  # noqa: E402
    build_rotation,
    build_schedule,
    verify_fairness,
)


def _assert_perfect(n, lanes):
    ids = list(range(1, n + 1))
    heats = build_rotation(ids, lanes)
    counts = verify_fairness(heats, lanes)
    # every participating racer appears exactly once in every lane
    for rid in ids:
        assert counts[rid] == [1] * lanes, (n, lanes, rid, counts[rid])
    # every heat has distinct, non-colliding cars
    for heat in heats:
        cars = [c for c in heat if c is not None]
        assert len(cars) == len(set(cars)), heat
    # total runs == n*lanes
    total = sum(1 for h in heats for c in h if c is not None)
    assert total == n * lanes


def test_perfect_rotation_various_sizes():
    for n in range(4, 31):
        _assert_perfect(n, 4)


def test_exactly_four_cars():
    _assert_perfect(4, 4)


def test_small_field_each_car_every_lane():
    # 2 and 3 cars: still want each car to see every lane once
    for n in (2, 3):
        ids = list(range(1, n + 1))
        heats = build_rotation(ids, 4)
        counts = verify_fairness(heats, 4)
        for rid in ids:
            assert counts[rid] == [1, 1, 1, 1]
        # no car appears twice in one heat
        for heat in heats:
            cars = [c for c in heat if c is not None]
            assert len(cars) == len(set(cars))


def test_empty():
    assert build_rotation([], 4) == []


def test_heat_count_equals_n_for_full_fields():
    for n in (4, 5, 8, 16, 23):
        assert len(build_rotation(list(range(n)), 4)) == n


def test_double_rotation_runs_each_lane_twice():
    for n in (4, 5, 8, 12):
        heats = build_schedule(list(range(n)), 4, runs_per_car=8)
        counts = verify_fairness(heats, 4)
        for rid in range(n):
            assert counts[rid] == [2, 2, 2, 2], (n, rid, counts[rid])
        assert len(heats) == 2 * n


def test_reduced_runs_fewer_heats_and_distinct_lanes():
    n = 12
    heats = build_schedule(list(range(n)), 4, runs_per_car=2)
    assert len(heats) < n                     # fewer than a full rotation
    counts = verify_fairness(heats, 4)
    for rid in range(n):
        per_lane = counts.get(rid, [0, 0, 0, 0])
        # each lane used at most once for a car (distinct lanes)
        assert all(c <= 1 for c in per_lane), (rid, per_lane)
        # roughly runs_per_car runs each
        assert 1 <= sum(per_lane) <= 3
    # full heats, no car twice in a heat
    for h in heats:
        cars = [c for c in h if c is not None]
        assert len(cars) == len(set(cars))


def test_default_runs_per_car_matches_single_rotation():
    ids = list(range(10))
    assert build_schedule(ids, 4, runs_per_car=0) == build_rotation(ids, 4)


def test_ranking_by_average():
    racers = {i: Racer(i, f"car{i}", i) for i in (1, 2, 3)}
    # car1 fastest avg, car2 mid, car3 slowest
    results = [
        LaneResult(0, 1, 3.0), LaneResult(1, 1, 3.2),
        LaneResult(0, 2, 3.5), LaneResult(1, 2, 3.5),
        LaneResult(0, 3, 4.0), LaneResult(1, 3, 4.2),
    ]
    standings = compute_standings(racers, results, 4, dnf_penalty_s=9.999)
    assert [s.racer.id for s in standings] == [1, 2, 3]
    assert standings[0].rank == 1
    assert abs(standings[0].average_s - 3.1) < 1e-9


def test_dnf_penalised():
    racers = {1: Racer(1, "a", 1), 2: Racer(2, "b", 2)}
    results = [
        LaneResult(0, 1, 3.0), LaneResult(1, 1, None, dnf=True),
        LaneResult(0, 2, 3.4), LaneResult(1, 2, 3.4),
    ]
    standings = compute_standings(racers, results, 4, dnf_penalty_s=9.999)
    # car2 finished both; car1 has a DNF dragging its average up
    assert standings[0].racer.id == 2
    assert standings[1].dnfs == 1


def test_heat_winner_ignores_dnf():
    res = [
        LaneResult(0, 1, None, dnf=True),
        LaneResult(1, 2, 3.5),
        LaneResult(2, 3, 3.2),
    ]
    w = heat_winner(res)
    assert w is not None and w.racer_id == 3
