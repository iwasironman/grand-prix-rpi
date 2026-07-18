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

"""Restart test: a fresh App on the same DB continues where it left off."""

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

from pinewood.config import load_config  # noqa: E402
from pinewood.race import RaceState  # noqa: E402
from pinewood.ui.app import App, Screen  # noqa: E402


def _cfg(tmp):
    cfg = load_config()
    cfg.display.fullscreen = False
    cfg.hardware.backend = "mock"
    cfg.countdown.stage_interval_s = 0.005
    cfg.config_dir = Path(tmp)
    cfg.database = "derby.db"
    return cfg


def _add(app, name, num):
    app.screen_state = Screen.RACERS
    for ch in name:
        app._on_key(pygame.event.Event(pygame.KEYDOWN, key=97, unicode=ch))
    app._on_key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    for ch in str(num):
        app._on_key(pygame.event.Event(pygame.KEYDOWN,
                                       key=getattr(pygame, f"K_{ch}"), unicode=ch))
    app._on_key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))


def _run_one_heat(app):
    app._enter_race()
    c = app.controller
    c.begin_countdown()
    for _ in range(40):
        time.sleep(0.005)
        c.update()
        if c.state is RaceState.ARMED:
            break
    app.hw.simulate_start_line(0)
    for lane, _rid in c.heat.occupied():
        app.hw.simulate_finish(lane)
    c.update()
    assert c.state is RaceState.FINISHED
    app._finish_current_heat()          # saves results + marks heat completed


def main():
    tmp = tempfile.mkdtemp()

    # --- session 1: set things up, run one heat, then "exit" --------------
    app1 = App(_cfg(tmp))
    for i, nm in enumerate(["Lightning", "Thunder", "Comet", "Rocket", "Blaze"], 1):
        _add(app1, nm, 100 + i)
    app1.screen_state = Screen.SCHEDULE
    app1._build_qualifying()
    # change every persisted setting via the real handlers
    app1.screen_state = Screen.SETTINGS
    app1.scoring = "average"
    while app1.scoring != "best":
        app1._cycle_scoring(1)
    app1.finalists = 4
    app1._cycle_finalists(1)            # 4 -> 8
    app1._cycle_format(1)               # rotation -> single
    n_heats = len(app1.db.get_heats("qualifying"))
    _run_one_heat(app1)
    app1.hw.cleanup()
    app1.db.close()                     # simulate exit

    # --- session 2: brand-new App on the SAME database --------------------
    app2 = App(_cfg(tmp))

    assert len(app2.db.list_racers()) == 5, "roster not restored"
    assert app2.scoring == "best", f"scoring not restored ({app2.scoring})"
    assert app2.finalists == 8, "finalists not restored"
    assert app2.finals_format == "single", "finals format not restored"

    q = app2.db.get_heats("qualifying")
    assert len(q) == n_heats, "schedule not restored"
    assert q[0].completed, "completed heat not restored"
    assert app2.db.next_pending_heat("qualifying").seq == 2, "did not resume at heat 2"
    assert len(app2.db.get_results("qualifying")) > 0, "results not restored"

    # the menu advertises the resume
    resume, status = app2._resume_status()
    assert resume and "Qualifying 1/" in status, f"resume status wrong: {status!r}"

    app2.hw.cleanup()
    app2.db.close()
    pygame.quit()
    print("PERSISTENCE OK: roster, schedule, results and settings all resumed.")


def test_late_entry_preserves_results_and_schedules_newcomer():
    """Adding a racer mid-event must not erase completed heats."""
    tmp = tempfile.mkdtemp()
    app = App(_cfg(tmp))
    for i, nm in enumerate(["A", "B", "C", "D", "E"], 1):
        _add(app, nm, 200 + i)
    app.screen_state = Screen.SCHEDULE
    app._build_qualifying()
    lanes = app.cfg.race.lanes
    n_before = len(app.db.get_heats("qualifying"))
    _run_one_heat(app)
    assert app.db.phase_has_results("qualifying")
    results_before = len(app.db.get_results("qualifying"))

    # destructive rebuild is guarded once results exist: first B only arms
    app.screen_state = Screen.SCHEDULE
    app._build_qualifying()
    assert app._confirm_rebuild, "rebuild should require confirmation"
    assert app.db.phase_has_results("qualifying"), "guard must not erase results"
    assert len(app.db.get_heats("qualifying")) == n_before, "guard must not rebuild"

    # add a late racer; re-entering the schedule screen disarms the guard
    _add(app, "Late", 999)
    app._confirm_rebuild = False   # what _select_menu(SCHEDULE) does on entry
    late = next(r for r in app.db.list_racers() if r.car_number == 999)
    assert late.id not in app.db.scheduled_racer_ids("qualifying")

    app._append_late_entries()

    heats = app.db.get_heats("qualifying")
    assert len(heats) == n_before + lanes, "should append one heat per lane"
    assert heats[0].completed, "existing completed heat was lost"
    assert len(app.db.get_results("qualifying")) == results_before, "results changed"
    # newcomer now runs once in every lane
    lane_counts = [0] * lanes
    for h in heats:
        for lane, rid in enumerate(h.lanes):
            if rid == late.id:
                lane_counts[lane] += 1
    assert lane_counts == [1] * lanes, lane_counts
    # seq numbering stays contiguous
    assert [h.seq for h in heats] == list(range(1, len(heats) + 1))

    # a second append with no new racers is a no-op
    app._append_late_entries()
    assert len(app.db.get_heats("qualifying")) == n_before + lanes

    app.hw.cleanup()
    app.db.close()
    pygame.quit()


if __name__ == "__main__":
    main()
    test_late_entry_preserves_results_and_schedules_newcomer()
    print("LATE-ENTRY OK: results preserved, newcomer scheduled once per lane.")
