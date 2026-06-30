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

"""Pygame application: menu, roster entry, schedule, race mode, results."""

from __future__ import annotations

import math
import sys
from enum import Enum, auto

import pygame

from ..audio import Beeper
from ..config import Config
from ..db import Database
from ..hardware import create_backend
from ..models import FINAL, QUALIFYING, Heat
from ..race import RaceController, RaceState
from ..ranking import (
    SCORING_METHODS,
    column_label,
    compute_standings,
    format_score,
    heat_winner,
    score_label,
)
from ..roster import (
    list_rosters,
    load_roster,
    roster_label,
    save_roster,
)
from ..scheduling import build_finals, build_schedule, verify_fairness
from . import theme as T


class Screen(Enum):
    MENU = auto()
    RACERS = auto()
    ROSTERS = auto()
    SETTINGS = auto()
    SCHEDULE = auto()
    RACE = auto()         # staging -> countdown -> running -> result
    STANDINGS = auto()
    CHAMPION = auto()
    CONFIRM_RESET = auto()


MENU_ITEMS = [
    ("Manage Racers", Screen.RACERS),
    ("Save / Load Roster", Screen.ROSTERS),
    ("Settings", Screen.SETTINGS),
    ("Build Schedule", Screen.SCHEDULE),
    ("Race!", Screen.RACE),
    ("Standings", Screen.STANDINGS),
    ("Reset Event", Screen.CONFIRM_RESET),
    ("Quit", None),
]


class App:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.db = Database(cfg.database_path)
        self.hw = create_backend(cfg.hardware, cfg.race.lanes)

        pygame.init()
        pygame.display.set_caption("Grand Prix RPi — Pinewood Derby")
        # The SCALED flag is REQUIRED on the Pi's KMSDRM driver: it makes pygame
        # present through an accelerated (GL/EGL) renderer and scale our fixed
        # 1280x720 layout to the actual display. A plain window surface is not
        # scanned out on kmsdrm (blank screen).
        flags = pygame.FULLSCREEN | pygame.SCALED if cfg.display.fullscreen else 0
        self.screen = pygame.display.set_mode(
            (cfg.display.width, cfg.display.height), flags
        )
        if cfg.display.fullscreen:
            pygame.mouse.set_visible(False)
        self.W, self.H = self.screen.get_size()
        self.fonts = T.Fonts(scale=self.H / 720.0)
        self.clock = pygame.time.Clock()
        try:
            with open("/tmp/gp_display.log", "w") as _f:
                _f.write(f"driver={pygame.display.get_driver()} size={self.W}x{self.H}\n")
        except Exception:
            pass

        self.beeper = Beeper(
            enabled=cfg.countdown.sound,
            amber_hz=cfg.countdown.amber_tone_hz,
            go_hz=cfg.countdown.go_tone_hz,
            amber_ms=cfg.countdown.stage_interval_s * 1000,   # hold like the light
            go_ms=cfg.countdown.green_hold_s * 1000,
        )

        self.screen_state = Screen.MENU
        self.menu_idx = 0
        self.running = True

        # roster entry state
        self._racers = self.db.list_racers()
        self._field = "name"        # "name" | "number"
        self._buf_name = ""
        self._buf_number = ""
        self._sel_racer = 0
        self._msg = ""

        # roster save/load screen state
        self._roster_files: list = []
        self._roster_sel = 0
        self._roster_saving = False
        self._roster_save_name = ""

        # race state
        self.controller: RaceController | None = None
        self.cur_heat: Heat | None = None
        self._ambers_beeped = 0          # countdown beeps already played
        self._go_beeped = False
        self.cur_phase = QUALIFYING
        self._results_saved = False
        self._single_heat_mode = False   # re-running one heat, then return
        self._sched_sel = 0              # selected heat on the schedule screen

        # scoring / scheduling / playoff settings (DB overrides config defaults)
        self.scoring = self.db.get_setting("scoring", cfg.race.scoring)
        self.runs_per_car = int(
            self.db.get_setting("runs_per_car", str(cfg.race.runs_per_car))
        )
        self.finalists = int(
            self.db.get_setting("finalists", str(cfg.race.finalists))
        )
        self.finals_format = self.db.get_setting(
            "finals_format", cfg.race.finals_format
        )
        self._settings_sel = 0           # which setting row is selected

    # ======================================================================
    #  Main loop
    # ======================================================================
    def run(self) -> None:
        try:
            while self.running:
                self._handle_events()
                self._update()
                self._draw()
                pygame.display.flip()
                self.clock.tick(self.cfg.display.fps)
        finally:
            self.hw.cleanup()
            self.db.close()
            pygame.quit()

    # ======================================================================
    #  Events
    # ======================================================================
    def _handle_events(self) -> None:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.running = False
            elif ev.type == pygame.KEYDOWN:
                self._on_key(ev)

    def _on_key(self, ev) -> None:
        # Global: ESC backs out to the menu (except mid-race, or while typing
        # a roster name — there ESC just cancels the save prompt).
        if (
            ev.key == pygame.K_ESCAPE
            and self.screen_state not in (Screen.MENU, Screen.RACE)
            and not (self.screen_state is Screen.ROSTERS and self._roster_saving)
        ):
            self.screen_state = Screen.MENU
            self._msg = ""
            return

        dispatch = {
            Screen.MENU: self._key_menu,
            Screen.RACERS: self._key_racers,
            Screen.ROSTERS: self._key_rosters,
            Screen.SETTINGS: self._key_settings,
            Screen.SCHEDULE: self._key_schedule,
            Screen.RACE: self._key_race,
            Screen.STANDINGS: self._key_standings,
            Screen.CHAMPION: self._key_champion,
            Screen.CONFIRM_RESET: self._key_confirm_reset,
        }
        dispatch[self.screen_state](ev)

    # ----- menu -------------------------------------------------------------
    def _key_menu(self, ev) -> None:
        if ev.key in (pygame.K_DOWN, pygame.K_s):
            self.menu_idx = (self.menu_idx + 1) % len(MENU_ITEMS)
        elif ev.key in (pygame.K_UP, pygame.K_w):
            self.menu_idx = (self.menu_idx - 1) % len(MENU_ITEMS)
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self._select_menu()

    def _select_menu(self) -> None:
        label, target = MENU_ITEMS[self.menu_idx]
        if target is None:
            self.running = False
            return
        if target is Screen.RACE:
            self._enter_race()
            return
        if target is Screen.RACERS:
            self._racers = self.db.list_racers()
            self._sel_racer = 0
        if target is Screen.ROSTERS:
            self._refresh_rosters()
        self.screen_state = target
        self._msg = ""

    # ----- racers -----------------------------------------------------------
    def _key_racers(self, ev) -> None:
        if ev.key == pygame.K_TAB:
            self._field = "number" if self._field == "name" else "name"
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if self._field == "name":
                self._field = "number"
            else:
                self._commit_racer()
        elif ev.key == pygame.K_BACKSPACE:
            if self._field == "name":
                self._buf_name = self._buf_name[:-1]
            else:
                self._buf_number = self._buf_number[:-1]
        elif ev.key in (pygame.K_DELETE,):
            self._delete_selected()
        elif ev.key == pygame.K_DOWN:
            if self._racers:
                self._sel_racer = (self._sel_racer + 1) % len(self._racers)
        elif ev.key == pygame.K_UP:
            if self._racers:
                self._sel_racer = (self._sel_racer - 1) % len(self._racers)
        else:
            ch = ev.unicode
            if self._field == "name" and ch and ch.isprintable() and len(self._buf_name) < 22:
                self._buf_name += ch
            elif self._field == "number" and ch.isdigit() and len(self._buf_number) < 4:
                self._buf_number += ch

    def _commit_racer(self) -> None:
        name = self._buf_name.strip()
        if not name:
            self._msg = "Enter a name first."
            self._field = "name"
            return
        if not self._buf_number:
            self._msg = "Enter a car number."
            return
        num = int(self._buf_number)
        if self.db.car_number_exists(num):
            self._msg = f"Car #{num} already exists."
            return
        self.db.add_racer(name, num)
        self._racers = self.db.list_racers()
        self._msg = f"Added #{num} {name}."
        self._buf_name = ""
        self._buf_number = ""
        self._field = "name"

    def _delete_selected(self) -> None:
        if not self._racers:
            return
        r = self._racers[self._sel_racer]
        self.db.delete_racer(r.id)
        self._racers = self.db.list_racers()
        self._sel_racer = min(self._sel_racer, max(0, len(self._racers) - 1))
        self._msg = f"Removed #{r.car_number} {r.name}."

    # ----- rosters (save / load) -------------------------------------------
    def _refresh_rosters(self) -> None:
        self._roster_files = list_rosters(self.cfg)
        self._roster_sel = min(self._roster_sel, max(0, len(self._roster_files) - 1))

    def _key_rosters(self, ev) -> None:
        if self._roster_saving:
            self._key_roster_save(ev)
            return
        if ev.key in (pygame.K_s,):
            self._roster_saving = True
            self._roster_save_name = ""
            self._msg = ""
        elif ev.key == pygame.K_DOWN:
            if self._roster_files:
                self._roster_sel = (self._roster_sel + 1) % len(self._roster_files)
        elif ev.key == pygame.K_UP:
            if self._roster_files:
                self._roster_sel = (self._roster_sel - 1) % len(self._roster_files)
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_l):
            self._load_selected_roster()
        elif ev.key == pygame.K_DELETE:
            self._delete_selected_roster()

    def _key_roster_save(self, ev) -> None:
        if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._commit_roster_save()
        elif ev.key == pygame.K_ESCAPE:
            self._roster_saving = False
            self._roster_save_name = ""
        elif ev.key == pygame.K_BACKSPACE:
            self._roster_save_name = self._roster_save_name[:-1]
        else:
            ch = ev.unicode
            if ch and ch.isprintable() and len(self._roster_save_name) < 28:
                self._roster_save_name += ch

    def _commit_roster_save(self) -> None:
        name = self._roster_save_name.strip()
        if not name:
            self._msg = "Enter a name for the roster."
            return
        racers = self.db.list_racers()
        if not racers:
            self._msg = "No racers to save."
            self._roster_saving = False
            return
        path = save_roster(self.cfg, name, racers)
        self._roster_saving = False
        self._roster_save_name = ""
        self._refresh_rosters()
        self._msg = f"Saved {len(racers)} racers to {path.name}"

    def _load_selected_roster(self) -> None:
        if not self._roster_files:
            self._msg = "No saved rosters to load."
            return
        path = self._roster_files[self._roster_sel]
        try:
            entries = load_roster(path)
        except (ValueError, OSError) as exc:
            self._msg = f"Could not load: {exc}"
            return
        added = self.db.replace_roster(entries)
        self._racers = self.db.list_racers()
        self._msg = f"Loaded {added} racers from {path.name} (event reset)"

    def _delete_selected_roster(self) -> None:
        if not self._roster_files:
            return
        path = self._roster_files[self._roster_sel]
        try:
            path.unlink()
        except OSError as exc:
            self._msg = f"Could not delete: {exc}"
            return
        self._msg = f"Deleted {path.name}"
        self._refresh_rosters()

    # ----- settings (scoring / schedule / playoffs) ------------------------
    _SCORING_DESC = {
        "average": "Mean of all runs. Fair; rewards consistency.",
        "drop_worst": "Drop each car's slowest run, then average. Absorbs a fluke/DNF.",
        "best": "Each car's single fastest run. Rewards top speed.",
        "total": "Sum of all runs. Same order as average under a full rotation.",
        "points": "Finish-place points per heat, summed. Tolerant of jittery timing.",
    }

    def _settings_rows(self) -> list:
        return [
            {"label": "Scoring method", "value": score_label(self.scoring),
             "desc": self._SCORING_DESC[self.scoring], "change": self._cycle_scoring},
            {"label": "Schedule density", "value": self._runs_label(),
             "desc": "Applies the next time you build the schedule.",
             "change": self._adjust_runs},
            {"label": "Playoff cars", "value": self._finalists_label(),
             "desc": "How many top qualifiers advance to the playoffs.",
             "change": self._cycle_finalists},
            {"label": "Playoff format", "value": self._format_label(),
             "desc": "Rotation = finalists run every lane (fair). "
                     "Single = one final heat of the top 4.",
             "change": self._cycle_format},
        ]

    def _key_settings(self, ev) -> None:
        rows = self._settings_rows()
        if ev.key == pygame.K_DOWN:
            self._settings_sel = min(self._settings_sel + 1, len(rows) - 1)
        elif ev.key == pygame.K_UP:
            self._settings_sel = max(self._settings_sel - 1, 0)
        elif ev.key in (pygame.K_LEFT, pygame.K_RIGHT):
            step = 1 if ev.key == pygame.K_RIGHT else -1
            rows[self._settings_sel]["change"](step)

    def _cycle_scoring(self, step: int) -> None:
        keys = list(SCORING_METHODS)
        i = (keys.index(self.scoring) + step) % len(keys)
        self.scoring = keys[i]
        self.db.set_setting("scoring", self.scoring)
        self.db.clear_phase(FINAL)        # seeding depends on scoring
        self._msg = f"Scoring set to {score_label(self.scoring)}"

    # --- playoff settings ---------------------------------------------------
    _FINALIST_OPTIONS = [0, 4, 8]

    def _finalists_label(self) -> str:
        return {0: "None — qualifying decides", 4: "Top 4", 8: "Top 8"}.get(
            self.finalists, f"Top {self.finalists}")

    def _cycle_finalists(self, step: int) -> None:
        opts = self._FINALIST_OPTIONS
        cur = opts.index(self.finalists) if self.finalists in opts else 1
        self.finalists = opts[max(0, min(len(opts) - 1, cur + step))]
        self.db.set_setting("finalists", str(self.finalists))
        self.db.clear_phase(FINAL)        # re-seed next time
        self._msg = "Playoff size changed."

    def _format_label(self) -> str:
        return {"rotation": "Rotation (every lane, fair)",
                "single": "Single final heat"}.get(self.finals_format,
                                                    self.finals_format)

    def _cycle_format(self, step: int) -> None:
        opts = ["rotation", "single"]
        cur = opts.index(self.finals_format) if self.finals_format in opts else 0
        self.finals_format = opts[max(0, min(len(opts) - 1, cur + step))]
        self.db.set_setting("finals_format", self.finals_format)
        self.db.clear_phase(FINAL)
        self._msg = "Playoff format changed."

    def _density_options(self) -> list[tuple[int, str]]:
        """Distinct schedule-density choices, in order, for the current lanes."""
        lanes = self.cfg.race.lanes
        opts = [(k, f"~{k} runs each — reduced/faster") for k in range(2, lanes)]
        opts.append((lanes, f"once per lane ({lanes} runs) — single rotation"))
        opts.append((2 * lanes, f"twice per lane ({2 * lanes} runs) — double rotation"))
        return opts

    def _density_index(self) -> int:
        # runs_per_car == 0 means the default single rotation (== lanes)
        value = self.runs_per_car or self.cfg.race.lanes
        opts = self._density_options()
        for i, (v, _) in enumerate(opts):
            if v == value:
                return i
        return next(i for i, (v, _) in enumerate(opts) if v == self.cfg.race.lanes)

    def _adjust_runs(self, step: int) -> None:
        opts = self._density_options()
        i = max(0, min(len(opts) - 1, self._density_index() + step))
        self.runs_per_car = opts[i][0]
        self.db.set_setting("runs_per_car", str(self.runs_per_car))
        self._msg = "Schedule density changed — rebuild the schedule to apply."

    def _runs_label(self) -> str:
        return self._density_options()[self._density_index()][1]

    # ----- schedule ---------------------------------------------------------
    def _key_schedule(self, ev) -> None:
        heats = self.db.get_heats(QUALIFYING)
        if ev.key == pygame.K_b:
            self._build_qualifying()
            self._sched_sel = 0
        elif ev.key == pygame.K_DOWN:
            if heats:
                self._sched_sel = min(self._sched_sel + 1, len(heats) - 1)
        elif ev.key == pygame.K_UP:
            if heats:
                self._sched_sel = max(self._sched_sel - 1, 0)
        elif ev.key == pygame.K_r:
            if heats:
                self._rerun_heat(heats[self._sched_sel])
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if not heats:
                self._build_qualifying()      # Enter builds only when empty
            else:
                self._rerun_heat(heats[self._sched_sel])

    def _rerun_heat(self, heat: Heat) -> None:
        """Re-run one specific heat, then return to the schedule."""
        self.db.reopen_heat(heat.id)
        self._single_heat_mode = True
        self.cur_phase = heat.phase
        self.screen_state = Screen.RACE
        self._start_heat(heat)
        self._msg = ""

    def _build_qualifying(self) -> None:
        racers = self.db.list_racers()
        if len(racers) < 2:
            self._msg = "Need at least 2 racers."
            return
        rows = build_schedule(
            [r.id for r in racers], self.cfg.race.lanes, self.runs_per_car
        )
        self.db.save_schedule(QUALIFYING, rows)
        self.db.clear_phase(FINAL)   # invalidate stale finals
        self._msg = f"Built {len(rows)} qualifying heats. Results cleared."

    # ----- race -------------------------------------------------------------
    def _key_race(self, ev) -> None:
        if self.controller is None:
            # result/idle view between heats
            if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self._advance_heat()
            elif ev.key == pygame.K_ESCAPE:
                self.screen_state = Screen.MENU
            return

        st = self.controller.state
        if ev.key == pygame.K_SPACE and st is RaceState.STAGING:
            self.controller.begin_countdown()
        elif ev.key == pygame.K_SPACE and st is RaceState.ARMED:
            # start the clock: mock = trip the start beam; real = manual fallback
            if self.hw.is_mock:
                self.hw.simulate_start_line(0)
            else:
                self.controller.manual_start()
        elif ev.key == pygame.K_SPACE and st is RaceState.RUNNING:
            # double-tap to end the heat now; unfinished lanes are scored DNF
            self.controller.request_end()
        elif st is RaceState.RUNNING and ev.unicode.isdigit():
            lane = int(ev.unicode) - 1
            self.hw.simulate_finish(lane)        # no-op on real GPIO
        elif st is RaceState.FINISHED and ev.key == pygame.K_r:
            # something went wrong — discard these times and re-stage the heat
            self._start_heat(self.cur_heat)
            self._msg = ""
        elif st is RaceState.FINISHED and ev.key in (
            pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE
        ):
            self._finish_current_heat()
        elif ev.key == pygame.K_ESCAPE and st in (
            RaceState.STAGING, RaceState.ARMED, RaceState.FINISHED
        ):
            self.controller = None
            self.screen_state = (
                Screen.SCHEDULE if self._single_heat_mode else Screen.MENU
            )
            self._single_heat_mode = False

    def _enter_race(self) -> None:
        if not self.db.phase_has_schedule(QUALIFYING):
            self._msg = "Build the schedule first."
            self.screen_state = Screen.MENU
            return
        self.screen_state = Screen.RACE
        self.controller = None
        self._advance_heat()

    def _advance_heat(self) -> None:
        """Pick the next pending heat across qualifying then finals."""
        heat = self.db.next_pending_heat(QUALIFYING)
        if heat is not None:
            self.cur_phase = QUALIFYING
            self._start_heat(heat)
            return

        # qualifying done -> playoffs (unless disabled)
        if self.finalists > 0:
            if not self.db.phase_has_schedule(FINAL):
                self._build_finals()
            heat = self.db.next_pending_heat(FINAL)
            if heat is not None:
                self.cur_phase = FINAL
                self._start_heat(heat)
                return

        # everything done -> champion
        self.controller = None
        self.cur_heat = None
        self.screen_state = Screen.CHAMPION

    def _build_finals(self) -> None:
        if self.finalists <= 0:
            return
        racers = self.db.racers_by_id()
        results = self.db.get_results(QUALIFYING)
        standings = compute_standings(
            racers, results, self.cfg.race.lanes, self.cfg.race.dnf_penalty_s,
            method=self.scoring,
        )
        lanes = self.cfg.race.lanes
        if self.finals_format == "single":
            # one winner-take-all heat of the top `lanes` cars
            n = min(lanes, len(standings))
            ids = [s.racer.id for s in standings[:n]]
            rows = [ids + [None] * (lanes - len(ids))]
        else:
            n = min(self.finalists, len(standings))
            ids = [s.racer.id for s in standings[:n]]
            rows = build_finals(ids, lanes)
        if rows:
            self.db.save_schedule(FINAL, rows)

    def _start_heat(self, heat: Heat) -> None:
        self.cur_heat = heat
        self.controller = RaceController(self.cfg, self.hw, heat)
        self._results_saved = False
        self._ambers_beeped = 0
        self._go_beeped = False
        self._msg = ""

    def _finish_current_heat(self) -> None:
        if self.controller is None or self.cur_heat is None:
            return
        if not self._results_saved:
            self.db.save_heat_results(self.cur_heat.id, self.controller.results())
            self._results_saved = True
        self.controller = None
        if self._single_heat_mode:
            self._single_heat_mode = False
            self.screen_state = Screen.SCHEDULE
        else:
            self._advance_heat()

    # ----- standings / champion / reset ------------------------------------
    def _key_standings(self, ev) -> None:
        pass

    def _key_champion(self, ev) -> None:
        if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE, pygame.K_ESCAPE):
            self.screen_state = Screen.MENU

    def _key_confirm_reset(self, ev) -> None:
        if ev.key in (pygame.K_y, pygame.K_RETURN):
            self.db.reset_event()
            self._msg = "Event reset (roster kept)."
            self.screen_state = Screen.MENU
        elif ev.key in (pygame.K_n, pygame.K_ESCAPE):
            self.screen_state = Screen.MENU

    # ======================================================================
    #  Update
    # ======================================================================
    def _update(self) -> None:
        if self.screen_state is Screen.RACE and self.controller is not None:
            self.controller.update()
            self._update_countdown_sound()

    def _update_countdown_sound(self) -> None:
        """Beep on each amber as it lights, and a GO tone when green appears."""
        ctrl = self.controller
        if ctrl is None:
            return
        if ctrl.state is RaceState.COUNTDOWN:
            lit = ctrl.amber_stages_lit()
            while self._ambers_beeped < lit:
                self.beeper.amber()
                self._ambers_beeped += 1
        if ctrl.green_lit() and not self._go_beeped:
            self.beeper.go()
            self._go_beeped = True

    # ======================================================================
    #  Draw
    # ======================================================================
    def _draw(self) -> None:
        self.screen.fill(T.BG)
        drawer = {
            Screen.MENU: self._draw_menu,
            Screen.RACERS: self._draw_racers,
            Screen.ROSTERS: self._draw_rosters,
            Screen.SETTINGS: self._draw_settings,
            Screen.SCHEDULE: self._draw_schedule,
            Screen.RACE: self._draw_race,
            Screen.STANDINGS: self._draw_standings,
            Screen.CHAMPION: self._draw_champion,
            Screen.CONFIRM_RESET: self._draw_confirm_reset,
        }
        drawer[self.screen_state]()
        if self._msg:
            T.draw_text(self.screen, self.fonts, self._msg, 22,
                        (self.W // 2, self.H - 28), T.ACCENT, center=True)

    def _header(self, title: str, subtitle: str = "") -> None:
        T.draw_text(self.screen, self.fonts, title, 46, (40, 28), T.FG)
        if subtitle:
            T.draw_text(self.screen, self.fonts, subtitle, 22, (42, 82), T.MUTED)
        pygame.draw.line(self.screen, T.BG_PANEL, (40, 118), (self.W - 40, 118), 3)

    def _resume_status(self) -> tuple[bool, str | None]:
        """(is_resume, status_text) describing where the event stands.

        Everything is persisted to the DB as it happens, so this reflects what
        'Race!' will do after a restart. is_resume is True when a partly-run
        event can be continued.
        """
        if not self.db.phase_has_schedule(QUALIFYING):
            return (False, None)
        q = self.db.get_heats(QUALIFYING)
        q_done = sum(1 for h in q if h.completed)
        f = self.db.get_heats(FINAL)
        f_done = sum(1 for h in f if h.completed)
        any_done = q_done + f_done > 0

        if q_done < len(q):
            txt = f"Qualifying {q_done}/{len(q)}"
            return (any_done, f"{txt} — Race! to {'continue' if any_done else 'begin'}")
        # qualifying complete
        if self.finalists <= 0:
            return (True, "Qualifying complete — Race! crowns the champion")
        if not f:
            return (True, "Qualifying complete — Race! starts the playoffs")
        if f_done < len(f):
            return (True, f"Playoffs {f_done}/{len(f)} — Race! to continue")
        return (False, "Event complete — Race! shows the champion")

    # ----- menu -------------------------------------------------------------
    def _draw_menu(self) -> None:
        cx = self.W // 2
        T.draw_text(self.screen, self.fonts, "GRAND PRIX", 88, (cx, 120),
                    T.ACCENT, center=True)
        T.draw_text(self.screen, self.fonts, "Pinewood Derby Race System", 28,
                    (cx, 188), T.MUTED, center=True)

        n_racers = len(self.db.list_racers())
        T.draw_text(self.screen, self.fonts,
                    f"{n_racers} racers   |   "
                    f"{self.cfg.race.lanes} lanes   |   "
                    f"scoring: {score_label(self.scoring)}",
                    20, (cx, 224), T.MUTED, center=True)
        resume, status = self._resume_status()
        if status:
            T.draw_text(self.screen, self.fonts, status, 20, (cx, 252),
                        T.ACCENT if resume else T.MUTED, center=True)

        # Scrolling window: keep the selected item visible, show ▲/▼ when there
        # are more items off-screen.
        menu_top = 278
        item_h = 58
        hint_y = self.H - 34
        avail = hint_y - menu_top - 24
        visible = max(1, avail // item_h)
        n = len(MENU_ITEMS)
        start = 0 if n <= visible else min(max(self.menu_idx - visible // 2, 0),
                                           n - visible)
        end = min(start + visible, n)

        resume_race = self._resume_status()[0]
        for row, i in enumerate(range(start, end)):
            label, target = MENU_ITEMS[i]
            if target is Screen.RACE and resume_race:
                label = "Resume Race"
            selected = i == self.menu_idx
            y = menu_top + row * item_h
            rect = pygame.Rect(cx - 230, y, 460, item_h - 8)
            if selected:
                T.rounded_panel(self.screen, rect, T.BG_PANEL, border=T.ACCENT)
            color = T.ACCENT if selected else T.FG
            prefix = "›  " if selected else "    "
            T.draw_text(self.screen, self.fonts, prefix + label, 32,
                        (cx, y + (item_h - 8) // 2), color, center=True)

        if start > 0:
            T.draw_text(self.screen, self.fonts, "▲ more", 18,
                        (cx, menu_top - 14), T.MUTED, center=True)
        if end < n:
            T.draw_text(self.screen, self.fonts, "▼ more", 18,
                        (cx, menu_top + visible * item_h + 2), T.MUTED, center=True)

        T.draw_text(self.screen, self.fonts,
                    "↑/↓ to move · Enter to select", 20,
                    (cx, hint_y), T.MUTED, center=True)

    # ----- racers -----------------------------------------------------------
    def _draw_racers(self) -> None:
        self._header("Manage Racers", "Type a name and car number · Enter to add · ↑/↓ + Del to remove · Esc back")
        # entry form
        fy = 150
        name_active = self._field == "name"
        num_active = self._field == "number"
        self._input_box("Name", self._buf_name, (40, fy, 520, 56), name_active)
        self._input_box("Car #", self._buf_number, (580, fy, 200, 56), num_active)

        # list — a fitted grid that pages when there are more racers than fit
        ly = 250
        total = len(self._racers)
        T.draw_text(self.screen, self.fonts, f"Roster ({total})", 26,
                    (40, ly - 36), T.MUTED)
        if not self._racers:
            T.draw_text(self.screen, self.fonts, "No racers yet.", 24,
                        (40, ly + 10), T.MUTED)
            return

        cols = 3
        row_h = 36
        rows_per_col = max(1, (self.H - ly - 54) // row_h)
        capacity = cols * rows_per_col
        col_w = (self.W - 80) // cols

        page = self._sel_racer // capacity
        start = page * capacity
        # paging info lives on the header line so it never collides with the
        # bottom status message (e.g. "Added #102 Lightning.")
        if total > capacity:
            last = min(start + capacity, total)
            npages = (total + capacity - 1) // capacity
            T.draw_text(self.screen, self.fonts,
                        f"showing {start + 1}–{last} of {total}  ·  "
                        f"page {page + 1}/{npages}",
                        20, (self.W - 40, ly - 30), T.MUTED, right=True)
        for vi, r in enumerate(self._racers[start:start + capacity]):
            i = start + vi
            col = vi // rows_per_col
            row = vi % rows_per_col
            x = 40 + col * col_w
            y = ly + row * row_h
            sel = i == self._sel_racer
            rect = pygame.Rect(x, y, col_w - 16, row_h - 4)
            if sel:
                T.rounded_panel(self.screen, rect, T.BG_PANEL, radius=8, border=T.ACCENT)
            T.draw_text(self.screen, self.fonts, f"#{r.car_number}", 22,
                        (x + 12, y + 6), T.ACCENT)
            name = r.name if len(r.name) <= 14 else r.name[:13] + "…"
            T.draw_text(self.screen, self.fonts, name, 22, (x + 86, y + 6), T.FG)

    def _input_box(self, label, value, rect, active) -> None:
        x, y, w, h = rect
        T.draw_text(self.screen, self.fonts, label, 20, (x, y - 26), T.MUTED)
        box = pygame.Rect(x, y, w, h)
        T.rounded_panel(self.screen, box, T.BG_PANEL, radius=10,
                        border=T.ACCENT if active else T.MUTED)
        cursor = "_" if active else ""
        T.draw_text(self.screen, self.fonts, value + cursor, 30,
                    (x + 14, y + h // 2 - 16), T.FG)

    # ----- rosters ----------------------------------------------------------
    def _draw_rosters(self) -> None:
        self._header(
            "Save / Load Roster",
            "S save current roster · ↑/↓ select · Enter/L load · Del delete · Esc back",
        )
        cur = len(self.db.list_racers())
        T.draw_text(self.screen, self.fonts,
                    f"Current roster: {cur} racers", 24, (40, 128), T.MUTED)

        ly = 180
        if not self._roster_files:
            T.draw_text(self.screen, self.fonts,
                        "No saved rosters yet — press S to save the current one.",
                        26, (40, ly), T.MUTED)
        for i, path in enumerate(self._roster_files):
            name, count = roster_label(path)
            sel = i == self._roster_sel
            y = ly + i * 46
            rect = pygame.Rect(40, y, self.W - 80, 40)
            if sel:
                T.rounded_panel(self.screen, rect, T.BG_PANEL, radius=8, border=T.ACCENT)
            color = T.ACCENT if sel else T.FG
            T.draw_text(self.screen, self.fonts, ("›  " if sel else "    ") + name,
                        26, (56, y + 7), color)
            T.draw_text(self.screen, self.fonts, f"{count} racers", 22,
                        (self.W - 70, y + 9), T.MUTED, right=True)

        if self._roster_saving:
            self._draw_save_prompt()

    def _draw_save_prompt(self) -> None:
        w, h = 720, 200
        box = pygame.Rect((self.W - w) // 2, (self.H - h) // 2, w, h)
        # dim background
        veil = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 170))
        self.screen.blit(veil, (0, 0))
        T.rounded_panel(self.screen, box, T.BG_PANEL, radius=16, border=T.ACCENT)
        T.draw_text(self.screen, self.fonts, "Save roster as…", 30,
                    (box.x + 30, box.y + 26), T.FG)
        field = pygame.Rect(box.x + 30, box.y + 80, w - 60, 56)
        T.rounded_panel(self.screen, field, T.BG, radius=10, border=T.ACCENT)
        T.draw_text(self.screen, self.fonts, self._roster_save_name + "_", 30,
                    (field.x + 14, field.y + 14), T.FG)
        T.draw_text(self.screen, self.fonts, "Enter to save · Esc to cancel", 20,
                    (box.x + 30, box.bottom - 34), T.MUTED)

    # ----- settings ---------------------------------------------------------
    def _draw_settings(self) -> None:
        self._header(
            "Settings",
            "↑/↓ choose a setting · ←/→ change it · Esc back",
        )
        rows = self._settings_rows()
        top = 140
        gap = 14
        avail = self.H - top - 40
        row_h = min(120, (avail - gap * (len(rows) - 1)) // len(rows))
        for i, row in enumerate(rows):
            y = top + i * (row_h + gap)
            sel = i == self._settings_sel
            rect = pygame.Rect(40, y, self.W - 80, row_h)
            T.rounded_panel(self.screen, rect, T.BG_PANEL,
                            border=T.ACCENT if sel else T.MUTED,
                            width=3 if sel else 1)
            T.draw_text(self.screen, self.fonts, row["label"], 22,
                        (64, y + 12), T.MUTED)
            arrows = "‹  " if sel else "   "
            arrows2 = "  ›" if sel else ""
            T.draw_text(self.screen, self.fonts, arrows + row["value"] + arrows2, 32,
                        (64, y + 44), T.ACCENT if sel else T.FG)
            T.draw_text(self.screen, self.fonts, row["desc"], 18,
                        (64, y + row_h - 26), T.MUTED, bold=False)

    # ----- schedule ---------------------------------------------------------
    def _draw_schedule(self) -> None:
        self._header(
            "Qualifying Schedule",
            "↑/↓ select · Enter/R re-run a heat · B (re)build · Esc back",
        )
        heats = self.db.get_heats(QUALIFYING)
        racers = self.db.racers_by_id()
        if not heats:
            T.draw_text(self.screen, self.fonts,
                        "No schedule yet — press Enter or B to build one.", 28,
                        (40, 160), T.MUTED)
            return
        self._sched_sel = min(self._sched_sel, len(heats) - 1)

        # fairness banner
        fair = verify_fairness([h.lanes for h in heats], self.cfg.race.lanes)
        perfect = all(all(c == 1 for c in counts) for counts in fair.values())
        msg = "• Perfectly balanced: each car runs every lane once" if perfect \
            else "Balanced as evenly as possible for this field size"
        T.draw_text(self.screen, self.fonts, f"{len(heats)} heats   ·   {msg}",
                    22, (40, 128), T.GOOD if perfect else T.ACCENT)

        # column headers
        top = 168
        x0 = 40
        T.draw_text(self.screen, self.fonts, "Heat", 20, (x0, top), T.MUTED)
        for lane in range(self.cfg.race.lanes):
            T.draw_text(self.screen, self.fonts, T.lane_name(lane), 20,
                        (x0 + 110 + lane * 230, top), T.lane_color(lane))

        row_h = 34
        max_rows = max(1, (self.H - top - 60) // row_h)
        # scroll so the selected heat is always visible
        start = max(0, min(self._sched_sel - max_rows // 2, len(heats) - max_rows))
        start = max(0, start)
        visible = heats[start:start + max_rows]
        for i, h in enumerate(visible):
            idx = start + i
            y = top + 32 + i * row_h
            sel = idx == self._sched_sel
            if sel:
                T.rounded_panel(
                    self.screen,
                    pygame.Rect(x0 - 8, y - 4, self.W - 80 - x0 + 8, row_h - 2),
                    T.BG_PANEL, radius=6, border=T.ACCENT,
                )
            tag = "•" if h.completed else "·"
            base = T.GOOD if h.completed else T.FG
            T.draw_text(self.screen, self.fonts, f"{tag} {h.seq}", 22, (x0, y),
                        T.ACCENT if sel else base)
            for lane, rid in enumerate(h.lanes):
                label = "—" if rid is None else self._car_label(racers, rid)
                T.draw_text(self.screen, self.fonts, label, 20,
                            (x0 + 110 + lane * 230, y), T.FG)
        if len(heats) > max_rows:
            T.draw_text(self.screen, self.fonts,
                        f"heat {self._sched_sel + 1} of {len(heats)}", 20,
                        (self.W - 60, top), T.MUTED, right=True)

    def _car_label(self, racers, rid) -> str:
        r = racers.get(rid)
        if not r:
            return "?"
        name = r.name if len(r.name) <= 12 else r.name[:11] + "…"
        return f"#{r.car_number} {name}"

    # ----- race -------------------------------------------------------------
    def _draw_race(self) -> None:
        if self.controller is None or self.cur_heat is None:
            T.draw_text(self.screen, self.fonts, "No active heat.", 30,
                        (self.W // 2, self.H // 2), T.MUTED, center=True)
            return
        st = self.controller.state
        if st in (RaceState.STAGING, RaceState.COUNTDOWN,
                  RaceState.ARMED, RaceState.RUNNING):
            self._draw_race_track()
        if self.controller.show_tree():
            self._draw_tree()
        if st is RaceState.FINISHED:
            self._draw_heat_result()

    def _phase_title(self) -> str:
        if self.cur_phase == FINAL:
            return "CHAMPIONSHIP FINAL"
        return "QUALIFYING"

    def _draw_race_track(self) -> None:
        racers = self.db.racers_by_id()
        heat = self.cur_heat
        ctrl = self.controller
        assert heat and ctrl
        T.draw_text(self.screen, self.fonts,
                    f"{self._phase_title()}  ·  Heat {heat.seq}", 40, (40, 28),
                    T.ACCENT if self.cur_phase == FINAL else T.FG)

        if ctrl.state is RaceState.STAGING:
            T.draw_text(self.screen, self.fonts, "Press  SPACE  to start",
                        30, (self.W - 40, 48), T.GOOD, right=True)
        elif ctrl.state is RaceState.ARMED:
            T.draw_text(self.screen, self.fonts, "GREEN — RELEASE THE CARS!",
                        34, (self.W - 40, 48), T.GREEN, right=True)
            T.draw_text(self.screen, self.fonts,
                        "timing starts when the first car trips the start beam",
                        20, (self.W - 40, 92), T.MUTED, right=True)
        elif ctrl.state is RaceState.RUNNING:
            T.draw_text(self.screen, self.fonts, f"{ctrl.running_clock():5.2f}s",
                        40, (self.W - 40, 48), T.GREEN, right=True)
            if ctrl.awaiting_end_confirm():
                T.draw_text(self.screen, self.fonts,
                            "TAP SPACE AGAIN TO END HEAT (unfinished = DNF)", 22,
                            (self.W - 40, 92), T.RED, right=True)
            else:
                T.draw_text(self.screen, self.fonts,
                            "Double-tap SPACE to end heat (unfinished = DNF)", 20,
                            (self.W - 40, 92), T.MUTED, right=True)

        lanes = self.cfg.race.lanes
        top = 130
        lane_h = (self.H - top - 104) // lanes      # leave room for the "up next" bar
        for lane in range(lanes):
            y = top + lane * lane_h
            rid = heat.lanes[lane] if lane < len(heat.lanes) else None
            color = T.lane_color(lane)
            panel = pygame.Rect(40, y + 6, self.W - 80, lane_h - 12)
            T.rounded_panel(self.screen, panel, T.BG_PANEL, border=color, width=3)

            # lane color badge, labelled with the lane's color name
            badge_w = 170
            pygame.draw.rect(self.screen, color,
                             pygame.Rect(40, y + 6, badge_w, lane_h - 12),
                             border_top_left_radius=14, border_bottom_left_radius=14)
            T.draw_text(self.screen, self.fonts, T.lane_name(lane), 34,
                        (40 + badge_w // 2, y + lane_h // 2), T.text_on(color),
                        center=True)

            if rid is None:
                T.draw_text(self.screen, self.fonts, "(empty lane)", 30,
                            (235, y + lane_h // 2 - 18), T.MUTED)
                continue
            r = racers[rid]
            T.draw_text(self.screen, self.fonts, f"#{r.car_number}", 40,
                        (235, y + lane_h // 2 - 22), color)
            T.draw_text(self.screen, self.fonts, r.name, 40,
                        (375, y + lane_h // 2 - 22), T.FG)

            # live time
            t = ctrl.lane_time(lane)
            if t is not None:
                T.draw_text(self.screen, self.fonts, T.fmt_time(t), 44,
                            (self.W - 70, y + lane_h // 2), T.GREEN, right=True)
            elif ctrl.state is RaceState.RUNNING:
                T.draw_text(self.screen, self.fonts, "…", 44,
                            (self.W - 70, y + lane_h // 2), T.MUTED, right=True)

        self._draw_up_next()

        if self.hw.is_mock and ctrl.state is RaceState.ARMED:
            T.draw_text(self.screen, self.fonts,
                        "[mock] press SPACE to trip the start beam", 16,
                        (self.W // 2, self.H - 16), T.MUTED, center=True)
        elif self.hw.is_mock and ctrl.state is RaceState.RUNNING:
            T.draw_text(self.screen, self.fonts,
                        "[mock] press 1-%d as cars cross the line" % lanes, 16,
                        (self.W // 2, self.H - 16), T.MUTED, center=True)

    def _next_heat_preview(self) -> Heat | None:
        """The next pending heat in the current phase, for the 'up next' bar."""
        if self.cur_heat is None:
            return None
        for h in self.db.get_heats(self.cur_phase):
            if h.seq > self.cur_heat.seq and not h.completed:
                return h
        return None

    def _draw_up_next(self, y: int | None = None) -> None:
        if y is None:
            y = self.H - 92
        bar = pygame.Rect(40, y, self.W - 80, 46)
        T.rounded_panel(self.screen, bar, T.BG_PANEL, radius=10)
        nxt = self._next_heat_preview()
        if nxt is None:
            tail = ("playoffs next" if self.cur_phase == QUALIFYING and self.finalists > 0
                    else "champion next" if self.cur_phase == FINAL else "last heat")
            T.draw_text(self.screen, self.fonts, f"UP NEXT  —  {tail}", 20,
                        (60, y + 12), T.MUTED)
            return
        T.draw_text(self.screen, self.fonts, f"UP NEXT · Heat {nxt.seq}", 20,
                    (60, y + 12), T.ACCENT)
        racers = self.db.racers_by_id()
        x0 = 320
        span = (self.W - 80 - x0) // max(1, self.cfg.race.lanes)
        for lane, rid in nxt.occupied():
            r = racers.get(rid)
            if r is None:
                continue
            cxp = x0 + lane * span
            pygame.draw.circle(self.screen, T.lane_color(lane), (cxp + 9, y + 23), 9)
            name = r.name if len(r.name) <= 10 else r.name[:9] + "…"
            T.draw_text(self.screen, self.fonts, f"#{r.car_number} {name}", 20,
                        (cxp + 26, y + 12), T.FG)

    def _draw_tree(self) -> None:
        """Drag-strip Christmas tree overlay during the countdown."""
        ctrl = self.controller
        assert ctrl
        cx = self.W // 2
        if self.cfg.countdown.style == "numeric":
            num = ctrl.countdown_number()
            txt = "GO!" if num == 0 else str(num)
            col = T.GREEN if num == 0 else T.AMBER
            T.draw_text(self.screen, self.fonts, txt, 260, (cx, self.H // 2),
                        col, center=True)
            return

        lit = ctrl.amber_stages_lit()
        green = ctrl.green_lit()
        n = ctrl.segments                                   # amber bulbs
        green_count = max(1, self.cfg.countdown.green_lights)
        bulbs = n + green_count                             # ambers + greens

        # Scale the bulb size / spacing so the whole tree always fits vertically.
        avail = self.H - 140              # leave top/bottom margin
        slot = avail / bulbs
        r = int(min(slot * 0.42, self.W * 0.06))
        top = int((self.H - slot * (bulbs - 1)) / 2)

        # backing pole
        pole = pygame.Rect(
            cx - r - 18, top - r - 14,
            (r + 18) * 2, int(slot * (bulbs - 1)) + r * 2 + 28,
        )
        T.rounded_panel(self.screen, pole, (8, 9, 14), radius=20, border=T.BG_PANEL)

        # amber bulbs (light from the top down)
        for i in range(n):
            y = int(top + i * slot)
            on = lit > i and not green
            pygame.draw.circle(self.screen, T.AMBER if on else T.DARK_BULB, (cx, y), r)
            pygame.draw.circle(self.screen, (0, 0, 0), (cx, y), r, 3)
        # green bulbs at the bottom (all light together on go)
        for g in range(green_count):
            gy = int(top + (n + g) * slot)
            pygame.draw.circle(self.screen, T.GREEN if green else T.DARK_BULB, (cx, gy), r)
            pygame.draw.circle(self.screen, (0, 0, 0), (cx, gy), r, 3)

    def _draw_heat_result(self) -> None:
        racers = self.db.racers_by_id()
        results = self.controller.results()
        winner = heat_winner(results)
        T.draw_text(self.screen, self.fonts,
                    f"{self._phase_title()}  ·  Heat {self.cur_heat.seq} Results",
                    40, (self.W // 2, 50), T.FG, center=True)

        ranked = sorted(
            results,
            key=lambda r: (r.time_s if r.finished else float("inf")),
        )
        top = 130
        row_h = (self.H - top - 175) // max(1, len(ranked))
        row_h = min(row_h, 130)
        for i, res in enumerate(ranked):
            y = top + i * row_h
            r = racers[res.racer_id]
            is_win = winner is not None and res.lane == winner.lane
            lane_col = T.lane_color(res.lane)
            panel = pygame.Rect(self.W // 2 - 460, y, 920, row_h - 14)
            # the winner is highlighted in ITS OWN lane colour (thicker border)
            T.rounded_panel(self.screen, panel, T.BG_PANEL, border=lane_col,
                            width=5 if is_win else 2)
            place = ("• " if is_win else "") + f"{i + 1}"
            T.draw_text(self.screen, self.fonts, place, 40,
                        (panel.x + 24, y + row_h // 2 - 22),
                        lane_col if is_win else T.FG)
            T.draw_text(self.screen, self.fonts,
                        T.lane_name(res.lane), 24,
                        (panel.x + 110, y + row_h // 2 - 12), lane_col)
            T.draw_text(self.screen, self.fonts, f"#{r.car_number} {r.name}", 36,
                        (panel.x + 250, y + row_h // 2 - 20), T.FG)
            col = lane_col if is_win else (T.GREEN if res.finished else T.BAD)
            T.draw_text(self.screen, self.fonts, T.fmt_time(res.time_s, res.dnf), 44,
                        (panel.right - 30, y + row_h // 2), col, right=True)

        if not self._single_heat_mode:
            self._draw_up_next(self.H - 150)

        accept = "Enter = save & return" if self._single_heat_mode \
            else "SPACE / Enter = next heat"
        T.draw_text(self.screen, self.fonts,
                    f"{accept}        R = re-run this heat", 24,
                    (self.W // 2, self.H - 40), T.GOOD, center=True)

    # ----- standings --------------------------------------------------------
    def _draw_standings(self) -> None:
        self._header("Standings",
                     f"Ranked by {score_label(self.scoring)} · Esc back")
        racers = self.db.racers_by_id()
        results = self.db.get_results(QUALIFYING)
        if not results:
            T.draw_text(self.screen, self.fonts, "No results yet.", 28,
                        (40, 160), T.MUTED)
            return
        standings = compute_standings(
            racers, results, self.cfg.race.lanes, self.cfg.race.dnf_penalty_s,
            method=self.scoring,
        )
        top = 150
        T.draw_text(self.screen, self.fonts, "Rank", 20, (40, top), T.MUTED)
        T.draw_text(self.screen, self.fonts, "Car", 20, (140, top), T.MUTED)
        T.draw_text(self.screen, self.fonts, column_label(self.scoring), 20,
                    (self.W - 360, top), T.MUTED)
        T.draw_text(self.screen, self.fonts, "Best", 20, (self.W - 200, top), T.MUTED)
        T.draw_text(self.screen, self.fonts, "Runs", 20, (self.W - 90, top), T.MUTED)

        max_rows = max(1, (self.H - top - 80) // 40)
        for i, st in enumerate(standings[:max_rows]):
            y = top + 34 + i * 40
            in_finals = i < self.finalists
            color = T.ACCENT if i == 0 else (T.FG if in_finals else T.MUTED)
            medal = ("• " if i == 0 else "") + f"{st.rank}"
            T.draw_text(self.screen, self.fonts, str(medal), 28, (44, y), color)
            T.draw_text(self.screen, self.fonts,
                        f"#{st.racer.car_number} {st.racer.name}", 28, (140, y), color)
            T.draw_text(self.screen, self.fonts, format_score(st, self.scoring), 26,
                        (self.W - 360, y), color)
            T.draw_text(self.screen, self.fonts,
                        f"{st.best_s:.3f}" if st.best_s else "—", 26,
                        (self.W - 200, y), color)
            T.draw_text(self.screen, self.fonts,
                        f"{st.finishes}/{st.runs}", 26, (self.W - 90, y), color)

        if self.finalists > 0:
            fmt = "single final heat" if self.finals_format == "single" else "rotation playoff"
            note = f"Top {self.finalists} (bright) advance to the {fmt}"
        else:
            note = "Playoffs off — qualifying decides the winner"
        T.draw_text(self.screen, self.fonts, note, 20, (40, self.H - 30), T.MUTED)

    # ----- champion ---------------------------------------------------------
    def _draw_champion(self) -> None:
        racers = self.db.racers_by_id()
        # Prefer finals results if present, else qualifying.
        phase = FINAL if self.db.phase_has_schedule(FINAL) else QUALIFYING
        results = self.db.get_results(phase)
        if not results:
            self._header("Champion")
            T.draw_text(self.screen, self.fonts, "No results yet.", 28, (40, 160), T.MUTED)
            return
        standings = compute_standings(
            racers, results, self.cfg.race.lanes, self.cfg.race.dnf_penalty_s,
            method=self.scoring,
        )
        cx = self.W // 2
        champ = standings[0]
        # colour the winner by the lane of their fastest run
        champ_lane = self._racer_best_lane(champ.racer.id)
        champ_color = T.lane_color(champ_lane) if champ_lane is not None else T.ACCENT

        # animated glow, tinted to the champion's lane colour
        t = pygame.time.get_ticks() / 1000.0
        f = (40 + 30 * (1 + math.sin(t * 3)) / 2) / 255.0
        pygame.draw.rect(self.screen, tuple(int(c * f) for c in champ_color),
                         pygame.Rect(0, 0, self.W, 150))
        T.draw_text(self.screen, self.fonts, "•  CHAMPION  •", 70, (cx, 80),
                    champ_color, center=True)

        T.draw_text(self.screen, self.fonts,
                    f"#{champ.racer.car_number}  {champ.racer.name}", 84,
                    (cx, 260), champ_color, center=True)
        if self.scoring == "points":
            sub = f"{champ.points} place-points" + (
                f"   ·   best {champ.best_s:.3f}s" if champ.best_s else "")
        else:
            sub = (f"{score_label(self.scoring).lower()} "
                   f"{format_score(champ, self.scoring)}s"
                   + (f"   ·   best {champ.best_s:.3f}s" if champ.best_s else ""))
        T.draw_text(self.screen, self.fonts, sub, 30, (cx, 330), T.MUTED, center=True)

        # podium 2 & 3
        for i, st in enumerate(standings[1:3], start=2):
            y = 408 + (i - 2) * 52
            medal = "2nd" if i == 2 else "3rd"
            tail = (f"   {st.points} pts" if self.scoring == "points"
                    else f"   {format_score(st, self.scoring)}s")
            T.draw_text(self.screen, self.fonts,
                        f"{medal}  #{st.racer.car_number} {st.racer.name}{tail}",
                        32, (cx, y), T.FG, center=True)

        # fastest single runs of the whole event
        fast = self._fastest_runs(3)
        if fast:
            fy = 530
            T.draw_text(self.screen, self.fonts, "Fastest Runs", 24,
                        (cx, fy), T.ACCENT, center=True)
            for i, (t, rid, lane) in enumerate(fast):
                r = racers[rid]
                line = (f"{i + 1}.  {t:.3f}s   #{r.car_number} {r.name}"
                        f"   ·   {T.lane_name(lane)}")
                T.draw_text(self.screen, self.fonts, line, 24,
                            (cx, fy + 34 + i * 32),
                            T.ACCENT if i == 0 else T.FG, center=True)

        T.draw_text(self.screen, self.fonts, "Press Enter to return", 22,
                    (cx, self.H - 28), T.MUTED, center=True)

    def _racer_best_lane(self, racer_id: int) -> int | None:
        """Lane of a racer's fastest finished run (their 'home' lane), or None."""
        best_t = None
        best_lane = None
        for phase in (QUALIFYING, FINAL):
            for res in self.db.get_results(phase):
                if (res.racer_id == racer_id and res.finished
                        and res.time_s is not None
                        and (best_t is None or res.time_s < best_t)):
                    best_t = res.time_s
                    best_lane = res.lane
        return best_lane

    def _fastest_runs(self, n: int = 3) -> list[tuple[float, int, int]]:
        """The n fastest finished single runs across the whole event.

        Returns (time_s, racer_id, lane) sorted fastest first.
        """
        racers = self.db.racers_by_id()
        runs: list[tuple[float, int, int]] = []
        for phase in (QUALIFYING, FINAL):
            for res in self.db.get_results(phase):
                if res.finished and res.time_s is not None and res.racer_id in racers:
                    runs.append((res.time_s, res.racer_id, res.lane))
        runs.sort(key=lambda x: x[0])
        return runs[:n]

    # ----- confirm reset ----------------------------------------------------
    def _draw_confirm_reset(self) -> None:
        cx, cy = self.W // 2, self.H // 2
        T.draw_text(self.screen, self.fonts, "Reset the event?", 50, (cx, cy - 60),
                    T.FG, center=True)
        T.draw_text(self.screen, self.fonts,
                    "Clears all heats and results. Roster of racers is kept.",
                    26, (cx, cy), T.MUTED, center=True)
        T.draw_text(self.screen, self.fonts, "Y = reset      N = cancel", 30,
                    (cx, cy + 70), T.ACCENT, center=True)


def main(cfg: Config | None = None) -> None:
    from ..config import load_config
    app = App(cfg or load_config())
    app.run()


if __name__ == "__main__":
    sys.exit(main())
