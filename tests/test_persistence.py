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


if __name__ == "__main__":
    main()
