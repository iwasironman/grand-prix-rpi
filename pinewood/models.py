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
