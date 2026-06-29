"""Load and validate the TOML configuration."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.toml"


@dataclass
class RaceCfg:
    lanes: int = 4
    finalists: int = 4
    finals_format: str = "rotation"
    scoring: str = "average"
    runs_per_car: int = 0
    dnf_timeout_s: float = 12.0
    dnf_penalty_s: float = 9.999
    end_double_tap_s: float = 0.8


@dataclass
class DisplayCfg:
    fullscreen: bool = True
    width: int = 1280
    height: int = 720
    fps: int = 60


@dataclass
class CountdownCfg:
    style: str = "tree"
    segments: int = 5
    green_lights: int = 2
    stage_interval_s: float = 0.6
    green_hold_s: float = 1.0


@dataclass
class HardwareCfg:
    backend: str = "auto"
    start_mode: str = "sensor"
    start_pins: list[int] = field(default_factory=lambda: [22, 23, 24, 25])
    servo_pin: int = 17
    servo_closed: float = -0.6
    servo_open: float = 0.6
    servo_settle_s: float = 0.4
    start_button_enabled: bool = False
    start_button_pin: int = 27
    button_pull_up: bool = True
    finish_pins: list[int] = field(default_factory=lambda: [5, 6, 13, 19])
    finish_active_low: bool = False


@dataclass
class Config:
    race: RaceCfg = field(default_factory=RaceCfg)
    display: DisplayCfg = field(default_factory=DisplayCfg)
    countdown: CountdownCfg = field(default_factory=CountdownCfg)
    hardware: HardwareCfg = field(default_factory=HardwareCfg)
    database: str = "derby.db"
    config_dir: Path = field(default_factory=lambda: CONFIG_PATH.parent)

    @property
    def database_path(self) -> Path:
        return self.config_dir / self.database

    def validate(self) -> None:
        if self.race.lanes < 1:
            raise ValueError("race.lanes must be >= 1")
        if len(self.hardware.finish_pins) != self.race.lanes:
            raise ValueError(
                f"hardware.finish_pins has {len(self.hardware.finish_pins)} entries "
                f"but race.lanes is {self.race.lanes}; they must match."
            )
        if self.countdown.style not in ("tree", "numeric"):
            raise ValueError("countdown.style must be 'tree' or 'numeric'")
        if self.race.scoring not in (
            "average", "drop_worst", "best", "total", "points"
        ):
            raise ValueError(
                "race.scoring must be one of: average, drop_worst, best, total, points"
            )
        if self.race.runs_per_car < 0:
            raise ValueError("race.runs_per_car must be >= 0")
        if self.race.finals_format not in ("rotation", "single"):
            raise ValueError("race.finals_format must be 'rotation' or 'single'")
        if self.hardware.backend not in ("auto", "mock", "gpio"):
            raise ValueError("hardware.backend must be 'auto', 'mock' or 'gpio'")
        if self.hardware.start_mode not in ("sensor", "servo"):
            raise ValueError("hardware.start_mode must be 'sensor' or 'servo'")
        if (
            self.hardware.start_mode == "sensor"
            and len(self.hardware.start_pins) != self.race.lanes
        ):
            raise ValueError(
                f"hardware.start_pins has {len(self.hardware.start_pins)} entries "
                f"but race.lanes is {self.race.lanes}; they must match."
            )


def load_config(path: Path | str | None = None) -> Config:
    path = Path(path) if path else CONFIG_PATH
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)

    cfg = Config(
        race=RaceCfg(**raw.get("race", {})),
        display=DisplayCfg(**raw.get("display", {})),
        countdown=CountdownCfg(**raw.get("countdown", {})),
        hardware=HardwareCfg(**raw.get("hardware", {})),
        database=raw.get("storage", {}).get("database", "derby.db"),
        config_dir=path.resolve().parent,
    )
    cfg.validate()
    return cfg
