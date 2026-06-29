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

"""Headless end-to-end smoke test: boot the app, draw every screen, run a heat.

Uses SDL's dummy video driver so it needs no display. Catches runtime errors
in the pygame drawing code and the race controller without a Pi or a monitor.
"""

import os
import sys
import tempfile
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

from pinewood.config import load_config  # noqa: E402
from pinewood.race import RaceState  # noqa: E402
from pinewood.ui.app import App, Screen  # noqa: E402


def key(k, unicode=""):
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode=unicode)


def main():
    cfg = load_config()
    cfg.display.fullscreen = False
    cfg.display.width, cfg.display.height = 1280, 720
    cfg.hardware.backend = "mock"
    cfg.countdown.stage_interval_s = 0.01
    cfg.race.finalists = 4
    tmp = tempfile.mkdtemp()
    cfg.config_dir = __import__("pathlib").Path(tmp)
    cfg.database = "smoke.db"

    app = App(cfg)

    def draw_once():
        app._update()
        app._draw()
        pygame.display.flip()

    # draw the menu
    draw_once()

    # --- add 6 racers via the roster screen --------------------------------
    app.screen_state = Screen.RACERS
    names = ["Lightning", "Thunder", "Comet", "Rocket", "Blaze", "Dash"]
    for i, nm in enumerate(names, start=1):
        for ch in nm:
            app._on_key(key(pygame.K_a, ch))
        app._on_key(key(pygame.K_RETURN))           # -> number field
        for ch in str(100 + i):
            app._on_key(key(getattr(pygame, f"K_{ch}"), ch))
        app._on_key(key(pygame.K_RETURN))           # commit
    draw_once()
    assert len(app.db.list_racers()) == 6, "racers not saved"

    # --- save + load the roster through the UI -----------------------------
    app.screen_state = Screen.ROSTERS
    app._refresh_rosters()
    app._on_key(key(pygame.K_s))                     # open save prompt
    for ch in "Test Pack":
        app._on_key(key(pygame.K_a, ch))
    app._on_key(key(pygame.K_RETURN))                # commit save
    draw_once()
    assert app._roster_files, "roster file not saved"
    # wipe the roster, then load it back from the file
    app.db.replace_roster([])
    assert len(app.db.list_racers()) == 0
    app._refresh_rosters()
    app._roster_sel = 0
    app._on_key(key(pygame.K_RETURN))                # load selected
    draw_once()
    assert len(app.db.list_racers()) == 6, "roster did not load back"
    app.screen_state = Screen.MENU

    # --- build schedule ----------------------------------------------------
    app.screen_state = Screen.SCHEDULE
    app._on_key(key(pygame.K_RETURN))
    draw_once()
    qheats = app.db.get_heats("qualifying")
    assert len(qheats) == 6, f"expected 6 qualifying heats, got {len(qheats)}"

    # --- run EVERY qualifying + finals heat to completion ------------------
    app._enter_race()
    heats_run = 0
    safety = 0
    while app.screen_state == Screen.RACE and safety < 200:
        safety += 1
        ctrl = app.controller
        if ctrl is None:
            break
        if ctrl.state is RaceState.STAGING:
            ctrl.begin_countdown()
        elif ctrl.state is RaceState.COUNTDOWN:
            time.sleep(0.05)
            ctrl.update()
        elif ctrl.state is RaceState.ARMED:
            app.hw.simulate_start_line(0)        # first start beam sets t0
            ctrl.update()
        elif ctrl.state is RaceState.RUNNING:
            # finish each occupied lane with a distinct time
            for j, (lane, _rid) in enumerate(ctrl.heat.occupied()):
                time.sleep(0.002 * (j + 1))
                app.hw.simulate_finish(lane)
            ctrl.update()
        elif ctrl.state is RaceState.FINISHED:
            draw_once()                  # render the result screen
            heats_run += 1
            app._finish_current_heat()
        draw_once()

    assert app.screen_state == Screen.CHAMPION, \
        f"did not reach champion screen (state={app.screen_state}, ran {heats_run} heats)"
    print(f"ran {heats_run} heats (qualifying + finals)")

    # finals were auto-built
    assert app.db.phase_has_schedule("final"), "finals not built"

    # --- playoff settings: count + format rebuild correctly ----------------
    # (qualifying is fully raced here, so standings are available)
    app.db.clear_phase("final")
    app.finals_format = "single"
    app._build_finals()
    assert len(app.db.get_heats("final")) == 1, "single final should be one heat"

    app.db.clear_phase("final")
    app.finals_format = "rotation"
    app.finalists = 8
    app._build_finals()
    n_finalists = min(8, len(app.db.list_racers()))
    assert len(app.db.get_heats("final")) == n_finalists, "top-8 rotation heat count"

    app.db.clear_phase("final")
    app.finalists = 0
    app._build_finals()
    assert not app.db.phase_has_schedule("final"), "no playoffs when finalists=0"
    # restore
    app.finalists, app.finals_format = 4, "rotation"
    print("playoffs OK: single=1 heat, top-8 rotation, none=skipped")

    # --- standings + champion draws ----------------------------------------
    draw_once()                                       # champion
    app.screen_state = Screen.STANDINGS
    draw_once()
    app.screen_state = Screen.CONFIRM_RESET
    draw_once()

    # --- verify force-finish (start button mid-race) DNFs unfinished lanes --
    app.db.reset_results("qualifying")
    app.db.clear_phase("final")
    app._enter_race()
    ctrl = app.controller
    ctrl.begin_countdown()
    while ctrl.state is RaceState.COUNTDOWN:
        time.sleep(0.02)
        ctrl.update()
    if ctrl.state is RaceState.ARMED:        # sensor start: trip the start beam
        app.hw.simulate_start_line(0)
        ctrl.update()
    assert ctrl.state is RaceState.RUNNING
    occ = ctrl.heat.occupied()
    # only the first lane crosses the line; the rest are "still on the track"
    app.hw.simulate_finish(occ[0][0])
    ctrl.update()
    # a SINGLE press must NOT end the heat (guards against a stray bump)
    app.hw.simulate_start()
    assert ctrl.state is RaceState.RUNNING, "single tap should not end the heat"
    assert ctrl.awaiting_end_confirm(), "first tap should arm the end-confirm"
    # a second press within the window ends it
    app.hw.simulate_start()
    assert ctrl.state is RaceState.FINISHED, "double tap did not end the heat"
    res = ctrl.results()
    finished = [r for r in res if r.finished]
    dnfs = [r for r in res if r.dnf]
    assert len(finished) == 1 and len(dnfs) == len(occ) - 1, \
        f"expected 1 finisher + {len(occ) - 1} DNF, got {len(finished)}/{len(dnfs)}"
    draw_once()
    print(f"force-finish OK: 1 finisher, {len(dnfs)} DNF scored")

    # --- re-run paths ------------------------------------------------------
    def drive_to_finish(ctrl):
        ctrl.begin_countdown()
        while ctrl.state is RaceState.COUNTDOWN:
            time.sleep(0.02)
            ctrl.update()
        if ctrl.state is RaceState.ARMED:        # sensor start: trip the start beam
            app.hw.simulate_start_line(0)
            ctrl.update()
        for j, (lane, _rid) in enumerate(ctrl.heat.occupied()):
            time.sleep(0.001 * (j + 1))
            app.hw.simulate_finish(lane)
        ctrl.update()
        assert ctrl.state is RaceState.FINISHED

    app.db.reset_results("qualifying")
    app.db.clear_phase("final")

    # (1) redo from the result screen: discard times, re-stage, nothing saved
    app._enter_race()
    heat_id = app.cur_heat.id
    drive_to_finish(app.controller)
    draw_once()
    app._on_key(key(pygame.K_r))                     # re-run
    assert app.controller.state is RaceState.STAGING, "redo did not re-stage"
    assert not app._results_saved
    assert app.db.next_pending_heat("qualifying").id == heat_id, "heat got saved on redo"
    # now actually complete + accept it
    drive_to_finish(app.controller)
    app._finish_current_heat()
    assert app.db.get_heats("qualifying")[0].completed, "heat not saved after accept"
    print("redo-before-accept OK")

    # (2) re-run an already-completed heat from the schedule screen
    app.screen_state = Screen.SCHEDULE
    app._sched_sel = 0
    app._on_key(key(pygame.K_r))                     # re-run heat 1
    assert app._single_heat_mode and app.screen_state == Screen.RACE
    assert not app.db.get_heats("qualifying")[0].completed, "heat not reopened"
    drive_to_finish(app.controller)
    draw_once()
    app._on_key(key(pygame.K_RETURN))                # save & return
    assert app.screen_state == Screen.SCHEDULE, "did not return to schedule"
    assert app.db.get_heats("qualifying")[0].completed, "re-run result not saved"
    assert not app._single_heat_mode
    print("rerun-completed-heat OK")

    # --- sensor-start flow: countdown does NOT start the clock -------------
    app.db.reset_results("qualifying")
    app.db.clear_phase("final")
    app._enter_race()
    ctrl = app.controller
    ctrl.begin_countdown()
    while ctrl.state is RaceState.COUNTDOWN:
        time.sleep(0.02)
        ctrl.update()
    # ambers done -> ARMED (green), clock NOT yet running
    assert ctrl.state is RaceState.ARMED, f"expected ARMED, got {ctrl.state}"
    assert ctrl.running_clock() == 0.0, "clock started before the start beam"
    assert ctrl.green_lit() and ctrl.show_tree(), "green should be showing"
    draw_once()
    # a finish before the start beam must be ignored
    app.hw.simulate_finish(0)
    assert ctrl.lane_time(0) is None, "finish counted before start beam"
    # first start beam sets t0 for all lanes
    app.hw.simulate_start_line(0)
    assert ctrl.state is RaceState.RUNNING, "start beam did not start the clock"
    time.sleep(0.01)
    for lane, _rid in ctrl.heat.occupied():
        app.hw.simulate_finish(lane)
    ctrl.update()
    assert all(r.finished and r.time_s > 0 for r in ctrl.results()), "bad lane times"
    app._finish_current_heat()
    print("sensor-start OK: green→armed, t0 on first start beam, shared clock")

    # --- settings: scoring + schedule density ------------------------------
    from pinewood.ranking import SCORING_METHODS

    app.screen_state = Screen.SETTINGS
    start_scoring = app.scoring
    app._on_key(key(pygame.K_RIGHT))                 # cycle scoring method
    assert app.scoring != start_scoring
    assert app.db.get_setting("scoring", "?") == app.scoring, "scoring not persisted"
    draw_once()
    # every scoring method renders standings without error
    for m in SCORING_METHODS:
        app.scoring = m
        app.screen_state = Screen.STANDINGS
        draw_once()
    app.scoring = "average"

    # schedule density: double rotation -> twice the heats
    app.screen_state = Screen.SETTINGS
    app._on_key(key(pygame.K_DOWN))                  # select density row
    app.runs_per_car = 2 * cfg.race.lanes
    app.db.set_setting("runs_per_car", str(app.runs_per_car))
    app._build_qualifying()
    n_racers = len(app.db.list_racers())
    assert len(app.db.get_heats("qualifying")) == 2 * n_racers, "double rotation wrong"
    draw_once()
    print(f"settings OK: scoring persists, all methods render, "
          f"double rotation = {2 * n_racers} heats")

    app.hw.cleanup()
    app.db.close()
    pygame.quit()
    print("SMOKE OK: all screens drew, full event completed, champion crowned.")


if __name__ == "__main__":
    main()
