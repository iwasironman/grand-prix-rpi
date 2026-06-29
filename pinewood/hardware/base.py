"""Abstract hardware backend.

The UI never touches GPIO directly — it registers callbacks and calls
gate methods through this interface, so the same app runs on a laptop
(MockBackend) and on the Pi (GpioBackend).

Timing model
------------
Callbacks deliver a monotonic timestamp from ``time.perf_counter()``.  The
race controller records the gate-release time and subtracts to get each
lane's elapsed time, so absolute clock skew never matters.
"""

from __future__ import annotations

from typing import Callable

StartCallback = Callable[[], None]
FinishCallback = Callable[[int, float], None]   # (lane_index, perf_counter_ts)


class HardwareBackend:
    def __init__(self, cfg, lanes: int):
        self.cfg = cfg
        self.lanes = lanes
        self._on_start: StartCallback | None = None
        self._on_finish: FinishCallback | None = None
        self._on_start_line: FinishCallback | None = None

    # ----- callbacks --------------------------------------------------------
    def on_start(self, cb: StartCallback) -> None:
        self._on_start = cb

    def on_finish(self, cb: FinishCallback) -> None:
        self._on_finish = cb

    def on_start_line(self, cb: FinishCallback) -> None:
        """Register a callback for a start-line IR sensor trip (lane, ts)."""
        self._on_start_line = cb

    def _fire_start(self) -> None:
        if self._on_start:
            self._on_start()

    def _fire_finish(self, lane: int, ts: float) -> None:
        if self._on_finish:
            self._on_finish(lane, ts)

    def _fire_start_line(self, lane: int, ts: float) -> None:
        if self._on_start_line:
            self._on_start_line(lane, ts)

    # ----- gate -------------------------------------------------------------
    def arm_gate(self) -> None:
        """Move the gate to the closed/holding position."""
        raise NotImplementedError

    def release_gate(self) -> None:
        """Move the servo to release the cars."""
        raise NotImplementedError

    # ----- sensor enable window --------------------------------------------
    def begin_timing(self) -> None:
        """Start listening for finish-line trips (called at gate release)."""
        pass

    def end_timing(self) -> None:
        """Stop listening (called when the heat is scored)."""
        pass

    # ----- lifecycle --------------------------------------------------------
    def cleanup(self) -> None:
        pass

    # ----- mock-only hooks (no-ops on real hardware) -----------------------
    @property
    def is_mock(self) -> bool:
        return False

    def simulate_start(self) -> None:
        pass

    def simulate_finish(self, lane: int) -> None:
        pass

    def simulate_start_line(self, lane: int) -> None:
        pass
