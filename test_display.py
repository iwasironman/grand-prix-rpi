"""Minimal KMSDRM display test: cycles red/green/blue fullscreen for ~9s.

Run on the Pi's console (tty1). If you see the colors, pygame+KMSDRM presents
fine and the issue is elsewhere; if it stays blank, it's a driver/render issue.
"""
import time
import pygame

try:
    pygame.init()
    flags = pygame.FULLSCREEN | pygame.SCALED
    scr = pygame.display.set_mode((1280, 720), flags)
    print("OK driver=%s size=%s" % (pygame.display.get_driver(), scr.get_size()), flush=True)
    for name, col in [("RED", (220, 40, 40)), ("GREEN", (40, 200, 80)), ("BLUE", (60, 120, 240))]:
        scr.fill(col)
        pygame.display.flip()
        print("showing", name, flush=True)
        time.sleep(3)
    print("DONE", flush=True)
except Exception as exc:
    print("ERROR:", repr(exc), flush=True)
finally:
    pygame.quit()
