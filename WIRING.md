# Grand Prix RPi — Wiring Guide

Wiring for the **default configuration**: a 4-lane track, manual start gate, no
servo, and the wireless keyboard as the only control. Timing uses IR
**break-beam** pairs (e.g. Adafruit #2167) at the start and finish lines.

> ⚠️ **The Raspberry Pi GPIO is 3.3 V and NOT 5 V tolerant.** Power the
> **receivers from 3.3 V** — their open-collector signal, held up by the Pi's
> internal 3.3 V pull-up (which the software enables), then never exceeds 3.3 V.
> The **emitters are just IR LEDs with no connection to a GPIO**, so they can run
> from **5 V** for a brighter, longer-range beam (nice over a long cable). Always
> use a **common ground**.

## What the software expects

- **4 lanes**, named by color in pin order: **Red, Blue, Green, Yellow**.
- **Start mode `sensor`** — a person releases the cars on green; the **first**
  start-line beam to break starts the shared clock (`config.toml` →
  `start_mode = "sensor"`).
- **`finish_active_low = false`** — break-beam output is LOW while the beam is
  intact and goes HIGH when a car breaks it (true for Adafruit 2167-style
  receivers). For reflective LM393 modules instead, set this `true`.
- **No servo, no physical button** — `SPACE` on the keyboard starts/ends races.
  (Re-enable either via `config.toml`; see the bottom of this doc.)

## Bill of materials

| Qty | Part | Notes |
|----|------|-------|
| 1  | Raspberry Pi 4 or 3 B + power supply | Pi OS Bookworm (Lite is fine) |
| 1  | HDMI display | the race/results screen |
| 1  | USB wireless keyboard | all control (keep the dongle plugged in) |
| 4  | IR break-beam pair — **finish line** | e.g. Adafruit #2167 (3 mm) |
| 4  | IR break-beam pair — **start line** | same part |
| 2  | Cat6 cable runs | one to the finish bar, one to the start bar |
| —  | emitter series resistors sized for **5 V** | ≈150–220 Ω (~20 mA); per Adafruit's guide |

## Pin map (BCM → physical pin on the 40-pin header)

| Function | Lane | BCM | Physical pin |
|----------|------|-----|--------------|
| Finish sensor | Red    | GPIO 5  | 29 |
| Finish sensor | Blue   | GPIO 6  | 31 |
| Finish sensor | Green  | GPIO 13 | 33 |
| Finish sensor | Yellow | GPIO 19 | 35 |
| Start sensor  | Red    | GPIO 22 | 15 |
| Start sensor  | Blue   | GPIO 23 | 16 |
| Start sensor  | Green  | GPIO 24 | 18 |
| Start sensor  | Yellow | GPIO 25 | 22 |
| 3.3 V power (receivers) | — | 3V3 | 1 (and 17) |
| 5 V power (emitters)    | — | 5V  | 2 (and 4) |
| Ground        | —      | GND     | 6, 9, 14, 20, 25, 30, 34, 39 |

Pin numbers come from `config.toml` (`finish_pins`, `start_pins`); change them
there if you wire differently. Each list must have exactly 4 entries, in lane
order Red→Blue→Green→Yellow.

> **Pi 4 or Pi 3 B?** Either works — the 40-pin header, pinout, and 3.3 V logic
> are identical, so this wiring is unchanged. On a Pi 3 B: use Raspberry Pi OS
> Bookworm (default `vc4-kms-v3d` KMS driver) for the no-desktop fullscreen
> path; animations may run at a lower FPS (race timing is unaffected — lower
> `display.fps` in `config.toml` if needed); and if the 3.3 V rail seems
> marginal with 8 sensor pairs, power the emitter LEDs from 5 V (the receiver
> signal stays Pi-safe). The Pi 3 B uses a full-size HDMI cable (vs the Pi 4's
> micro-HDMI).

## Wiring each break-beam pair

An IR break-beam pair has an **emitter** (IR LED) and a **receiver** (3 wires).

**Receiver** — runs at 3.3 V so its signal stays Pi-safe (colors match Adafruit
2167; check your part):
- red → **3.3 V** (pin 1 or 17)
- black → **GND**
- white (signal) → the lane's **GPIO** (from the table above)

**Emitter** — an IR LED with no GPIO connection, so run it at **5 V** for a
stronger beam:
- through its current-limiting resistor (sized for 5 V, ≈150–220 Ω) → **5 V**
  (pin 2 or 4)
- other leg → **GND**

You do **not** add an external pull-up for short runs — the software enables the
Pi's internal pull-up on every sensor input. (For long cable runs, see Cabling.)

```
  Pi 5V   (pin 2/4)  ───────────────────────────► emitter (+ via resistor)
  Pi 3.3V (pin 1/17) ───────────────────────────► receiver red (power)
  Pi GND  ──┬────────────► receiver black ───────► emitter (–)
  Pi GPIOx ◄────────────── receiver white (signal)
```

## Cabling with Cat6

Cat6 is a great fit for the runs to the start and finish bars — it has **8
conductors (4 twisted pairs)**, easy to terminate, and the tiny sensor currents
mean **voltage drop is a non-issue**.

**One Cat6 run per line** carries everything for all four lanes:

| Conductor | Use |
|-----------|-----|
| 1 | **5 V** — shared by all 4 emitters |
| 1 | **3.3 V** — shared by all 4 receivers |
| 1 | **GND** — common ground |
| 4 | **signal** — one per lane (Red/Blue/Green/Yellow) |
| 1 | spare (use as a second ground if you like) |

So a single Cat6 to the finish bar and a single Cat6 to the start bar covers the
whole track (emitters just tap the shared 5 V/GND — they have no signal wire).

**Voltage drop:** each pair draws ~25 mA; Cat6 is ~0.026 Ω/ft. Even a 25 ft run
sharing one power conductor for 4 lanes (~0.1 A) drops only ~0.1 V — negligible,
and the parts are happy from 3–5 V anyway. You'd need *hundreds* of feet to care.

**Signal integrity (matters more than drop on long runs):**
- Run each **signal wire twisted with a ground/return** — that's what rejects
  noise. Keep a solid common ground.
- The internal pull-up is weak (~50 kΩ). For runs longer than ~15–20 ft, add an
  external **~4.7 kΩ pull-up from each signal to 3.3 V at the Pi end** for crisp
  edges. Short runs don't need it.
- The Adafruit 2167 beams are **modulated (38 kHz)**, so they already shrug off
  ambient light and cable noise.
- If you ever see occasional false/double triggers, the software debounces 5 ms;
  that can be increased.

### Cat6 pinout (T568B) — wire both cables the same

Lane colours are matched to cable colours where possible; the exact-match lanes
(Blue, Green) get true ground returns, and the power rails ride the white-stripe
conductors.

| RJ45 pin | Cat6 wire (T568B) | Carries |
|---|---|---|
| 1 | White/Orange | **3.3 V** (receiver power) |
| 2 | Orange       | Signal — **Red** lane |
| 3 | White/Green  | **GND** |
| 4 | Blue         | Signal — **Blue** lane |
| 5 | White/Blue   | **GND** |
| 6 | Green        | Signal — **Green** lane |
| 7 | White/Brown  | **5 V** (emitter power) |
| 8 | Brown        | Signal — **Yellow** lane |

**Pi end** — power is identical for both cables; only the four signal wires land
on different GPIOs:

| Cat6 wire | Finish cable | Start cable |
|---|---|---|
| White/Orange (3.3 V) | 3.3 V — phys pin 1  | 3.3 V — phys pin 17 |
| White/Brown (5 V)    | 5 V — phys pin 2    | 5 V — phys pin 4 |
| White/Green + White/Blue (GND) | GND (tie both) | GND (tie both) |
| Orange  → Red    | GPIO 5  — phys 29 | GPIO 22 — phys 15 |
| Blue    → Blue   | GPIO 6  — phys 31 | GPIO 23 — phys 16 |
| Green   → Green  | GPIO 13 — phys 33 | GPIO 24 — phys 18 |
| Brown   → Yellow | GPIO 19 — phys 35 | GPIO 25 — phys 22 |

**Track end (sensor bar)** — fan the one cable out to all 4 emitters + receivers:

- **White/Brown (5 V)** → each **emitter** (+) through its 5 V resistor
- **White/Orange (3.3 V)** → each **receiver** red (VCC)
- **White/Green + White/Blue (GND)** → every emitter (−) **and** every receiver
  black (all common)
- **Orange / Blue / Green / Brown** → the **signal (white) lead** of the
  Red / Blue / Green / Yellow receiver, respectively

> For long runs (>~15–20 ft) optionally add a ~4.7 kΩ pull-up from each signal
> wire to 3.3 V at the Pi end.

## Mounting (4 lanes side by side)

Use **one independent beam per lane** so each beam only crosses its own lane —
a single beam spanning all 4 lanes can't tell which car finished.

- **Best: vertical beams.** Emitter above the lane, receiver in/under the track
  at the line, beam pointing straight down. The car breaks only its lane's beam.
- **Alternative: horizontal**, emitter on one lane divider and receiver on the
  next, at car-body height, with the dividers blocking IR from neighbor lanes.
- Put the **finish** beam right at the finish line and the **start** beam just
  past the gate (so the fastest car trips it essentially at release).
- Reduce cross-lane interference with a little shrouding/tube around emitters
  and by keeping beams focused.

## Power & grounding

- All sensors and the Pi share **one common ground** (essential — the signal is
  referenced to it).
- **Receivers → 3.3 V** (pin 1/17), **emitters → 5 V** (pin 2/4). Eight low-power
  IR pairs are well within the Pi's rails; if you ever add many more, use a
  separate supply (still common ground).
- Only the **receiver signal** touches a GPIO, and it's clamped to 3.3 V by the
  internal pull-up — that's why receiver power is 3.3 V and emitter power (no GPIO
  link) can safely be 5 V.

## Quick bring-up test

1. Boot, run the app (`.venv/bin/python main.py`).
2. Verify the display driver: `.venv/bin/python -c "import pygame;
   pygame.display.init(); print(pygame.display.get_driver())"` → `kmsdrm`.
3. Build a tiny schedule, start a heat (`SPACE`), and wave your hand through
   each **start** beam — the clock should start on the first one.
4. Wave through each **finish** beam — the matching lane (Red/Blue/Green/Yellow)
   should record a time.
5. If a lane never registers, flip `finish_active_low` and re-test that wiring.

## Optional: servo gate or a physical button

Both are off by default but supported:

- **Servo start gate** — set `start_mode = "servo"` and wire the servo signal to
  **GPIO 17 (physical 11)**. **Power the servo from its own 5 V supply** with a
  common ground — don't run it off the Pi's 5 V rail.
- **Physical start button** — set `start_button_enabled = true` and wire a
  momentary button from **GPIO 27 (physical 13)** to **GND** (internal pull-up).
  It does exactly what `SPACE` does.
