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
