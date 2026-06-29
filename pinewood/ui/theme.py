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

"""Colors, fonts and small drawing helpers shared across screens."""

from __future__ import annotations

import pygame

# Palette --------------------------------------------------------------------
BG = (12, 14, 22)
BG_PANEL = (22, 26, 38)
FG = (235, 238, 245)
MUTED = (140, 148, 165)
ACCENT = (255, 196, 0)        # racing amber/gold
ACCENT_DK = (180, 138, 0)
GOOD = (60, 200, 120)
BAD = (220, 70, 70)
GREEN = (40, 220, 80)
AMBER = (255, 170, 0)
RED = (230, 40, 40)
DARK_BULB = (40, 40, 46)

# Per-lane colors + names. Lane 1 = Red, 2 = Blue, 3 = Green, 4 = Yellow.
# (extra entries cover tracks with more than 4 lanes.)
LANE_COLORS = [
    (228, 62, 62),    # red
    (66, 135, 245),   # blue
    (54, 196, 104),   # green
    (240, 200, 50),   # yellow
    (180, 110, 245),  # purple
    (245, 140, 70),   # orange
]
LANE_NAMES = ["Red", "Blue", "Green", "Yellow", "Purple", "Orange"]


def lane_color(lane: int) -> tuple[int, int, int]:
    return LANE_COLORS[lane % len(LANE_COLORS)]


def lane_name(lane: int) -> str:
    return LANE_NAMES[lane] if lane < len(LANE_NAMES) else f"Lane {lane + 1}"


def text_on(color: tuple[int, int, int]) -> tuple[int, int, int]:
    """Black or white text, whichever reads better on `color`."""
    r, g, b = color
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return (12, 14, 22) if luminance > 140 else (245, 245, 245)


class Fonts:
    """Lazily-built font cache (call after pygame.init / display set)."""

    def __init__(self, scale: float = 1.0):
        self.scale = scale
        self._cache: dict[int, pygame.font.Font] = {}

    def get(self, size: int, bold: bool = True) -> pygame.font.Font:
        key = int(size * self.scale) * (2 if bold else 1) + (1 if bold else 0)
        if key not in self._cache:
            f = pygame.font.SysFont(
                "dejavusans,arial,freesans", int(size * self.scale), bold=bold
            )
            self._cache[key] = f
        return self._cache[key]


def draw_text(
    surf: pygame.Surface,
    fonts: Fonts,
    text: str,
    size: int,
    pos: tuple[int, int],
    color=FG,
    center=False,
    bold=True,
    right=False,
) -> pygame.Rect:
    img = fonts.get(size, bold).render(text, True, color)
    rect = img.get_rect()
    if center:
        rect.center = pos
    elif right:
        rect.midright = pos
    else:
        rect.topleft = pos
    surf.blit(img, rect)
    return rect


def fmt_time(t: float | None, dnf: bool = False) -> str:
    if dnf or t is None:
        return "DNF"
    return f"{t:5.3f}s"


def rounded_panel(surf, rect, color=BG_PANEL, radius=14, border=None, width=2):
    pygame.draw.rect(surf, color, rect, border_radius=radius)
    if border:
        pygame.draw.rect(surf, border, rect, width=width, border_radius=radius)
