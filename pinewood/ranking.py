# Grand Prix RPi — pinewood derby race system.
# Copyright (C) 2026 Steven Southwell
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Turn raw lane results into standings / rankings.

Several scoring methods are supported; all reduce the same per-lane times:

  average     mean of all of a car's runs (DNF charged dnf_penalty_s)
  drop_worst  drop each car's single slowest run, then average the rest
  best        a car's single fastest run
  total       sum of all runs
  points      finishing-place points per heat, summed (low total wins)

For every method a lower score is better.
"""

from __future__ import annotations

from .models import LaneResult, Racer, Standing

SCORING_METHODS = {
    "average": "Average time",
    "drop_worst": "Drop-worst avg",
    "best": "Best time",
    "total": "Total time",
    "points": "Place points",
}


def score_label(method: str) -> str:
    return SCORING_METHODS.get(method, method)


def column_label(method: str) -> str:
    return "Points" if method == "points" else "Score"


def format_score(st: Standing, method: str) -> str:
    if method == "points":
        return str(st.points)
    return f"{st.score:.3f}" if st.score is not None else "—"


def _heat_points(results: list[LaneResult], lanes: int) -> dict[int, int]:
    """Low-point scoring: 1st place in a heat = 1pt, 2nd = 2pt, …; DNF = worst."""
    by_heat: dict[object, list[LaneResult]] = {}
    for r in results:
        by_heat.setdefault(r.heat_id, []).append(r)

    pts: dict[int, int] = {}
    for heat_results in by_heat.values():
        finishers = sorted(
            (r for r in heat_results if r.finished),
            key=lambda r: r.time_s,  # type: ignore[arg-type]
        )
        for place, r in enumerate(finishers, start=1):
            pts[r.racer_id] = pts.get(r.racer_id, 0) + place
        for r in heat_results:
            if not r.finished:
                pts[r.racer_id] = pts.get(r.racer_id, 0) + lanes  # worst place
    return pts


def compute_standings(
    racers: dict[int, Racer],
    results: list[LaneResult],
    lanes: int,
    dnf_penalty_s: float,
    method: str = "average",
) -> list[Standing]:
    by_racer: dict[int, Standing] = {}
    runs: dict[int, list[float | None]] = {}
    for rid, racer in racers.items():
        by_racer[rid] = Standing(racer=racer, lane_times=[None] * lanes)
        runs[rid] = []

    for res in results:
        st = by_racer.get(res.racer_id)
        if st is None:
            continue
        st.runs += 1
        if 0 <= res.lane < lanes:
            st.lane_times[res.lane] = res.time_s if res.finished else None
        if res.finished:
            st.finishes += 1
            assert res.time_s is not None
            if st.best_s is None or res.time_s < st.best_s:
                st.best_s = res.time_s
            runs[res.racer_id].append(res.time_s)
        else:
            st.dnfs += 1
            runs[res.racer_id].append(None)

    standings = [s for s in by_racer.values() if s.runs > 0]
    points = _heat_points(results, lanes) if method == "points" else {}

    for st in standings:
        outcomes = runs[st.racer.id]
        times = [t if t is not None else dnf_penalty_s for t in outcomes]
        finite = [t for t in outcomes if t is not None]
        st.average_s = sum(times) / len(times) if times else None

        if method == "best":
            st.score = min(finite) if finite else dnf_penalty_s
        elif method == "total":
            st.score = sum(times)
        elif method == "drop_worst":
            if len(times) > 1:
                kept = sorted(times)[:-1]          # drop the single worst run
                st.score = sum(kept) / len(kept)
            else:
                st.score = times[0] if times else dnf_penalty_s
        elif method == "points":
            st.points = points.get(st.racer.id, 0)
            st.score = float(st.points)
        else:  # average
            st.score = st.average_s

    if method == "points":
        standings.sort(
            key=lambda s: (s.points, s.average_s if s.average_s is not None else 1e9)
        )
    else:
        standings.sort(key=lambda s: (s.score if s.score is not None else 1e9))

    for i, st in enumerate(standings, start=1):
        st.rank = i
    return standings


def heat_winner(results: list[LaneResult]) -> LaneResult | None:
    """Lane with the fastest finished time in a single heat."""
    finished = [r for r in results if r.finished]
    if not finished:
        return None
    return min(finished, key=lambda r: r.time_s)  # type: ignore[arg-type]
