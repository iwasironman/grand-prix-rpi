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

"""Plain data structures passed between the scheduler, DB and UI."""

from __future__ import annotations

from dataclasses import dataclass, field

# Race phases
QUALIFYING = "qualifying"
FINAL = "final"


@dataclass
class Racer:
    id: int
    name: str
    car_number: int
    active: bool = True


@dataclass
class Heat:
    """A single run of up to `lanes` cars at the same time.

    `lanes` maps lane index (0-based) -> racer id, or None for an empty lane.
    """

    id: int
    phase: str
    seq: int                       # ordering within its phase (1-based)
    lanes: list[int | None]
    completed: bool = False

    def occupied(self) -> list[tuple[int, int]]:
        """Return (lane_index, racer_id) for non-empty lanes."""
        return [(i, r) for i, r in enumerate(self.lanes) if r is not None]


@dataclass
class LaneResult:
    lane: int
    racer_id: int
    time_s: float | None           # None while pending
    dnf: bool = False
    heat_id: int | None = None     # set when loaded from the DB (for place scoring)

    @property
    def finished(self) -> bool:
        return self.time_s is not None and not self.dnf


@dataclass
class Standing:
    """Aggregated qualifying performance for one racer."""

    racer: Racer
    runs: int = 0
    finishes: int = 0
    dnfs: int = 0
    best_s: float | None = None
    average_s: float | None = None     # mean time (always computed, used for display/tiebreak)
    score: float | None = None         # the metric this ranking is sorted by
    points: int = 0                    # place-points total (for the "points" method)
    rank: int = 0
    lane_times: list[float | None] = field(default_factory=list)
