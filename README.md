# Grand Prix RPi 🏁

A self-contained **pinewood derby race system** for a Raspberry Pi (4 or 3 B). Enter
racers, auto-build a fair heat schedule where every car runs in every lane,
run the races with a real start gate + finish-line timing, and crown a
champion — all on an HDMI display driven by a single fullscreen app.

## What it does

- **Roster entry** — type each racer's name and car number.
- **Fair scheduling** — generates a rotation so **every car runs once in each
  lane**, cancelling out fast/slow lanes. Cars are then ranked by their
  *average* time across all lanes.
- **Configurable playoffs** — after qualifying, send the top **None / 4 / 8**
  cars to a playoff, run either as a fair **rotation** (each runs every lane) or
  a **single** winner-take-all final heat. Set in **Settings**.
- **Race mode** on HDMI:
  - shows each lane with car number + name,
  - pressing **`SPACE`** (keyboard — or an optional hardware button) kicks off a
    drag-strip **light tree** (5 amber bulbs counting down to 2 green — bulb
    counts and speed are all configurable) — or a numeric countdown,
  - two start modes (`start_mode` in config):
    - **`sensor`** (default, no servo needed): on green a person releases the
      cars, and the clock (t0) starts when the **first start-line IR sensor**
      is tripped — that t0 is shared by all lanes,
    - **`servo`**: the servo releases the gate automatically on green and t0 is
      the release moment,
  - an **UP NEXT** bar shows the on-deck heat's cars so the next racers can
    line up,
  - **break-beam sensors** time each lane at the finish,
  - results show every lane's time with the **winner highlighted**, and a
    gold **champion screen** at the end.
- **Selectable scoring** — rank by average time, drop-worst average, best
  single run, total time, or place-points (timing-tolerant). Changeable live in
  **Settings**.
- **Adjustable schedule density** — single rotation (once per lane), double
  rotation (twice per lane), or a reduced/faster schedule for big fields.
- **Save / load rosters** — store a derby's racers (names + car numbers) to a
  named JSON file and reload it later, so you can keep multiple events on one
  Pi or move a roster between machines on a USB stick.
- **Autosave & resume** — roster, schedule, every accepted heat result, and all
  settings are written to `derby.db` as they happen. If the app exits or the Pi
  loses power, relaunch and pick **Resume Race** to continue at the next
  unfinished heat — the menu shows where you left off (e.g. "Qualifying 6/25").
- **Self-contained** — SQLite database, no network needed. Runs fullscreen
  straight to the TV.

## Hardware

You supply the hardware; the software expects this interface (all pins are
**BCM GPIO** numbers, configurable in `config.toml`). **See
[`WIRING.md`](WIRING.md)** for the full wiring guide — pin map with physical
pin numbers, per-sensor hookup, mounting, power/grounding, and a bring-up test.

| Function            | Default pin | Notes |
|---------------------|-------------|-------|
| Finish — Red/Blue/Green/Yellow | GPIO 5,6,13,19 | One IR sensor per lane (lanes are named by color, in `finish_pins` order). Through-beam (e.g. Adafruit 2167): high when the car breaks the beam → `finish_active_low = false`. Reflective LM393 module: low on detect → `finish_active_low = true`. |
| Start-line — Red/Blue/Green/Yellow | GPIO 22,23,24,25 | `start_mode = "sensor"` only. Same sensor type as the finish line; the first one tripped starts the shared clock. |
| Start button        | *(optional)* GPIO 27 | **Off by default** — the keyboard `SPACE` key starts/ends races. Wire one and set `start_button_enabled = true` only if you want a physical button. |
| Start gate servo    | GPIO 17     | `start_mode = "servo"` only. Hobby servo signal wire. **Power the servo from its own 5V supply** with a common ground — don't run it off the Pi's 5V rail. |

Wiring tips:
- Give every device a **common ground** with the Pi.
- Break-beam receivers usually have VCC/GND/OUT — OUT goes to the lane's GPIO.
- For the servo, a small buck converter or 4×AA pack on a shared ground works
  well; jitter is fine for a start gate.

## Install (on the Pi)

Flash **Raspberry Pi OS Lite (Bookworm)** — "Lite" (no desktop) is what you
want; 64-bit is fine (32-bit also works). Then on the Pi:

```bash
git clone <this repo> grand-prix-rpi   # or copy the folder over
cd grand-prix-rpi
./install.sh
```

`install.sh` installs `python3-pygame` + `lgpio` from apt, creates a
`--system-site-packages` venv, and adds you to the `video/render/input/gpio`
groups. Log out/in once, then:

```bash
.venv/bin/python main.py
```

### No desktop required (Raspberry Pi OS Lite)

It runs fullscreen on the **Lite** image with **no X11/Wayland** — SDL renders
straight to the HDMI display via the kernel's **KMSDRM** driver. `main.py`
selects `SDL_VIDEODRIVER=kmsdrm` automatically when it sees no desktop; force it
with `--video kmsdrm` if needed.

Requirements for the headless path:
- The default KMS display driver (`dtoverlay=vc4-kms-v3d`, already on).
- The **Mesa GL/EGL drivers** (`libgl1-mesa-dri libegl1 libegl-mesa0 libgles2`) —
  Pi OS **Lite** omits these, and SDL's kmsdrm backend renders through EGL, so
  without them you get `pygame.error: egl not initialized`. `install.sh` installs
  them.
- Your user in the **`video`** and **`render`** groups (install.sh does this).
- **Run it from the Pi's own console** (the local HDMI/keyboard, or the systemd
  unit below) — *not* over SSH. KMSDRM needs to own the display, which an SSH
  session can't grant.

Sanity-check the driver is available:

```bash
.venv/bin/python -c "import pygame; pygame.display.init(); print(pygame.display.get_driver())"
# prints: kmsdrm
```

### Troubleshooting the display (Pi OS Lite)

Two gotchas on a fresh **Lite** image, both handled automatically now but worth
knowing:

- **`pygame.error: egl not initialized`** — Lite ships without the Mesa GL/EGL
  drivers. Fix: `sudo apt-get install -y libgl1-mesa-dri libegl1 libegl-mesa0
  libgles2` (now in `install.sh`).
- **Service runs but the screen is blank/black (no error)** — SDL picked its
  desktop-OpenGL renderer, but the Pi's vc4/v3d GPU is OpenGL **ES** only, so
  every draw is a silent no-op. Fix: run with `SDL_RENDER_DRIVER=opengles2`
  (`main.py` sets this automatically whenever the kmsdrm path is used).

Quick checks on the Pi:
```bash
# GL/EGL drivers present? (should list v3d_dri.so / vc4_dri.so and libEGL*)
ls /usr/lib/aarch64-linux-gnu/dri/ | grep -E 'v3d|vc4'; ls /usr/lib/aarch64-linux-gnu/ | grep libEGL
# minimal red/green/blue display test on the console (tty1):
SDL_VIDEODRIVER=kmsdrm SDL_RENDER_DRIVER=opengles2 python3 test_display.py
```

### Auto-start on boot

`install.sh` sets this up automatically — it generates a systemd unit with
*your* user and repo path and enables it, so the app launches fullscreen on
every boot (KMSDRM on tty1). Skip it with `./install.sh --no-autostart`.

Manage it with:

```bash
sudo systemctl start grand-prix.service     # start now (also starts on boot)
sudo systemctl stop grand-prix.service       # stop
sudo systemctl disable grand-prix.service    # don't start on boot
journalctl -u grand-prix.service -b          # view logs
```

To run on a **full desktop** instead of the console, see the comment block in
the bundled `grand-prix.service` (drop `SDL_VIDEODRIVER`, set `DISPLAY=:0`,
target `graphical.target`).

## Develop on a laptop (no Pi / no hardware)

```bash
python3 -m pip install -r requirements.txt   # pygame-ce only
python3 main.py --windowed --mock
```

In `--mock` mode the keyboard stands in for the hardware:

| Key            | Acts as |
|----------------|---------|
| `SPACE`        | start control: begins the countdown; in `sensor` mode also starts the clock in ARMED; **double-tap during a race** ends the heat early (any car that hasn't crossed = DNF) |
| `1`–`4`        | a car crossing the finish line in that lane |
| `↑ ↓ / Enter`  | menu navigation / confirm |
| `Esc`          | back to menu |
| `Tab`          | switch name/number field on the roster screen |
| `Del`          | delete the selected racer |

## Configuration

All tunables live in [`config.toml`](config.toml): lane count, finalist count,
DNF timeout, servo positions, GPIO pins, countdown style, display size. The
finish-pin list length must equal `race.lanes`.

## Scheduling & scoring

**Scheduling** (`pinewood/scheduling.py`): for *N* cars and *L* lanes, each lane
gets a distinct cyclic offset spread around the field; heat *h* puts car
`(h + offset[lane]) % N` in each lane. Over *N* heats every car lands in every
lane exactly once. The `runs_per_car` setting controls density:

| `runs_per_car` | Result |
|---|---|
| `0` (default) | once per lane — single rotation, *N* heats |
| `2 × lanes` | twice per lane — double rotation, *2N* heats (more data) |
| `< lanes` | reduced/faster — each car runs ~that many lanes |

**Scoring** (`pinewood/ranking.py`) — pick the method in **Settings** or
`config.toml`:

| Method | Ranks by |
|---|---|
| `average` *(default)* | mean of all runs |
| `drop_worst` | mean after dropping each car's slowest run |
| `best` | single fastest run |
| `total` | sum of runs (same order as average under a full rotation) |
| `points` | finish-place points per heat, summed (low wins; timing-tolerant) |

A DNF is charged `dnf_penalty_s` for time methods, or worst-place for `points`.
Changes in Settings are saved in the database and persist across restarts;
schedule-density changes apply the next time you build the schedule.

## Project layout

```
main.py                  entry point (--windowed, --mock, --config)
config.toml              all hardware + race settings
pinewood/
  config.py              typed config loader
  models.py              Racer / Heat / LaneResult / Standing
  scheduling.py          fair lane-rotation + finals
  ranking.py             averages + standings + heat winner
  roster.py              save/load roster JSON files
  db.py                  SQLite persistence
  race.py                single-heat controller (countdown, timing, DNF)
  hardware/
    base.py              backend interface (callbacks + gate)
    mock.py              keyboard backend for development
    gpio.py              real gpiozero backend (servo, button, break-beams)
  ui/
    app.py               pygame screen state machine
    theme.py             colors, fonts, drawing helpers
tests/
  test_scheduling.py     fairness + rotation-density tests
  test_scoring.py        scoring-method tests (average/drop-worst/best/total/points)
  test_roster.py         roster save/load + DB replace tests
  test_countdown.py      light-tree timing (every amber lights before green)
  test_persistence.py    restart/resume: fresh app on the same DB continues
  smoke_app.py           headless full-event run (dummy SDL driver)
```

## Tests

```bash
# logic suites (scheduling, scoring, roster, countdown)
for m in test_scheduling test_scoring test_roster test_countdown; do
  python3 -c "import tests.$m as t; [getattr(t,n)() for n in dir(t) if n.startswith('test_')]; print('$m ok')"
done
# restart/resume test (a fresh app on the same DB continues the event)
python3 tests/test_persistence.py
# full app, headless (boots the UI, runs a whole event under the dummy SDL driver)
python3 tests/smoke_app.py
```

## Operating a race day

1. **Manage Racers** — add everyone. (Or **Save / Load Roster** → load a
   previously saved event.)
2. **Build Schedule** — generates qualifying heats (rebuild clears results).
3. **Race!** — for each heat: press **`SPACE`** → light tree → **green**.
   In `sensor` mode a person releases the cars on green and the clock starts on
   the first start-line beam; in `servo` mode the gate drops automatically.
   Times appear → press `SPACE` again for the next heat. If a car derails or
   won't reach the line, **double-tap `SPACE` while it's running** to end the
   heat early — every lane that hasn't crossed is scored DNF. (A single press
   just arms the confirm, so a stray tap won't kill a heat; the window is
   `race.end_double_tap_s` in `config.toml`.)
   - **Re-run a heat** if something went wrong: on the results screen press
     **`R`** to discard the times and re-stage the *same* heat before saving.
     To redo a heat you already moved past, go to **Build Schedule**, select it
     with `↑/↓`, and press **`R`** — its old result is cleared and it re-runs,
     then you return to the schedule.
4. After the last qualifying heat the **playoffs** (if enabled in Settings —
   top 4/8, rotation or single heat) are built automatically and run the same
   way, ending on the **champion** screen. With playoffs set to *None*, the
   champion comes straight from the qualifying standings.
5. **Standings** shows live rankings anytime. **Reset Event** clears heats and
   results but keeps your roster.

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE).
Copyright (C) 2026 Steven Southwell.
