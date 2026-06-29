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

"""Keyboard-driven mock backend for development without a Pi.

The pygame app forwards key presses:  SPACE -> start button,
number keys 1..N -> the matching lane's finish sensor.
"""

from __future__ import annotations

import time


class MockBackend:
    def __init__(self, cfg, lanes: int):
        self.cfg = cfg
        self.lanes = lanes
        self._on_start = None
        self._on_finish = None
        self._on_start_line = None
        self._timing = False
        self._gate_open = False

    # callbacks
    def on_start(self, cb):
        self._on_start = cb

    def on_finish(self, cb):
        self._on_finish = cb

    def on_start_line(self, cb):
        self._on_start_line = cb

    # gate
    def arm_gate(self):
        self._gate_open = False

    def release_gate(self):
        self._gate_open = True

    # timing window
    def begin_timing(self):
        self._timing = True

    def end_timing(self):
        self._timing = False

    def cleanup(self):
        pass

    # mock hooks
    @property
    def is_mock(self) -> bool:
        return True

    def simulate_start(self):
        if self._on_start:
            self._on_start()

    def simulate_finish(self, lane: int):
        if self._timing and self._on_finish and 0 <= lane < self.lanes:
            self._on_finish(lane, time.perf_counter())

    def simulate_start_line(self, lane: int):
        if self._timing and self._on_start_line and 0 <= lane < self.lanes:
            self._on_start_line(lane, time.perf_counter())
