"""Save / load a derby roster (racer names + car numbers) as JSON files.

Files live in ``<config dir>/rosters/<name>.json`` so you can keep several
events on one Pi and move a roster between machines with a USB stick.

File format::

    {
      "type": "pinewood-roster",
      "version": 1,
      "name": "Pack 42 - 2026",
      "racers": [
        {"name": "Lightning", "car_number": 101},
        ...
      ]
    }
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .config import Config
from .models import Racer

ROSTER_TYPE = "pinewood-roster"


def rosters_dir(cfg: Config) -> Path:
    d = cfg.config_dir / "rosters"
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_filename(name: str) -> str:
    """Turn a display name into a safe file stem."""
    stem = re.sub(r"[^A-Za-z0-9 _-]", "", name).strip()
    stem = re.sub(r"\s+", "_", stem)
    return stem or "roster"


def list_rosters(cfg: Config) -> list[Path]:
    return sorted(rosters_dir(cfg).glob("*.json"))


def save_roster(cfg: Config, name: str, racers: list[Racer]) -> Path:
    path = rosters_dir(cfg) / f"{safe_filename(name)}.json"
    data = {
        "type": ROSTER_TYPE,
        "version": 1,
        "name": name,
        "racers": [{"name": r.name, "car_number": r.car_number} for r in racers],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    return path


def load_roster(path: Path | str) -> list[tuple[str, int]]:
    """Read a roster file and return validated (name, car_number) pairs.

    Raises ValueError on a malformed file.
    """
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or data.get("type") != ROSTER_TYPE:
        raise ValueError("not a pinewood-roster file")
    racers = data.get("racers")
    if not isinstance(racers, list):
        raise ValueError("roster file has no 'racers' list")

    out: list[tuple[str, int]] = []
    for entry in racers:
        try:
            name = str(entry["name"]).strip()
            num = int(entry["car_number"])
        except (KeyError, TypeError, ValueError):
            continue
        if name:
            out.append((name, num))
    return out


def roster_label(path: Path) -> tuple[str, int]:
    """Return (display name, racer count) for a saved roster, cheaply."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        name = data.get("name") or path.stem
        count = len(data.get("racers", []))
        return name, count
    except Exception:
        return path.stem, 0
