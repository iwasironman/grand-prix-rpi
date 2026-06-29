"""Real Raspberry Pi backend using gpiozero.

Wiring (BCM pins from config.toml):
  * start pushbutton         -> hardware.start_button_pin (OPTIONAL; only if
                                start_button_enabled — the keyboard SPACE key
                                does the same job)
  * finish IR sensor x lane  -> hardware.finish_pins[lane]
  * start-line IR sensor x lane (start_mode = "sensor") -> hardware.start_pins[lane]
  * servo signal wire (start_mode = "servo")            -> hardware.servo_pin

The IR sensors all use the same polarity (`finish_active_low`): the internal
pull-up is always on, and the flag chooses which edge is the trip.

Start modes:
  * "sensor" : a human releases the cars on green; the FIRST start-line sensor
               to trip sets t0 for the whole heat.  No servo is used.
  * "servo"  : the servo releases the gate on green and t0 is the release.

NOTE: a hobby servo can draw more current than the Pi's 5V rail likes —
power the servo from a separate 5V supply with a common ground.
"""

from __future__ import annotations

import time

from gpiozero import AngularServo, Button, DigitalInputDevice  # type: ignore


class GpioBackend:
    def __init__(self, cfg, lanes: int):
        self.cfg = cfg
        self.lanes = lanes
        self._on_start = None
        self._on_finish = None
        self._on_start_line = None
        self._timing = False
        self.servo = None

        # --- start gate servo (only in servo mode) -------------------------
        self._closed_angle = cfg.servo_closed * 90.0
        self._open_angle = cfg.servo_open * 90.0
        if cfg.start_mode == "servo":
            # AngularServo takes -90..90; scale the -1..1 config values onto that.
            self.servo = AngularServo(
                cfg.servo_pin,
                min_angle=-90,
                max_angle=90,
                initial_angle=self._closed_angle,
            )

        # --- start button (optional; the keyboard SPACE key always works) --
        self.button = None
        if cfg.start_button_enabled:
            self.button = Button(cfg.start_button_pin, pull_up=cfg.button_pull_up)
            self.button.when_pressed = self._handle_start

        # --- finish sensors ------------------------------------------------
        self.sensors = [
            self._make_sensor(pin, self._make_finish_handler(lane))
            for lane, pin in enumerate(cfg.finish_pins)
        ]

        # --- start-line sensors (sensor mode only) -------------------------
        self.start_sensors = []
        if cfg.start_mode == "sensor":
            self.start_sensors = [
                self._make_sensor(pin, self._make_start_line_handler(lane))
                for lane, pin in enumerate(cfg.start_pins)
            ]

    def _make_sensor(self, pin: int, handler) -> "DigitalInputDevice":
        """Attach a handler on the configured trip edge (shared polarity).

        finish_active_low == true  -> trip on the LOW edge  (reflective modules)
        finish_active_low == false -> trip on the HIGH edge (break-beam, e.g. 2167)
        """
        dev = DigitalInputDevice(pin, pull_up=True, bounce_time=0.005)
        if self.cfg.finish_active_low:
            dev.when_activated = handler
        else:
            dev.when_deactivated = handler
        return dev

    # callbacks
    def on_start(self, cb):
        self._on_start = cb

    def on_finish(self, cb):
        self._on_finish = cb

    def on_start_line(self, cb):
        self._on_start_line = cb

    def _handle_start(self):
        if self._on_start:
            self._on_start()

    def _make_finish_handler(self, lane: int):
        def handler():
            ts = time.perf_counter()
            if self._timing and self._on_finish:
                self._on_finish(lane, ts)
        return handler

    def _make_start_line_handler(self, lane: int):
        def handler():
            ts = time.perf_counter()
            if self._timing and self._on_start_line:
                self._on_start_line(lane, ts)
        return handler

    # gate (no-ops in sensor mode — there is no servo)
    def arm_gate(self):
        if self.servo is not None:
            self.servo.angle = self._closed_angle
            time.sleep(self.cfg.servo_settle_s)

    def release_gate(self):
        if self.servo is not None:
            self.servo.angle = self._open_angle

    # timing window (arms both start-line and finish sensors)
    def begin_timing(self):
        self._timing = True

    def end_timing(self):
        self._timing = False

    def cleanup(self):
        try:
            if self.servo is not None:
                self.servo.angle = self._closed_angle
        finally:
            for s in (*self.sensors, *self.start_sensors):
                s.close()
            if self.button is not None:
                self.button.close()
            if self.servo is not None:
                self.servo.close()

    @property
    def is_mock(self) -> bool:
        return False

    def simulate_start(self):
        pass

    def simulate_finish(self, lane: int):
        pass

    def simulate_start_line(self, lane: int):
        pass
