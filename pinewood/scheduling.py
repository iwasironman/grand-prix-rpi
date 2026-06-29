"""Heat scheduling.

Goal: every car runs once in each lane so that a faster or slower lane cannot
bias the result.  We then rank by each car's average time across all lanes.

Algorithm (cyclic / "perfect-N" rotation)
-----------------------------------------
Number the cars 0..N-1 and the lanes 0..L-1.  Give each lane a distinct cyclic
offset spread evenly around the field::

    offset[lane] = round(lane * N / L)

Heat h (h = 0..N-1) places, in each lane, the car::

    car = (h + offset[lane]) % N

* Within a heat the L cars are distinct (offsets are distinct mod N when N>=L).
* For a fixed lane, as h sweeps 0..N-1 the car cycles through ALL N cars
  exactly once -> every car runs in every lane exactly once.

That yields N heats for N cars, each car running L times (once per lane).

For small fields (N < L) we fall back to a rotation that still gives each car a
different lane every heat, padding the unused lanes with ``None``.
"""

from __future__ import annotations


def _lane_offsets(n: int, lanes: int) -> list[int]:
    """Distinct, evenly spread cyclic offsets — one per lane."""
    offsets = [round(lane * n / lanes) % n for lane in range(lanes)]
    # Guard against a collision from rounding on awkward N (e.g. nudge dupes).
    seen: set[int] = set()
    for i, off in enumerate(offsets):
        while off in seen:
            off = (off + 1) % n
        offsets[i] = off
        seen.add(off)
    return offsets


def _small_rotation(racer_ids: list[int], lanes: int) -> list[list[int | None]]:
    """Few cars (< lanes): rotate cars across lanes, each gets every lane once."""
    heats: list[list[int | None]] = []
    for h in range(lanes):
        row: list[int | None] = [None] * lanes
        for i, rid in enumerate(racer_ids):
            row[(i + h) % lanes] = rid
        heats.append(row)
    return heats


def _cyclic_heats(racer_ids: list[int], lanes: int, num_heats: int) -> list[list[int | None]]:
    """First `num_heats` heats of the cyclic rotation.

    Each heat is full and has distinct cars.  Running the full N heats gives
    every car once per lane; running 2N gives twice per lane; running M<N gives
    each car ~M*lanes/N runs, each in a distinct lane.
    """
    n = len(racer_ids)
    offsets = _lane_offsets(n, lanes)
    return [
        [racer_ids[(h + offsets[lane]) % n] for lane in range(lanes)]
        for h in range(num_heats)
    ]


def build_schedule(
    racer_ids: list[int], lanes: int, runs_per_car: int = 0
) -> list[list[int | None]]:
    """Build a heat schedule.

    `runs_per_car` controls schedule density:
      * 0 (default) -> each car runs once in each lane  (a single rotation)
      * 2 * lanes   -> each car runs every lane twice    (double rotation)
      * < lanes     -> each car runs ~runs_per_car times  (faster, less balanced)
    """
    n = len(racer_ids)
    if n == 0:
        return []
    rpc = lanes if not runs_per_car else max(1, runs_per_car)

    if n < lanes:
        base = _small_rotation(racer_ids, lanes)
        reps = max(1, round(rpc / lanes))
        return [list(h) for _ in range(reps) for h in base]

    num_heats = max(1, round(n * rpc / lanes))
    return _cyclic_heats(racer_ids, lanes, num_heats)


def build_rotation(racer_ids: list[int], lanes: int) -> list[list[int | None]]:
    """A single fair rotation: every car runs once in each lane."""
    return build_schedule(racer_ids, lanes, runs_per_car=lanes)


def build_finals(finalist_ids: list[int], lanes: int) -> list[list[int | None]]:
    """Finals are a single fair rotation among the top qualifiers."""
    return build_rotation(finalist_ids, lanes)


def verify_fairness(heats: list[list[int | None]], lanes: int) -> dict:
    """Diagnostic: how many times each racer appears in each lane.

    Returns {racer_id: [count_lane0, count_lane1, ...]}.  A perfectly fair
    schedule has every count == 1 for participating racers.
    """
    counts: dict[int, list[int]] = {}
    for heat in heats:
        for lane, rid in enumerate(heat):
            if rid is None:
                continue
            counts.setdefault(rid, [0] * lanes)[lane] += 1
    return counts
