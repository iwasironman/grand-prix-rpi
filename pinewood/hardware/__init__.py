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

"""Hardware backends for the start gate, start button and finish sensors."""

from __future__ import annotations

from ..config import HardwareCfg
from .base import HardwareBackend
from .mock import MockBackend


def create_backend(cfg: HardwareCfg, lanes: int) -> HardwareBackend:
    """Pick a backend based on config and whether real GPIO is available."""
    choice = cfg.backend
    if choice == "mock":
        return MockBackend(cfg, lanes)
    if choice in ("auto", "gpio"):
        try:
            from .gpio import GpioBackend
            return GpioBackend(cfg, lanes)
        except Exception as exc:  # pragma: no cover - depends on hardware
            if choice == "gpio":
                raise
            print(f"[hardware] GPIO unavailable ({exc}); using keyboard mock.")
            return MockBackend(cfg, lanes)
    raise ValueError(f"unknown backend {choice!r}")


__all__ = ["HardwareBackend", "MockBackend", "create_backend"]
