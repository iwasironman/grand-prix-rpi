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

"""Light-tree countdown timing: every amber must light before green."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pinewood.config import load_config  # noqa: E402
from pinewood.hardware.mock import MockBackend  # noqa: E402
from pinewood.models import Heat  # noqa: E402
from pinewood.race import RaceController, RaceState  # noqa: E402


def _controller():
    cfg = load_config()
    cfg.hardware.backend = "mock"
    hw = MockBackend(cfg.hardware, cfg.race.lanes)
    heat = Heat(id=1, phase="qualifying", seq=1, lanes=[1, 2, 3, 4])
    return cfg, RaceController(cfg, hw, heat)


def _at(ctrl, elapsed):
    """Pretend the countdown started `elapsed` seconds ago."""
    ctrl.state = RaceState.COUNTDOWN
    ctrl._countdown_t0 = time.perf_counter() - elapsed


def test_first_amber_lights_immediately():
    cfg, ctrl = _controller()
    _at(ctrl, 0.0)
    assert ctrl.amber_stages_lit() == 1


def test_bottom_amber_lights_before_green():
    cfg, ctrl = _controller()
    n = cfg.countdown.segments
    interval = cfg.countdown.stage_interval_s
    # midway through the LAST amber's interval — still counting down, all lit
    _at(ctrl, (n - 1) * interval + interval * 0.5)
    assert ctrl.amber_stages_lit() == n, "bottom amber not lit before green"
    assert not ctrl.green_lit()


def test_each_amber_lights_in_sequence():
    cfg, ctrl = _controller()
    n = cfg.countdown.segments
    interval = cfg.countdown.stage_interval_s
    for i in range(n):
        _at(ctrl, i * interval + interval * 0.5)
        assert ctrl.amber_stages_lit() == i + 1, f"amber {i} timing wrong"


def test_green_only_after_all_ambers():
    cfg, ctrl = _controller()
    n = cfg.countdown.segments
    interval = cfg.countdown.stage_interval_s
    _at(ctrl, n * interval + 0.02)
    ctrl.update()
    assert ctrl.green_lit(), "green should be lit once the countdown completes"
    # sensor mode -> ARMED (waiting for start beam), still 'green'
    assert ctrl.state in (RaceState.ARMED, RaceState.RUNNING)
