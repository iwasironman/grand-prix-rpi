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

"""Procedurally-generated countdown beeps.

An original race-start sound in the spirit of arcade kart games: a short tone
on each amber light and a higher, longer 'GO' tone on green. Tones are
synthesized at runtime (no audio files, no numpy), so nothing copyrighted is
shipped or reproduced. All no-ops if audio is unavailable.
"""

from __future__ import annotations

import array
import math

try:
    import pygame
except Exception:  # pragma: no cover
    pygame = None  # type: ignore


def _tone(freq: float, ms: float, rate: int, channels: int, volume: float = 0.5,
          attack_ms: float = 8.0, release_ms: float = 80.0) -> bytes:
    """Signed-16 PCM of a sine tone that holds for `ms`.

    Uses short fixed attack/release fades (in ms) so a long tone sustains
    steadily and only fades briefly at the end (no early die-off, no clicks).
    """
    n = max(1, int(rate * ms / 1000))
    attack = min(max(1, int(rate * attack_ms / 1000)), n)
    release = min(max(1, int(rate * release_ms / 1000)), max(1, n - attack))
    amp = 32767 * volume
    buf = array.array("h")
    for i in range(n):
        if i < attack:
            env = i / attack
        elif i >= n - release:
            env = max(0.0, (n - i) / release)
        else:
            env = 1.0
        s = int(amp * env * math.sin(2 * math.pi * freq * i / rate))
        buf.append(s)
        if channels == 2:
            buf.append(s)
    return buf.tobytes()


class Beeper:
    """Plays a beep per amber light and a 'go' tone on green.

    Builds tones to match whatever format the pygame mixer initialized with, so
    it works whether the mixer is mono/stereo. Silently disables itself if the
    mixer can't init (e.g. no audio device, or the dummy audio driver).
    """

    def __init__(self, enabled: bool = True,
                 amber_hz: float = 600.0, go_hz: float = 1050.0,
                 amber_ms: float = 600.0, go_ms: float = 1000.0):
        self.ok = False
        if not enabled or pygame is None:
            return
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init()
            init = pygame.mixer.get_init()
            if not init:
                return
            rate, size, channels = init
            if abs(size) != 16:          # we only synthesize signed-16 PCM
                return
            # Each tone holds as long as its light (with a brief end fade).
            self._amber = pygame.mixer.Sound(
                buffer=_tone(amber_hz, amber_ms, rate, channels))
            self._go = pygame.mixer.Sound(
                buffer=_tone(go_hz, go_ms, rate, channels, release_ms=150))
            self._amber.set_volume(0.6)
            self._go.set_volume(0.75)
            self.ok = True
        except Exception:
            self.ok = False

    def amber(self) -> None:
        if self.ok:
            try:
                self._amber.play()
            except Exception:
                pass

    def go(self) -> None:
        if self.ok:
            try:
                self._go.play()
            except Exception:
                pass
