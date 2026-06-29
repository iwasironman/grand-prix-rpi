#!/usr/bin/env python3
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

"""Grand Prix RPi — entry point.

Usage:
    python3 main.py                 # use config.toml as-is
    python3 main.py --windowed      # force a window (dev on a laptop)
    python3 main.py --mock          # force the keyboard hardware mock
    python3 main.py --config PATH   # use an alternate config file
    python3 main.py --video kmsdrm  # force a specific SDL video driver

On Raspberry Pi OS Lite (no desktop), this renders fullscreen straight to the
HDMI display via SDL's KMSDRM driver — selected automatically when no desktop
(DISPLAY / WAYLAND_DISPLAY) is detected.
"""

from __future__ import annotations

import argparse
import os


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Pinewood derby race system")
    p.add_argument("--config", default=None, help="path to config.toml")
    p.add_argument("--windowed", action="store_true", help="run in a window, not fullscreen")
    p.add_argument("--mock", action="store_true", help="force keyboard hardware mock")
    p.add_argument("--video", default=None,
                   help="force an SDL video driver (e.g. kmsdrm, x11, wayland, dummy)")
    return p.parse_args()


def _select_video_driver(forced: str | None) -> None:
    """Pick an SDL video driver BEFORE pygame is imported.

    On a desktop SDL auto-detects x11/wayland.  On Pi OS Lite there is no
    desktop, so default to KMSDRM (direct-to-display via the kernel).
    """
    if forced:
        os.environ["SDL_VIDEODRIVER"] = forced
    elif (
        os.name == "posix"
        and "SDL_VIDEODRIVER" not in os.environ
        and not os.environ.get("DISPLAY")
        and not os.environ.get("WAYLAND_DISPLAY")
    ):
        os.environ["SDL_VIDEODRIVER"] = "kmsdrm"

    # The Pi's vc4/v3d GPU is OpenGL ES only. Force SDL's GLES2 renderer so it
    # doesn't fall back to the desktop-GL renderer, whose calls are invalid on a
    # GLES context and render nothing (black screen despite no error).
    if os.environ.get("SDL_VIDEODRIVER") == "kmsdrm":
        os.environ.setdefault("SDL_RENDER_DRIVER", "opengles2")


def main() -> int:
    args = parse_args()
    _select_video_driver(args.video)

    # Import only after the video driver is chosen (importing pygame reads it).
    from pinewood.config import load_config
    from pinewood.ui.app import App

    cfg = load_config(args.config)
    if args.windowed:
        cfg.display.fullscreen = False
    if args.mock:
        cfg.hardware.backend = "mock"
    App(cfg).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
