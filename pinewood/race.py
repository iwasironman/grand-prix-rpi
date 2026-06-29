"""Single-heat race controller — drives the start sequence and timing.

This is UI-agnostic: the pygame layer calls :meth:`update` every frame and
reads :attr:`state` / lane times to draw.  Hardware events arrive via the
backend callbacks registered in :meth:`__init__`.
"""

from __future__ import annotations

import time
from enum import Enum, auto
from threading import Lock

from .config import Config
from .hardware.base import HardwareBackend
from .models import Heat, LaneResult


class RaceState(Enum):
    STAGING = auto()      # cars shown, waiting for the start button
    COUNTDOWN = auto()    # light tree / numeric countdown running
    ARMED = auto()        # green shown; sensor mode waiting for the start beam
    RUNNING = auto()      # timing lanes (t0 set)
    FINISHED = auto()     # all lanes resolved (finished or DNF)


class RaceController:
    def __init__(self, cfg: Config, hw: HardwareBackend, heat: Heat):
        self.cfg = cfg
        self.hw = hw
        self.heat = heat
        self.lanes = cfg.race.lanes
        self.state = RaceState.STAGING

        self._lock = Lock()
        self._start_perf: float | None = None     # gate-release timestamp
        self._finish_perf: dict[int, float] = {}  # lane -> perf_counter
        self._countdown_t0: float | None = None
        self._green_until: float | None = None     # tree shows GREEN until this time
        self._last_end_tap: float | None = None    # first tap of the end double-tap
        self._n_stages = max(1, cfg.countdown.segments)   # amber bulbs before green
        self.start_mode = cfg.hardware.start_mode

        # lanes that actually have a car
        self._active_lanes = {lane for lane, _ in heat.occupied()}

        hw.on_start(self._on_start_pressed)
        hw.on_finish(self._on_finish)
        hw.on_start_line(self._on_start_line)
        hw.arm_gate()

    # ----- hardware callbacks (may run on another thread) ------------------
    def _on_start_pressed(self) -> None:
        # The start button is reused as an "end heat now" control: a DOUBLE TAP
        # while cars are running stops the heat and DNFs any lane that hasn't
        # crossed the line yet (derailed car, car that never reached the end).
        # Requiring two taps stops a single stray bump from killing a heat.
        if self.state is RaceState.STAGING:
            self.begin_countdown()
        elif self.state is RaceState.ARMED:
            # manual fallback: start the clock by button if the beam didn't trip
            self._begin_running(time.perf_counter())
        elif self.state is RaceState.RUNNING:
            self.request_end()

    def _on_finish(self, lane: int, ts: float) -> None:
        with self._lock:
            if self.state is not RaceState.RUNNING:
                return
            if lane in self._finish_perf or lane not in self._active_lanes:
                return
            self._finish_perf[lane] = ts

    def _on_start_line(self, lane: int, ts: float) -> None:
        # Sensor start: the FIRST start-line trip sets t0 for the whole heat.
        if self.state is RaceState.ARMED:
            self._begin_running(ts)

    def _begin_running(self, ts: float) -> None:
        with self._lock:
            if self.state is not RaceState.ARMED or self._start_perf is not None:
                return
            self._start_perf = ts
            self.state = RaceState.RUNNING

    def manual_start(self) -> None:
        """Operator starts the clock by hand (keyboard fallback in ARMED)."""
        self._begin_running(time.perf_counter())

    # ----- explicit triggers (UI may also start via keyboard) --------------
    def begin_countdown(self) -> None:
        if self.state is RaceState.STAGING:
            self.state = RaceState.COUNTDOWN
            self._countdown_t0 = time.perf_counter()

    def request_end(self) -> None:
        """Handle a start-button press during a race.

        Ends the heat only on a *double tap* (two presses within
        ``race.end_double_tap_s``); the first press just arms the confirm.
        """
        if self.state is not RaceState.RUNNING:
            return
        now = time.perf_counter()
        if (
            self._last_end_tap is not None
            and now - self._last_end_tap <= self.cfg.race.end_double_tap_s
        ):
            self.force_finish()
        else:
            self._last_end_tap = now

    def awaiting_end_confirm(self) -> bool:
        """True while the first end-tap is still within the double-tap window."""
        if self.state is not RaceState.RUNNING or self._last_end_tap is None:
            return False
        return time.perf_counter() - self._last_end_tap <= self.cfg.race.end_double_tap_s

    def force_finish(self) -> None:
        """End the heat immediately; lanes that never tripped become DNF.

        Used when the operator double-taps the start button mid-race because a
        car fell off the track or won't reach the finish line.
        """
        with self._lock:
            if self.state is not RaceState.RUNNING:
                return
            self.state = RaceState.FINISHED
        self.hw.end_timing()

    # ----- countdown helpers (for the light tree drawing) ------------------
    @property
    def segments(self) -> int:
        """Number of amber bulbs in the tree."""
        return self._n_stages

    def countdown_elapsed(self) -> float:
        if self._countdown_t0 is None:
            return 0.0
        return time.perf_counter() - self._countdown_t0

    _GREEN_STATES = (RaceState.ARMED, RaceState.RUNNING, RaceState.FINISHED)

    def amber_stages_lit(self) -> int:
        """How many amber bulbs are lit (0..n) during the countdown.

        Amber i lights at i * stage_interval — the first lights immediately, and
        the last (bottom) amber lights at (n-1)*interval, so it gets a full
        interval lit before GREEN appears at n*interval.
        """
        if self.state is not RaceState.COUNTDOWN:
            return self._n_stages if self.state in self._GREEN_STATES else 0
        steps = int(self.countdown_elapsed() / self.cfg.countdown.stage_interval_s)
        return min(self._n_stages, steps + 1)

    def countdown_number(self) -> int:
        """For numeric style: the big number to show (n..1), 0 means GO."""
        if self.state is not RaceState.COUNTDOWN:
            return 0
        steps = int(self.countdown_elapsed() / self.cfg.countdown.stage_interval_s)
        return max(0, self._n_stages - steps)

    def green_lit(self) -> bool:
        return self.state in self._GREEN_STATES

    def show_tree(self) -> bool:
        """Whether the light tree should be drawn right now.

        Visible through the amber countdown and the GREEN hold; it clears once
        the green hold elapses (the cue for the starter to release).
        """
        if self.state is RaceState.COUNTDOWN:
            return True
        if self._green_until is not None and time.perf_counter() < self._green_until:
            return True
        return False

    # ----- per-frame update -------------------------------------------------
    def update(self) -> None:
        now = time.perf_counter()

        if self.state is RaceState.COUNTDOWN:
            total = self._n_stages * self.cfg.countdown.stage_interval_s
            if self.countdown_elapsed() >= total:
                self._on_green()

        elif self.state is RaceState.RUNNING:
            with self._lock:
                # all active lanes in?
                done = self._active_lanes.issubset(self._finish_perf.keys())
                timed_out = (
                    self._start_perf is not None
                    and now - self._start_perf >= self.cfg.race.dnf_timeout_s
                )
            if done or timed_out:
                self.state = RaceState.FINISHED
                self.hw.end_timing()

    def _on_green(self) -> None:
        """Ambers finished → GREEN. Behaviour depends on the start mode."""
        now = time.perf_counter()
        self._green_until = now + self.cfg.countdown.green_hold_s
        self.hw.begin_timing()                 # arm sensors (start-line + finish)
        if self.start_mode == "servo":
            # automatic gate: release now, t0 is the release moment
            self.hw.release_gate()
            self._start_perf = now
            self.state = RaceState.RUNNING
        else:
            # manual gate: wait for the first start-line beam to set t0
            self.state = RaceState.ARMED

    # ----- live + final results --------------------------------------------
    def lane_time(self, lane: int) -> float | None:
        """Elapsed time for a lane, or None if not yet finished."""
        with self._lock:
            if self._start_perf is None or lane not in self._finish_perf:
                return None
            return self._finish_perf[lane] - self._start_perf

    def running_clock(self) -> float:
        if self._start_perf is None:
            return 0.0
        return time.perf_counter() - self._start_perf

    def results(self) -> list[LaneResult]:
        """Final scored results for occupied lanes (call when FINISHED)."""
        out: list[LaneResult] = []
        with self._lock:
            for lane, rid in self.heat.occupied():
                if lane in self._finish_perf and self._start_perf is not None:
                    t = self._finish_perf[lane] - self._start_perf
                    out.append(LaneResult(lane=lane, racer_id=rid, time_s=t, dnf=False))
                else:
                    out.append(LaneResult(lane=lane, racer_id=rid, time_s=None, dnf=True))
        return out
