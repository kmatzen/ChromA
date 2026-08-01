#!/usr/bin/env python3
"""The window's WY coincidence latches for the rest of the frame (#146).

Hardware turns the window on when LY reaches WY and keeps it on to the end of
the frame; raising WY afterwards does not retract it.  ChromA recomputed
visibility as `scanline >= windowY` on every register write, so a mid-frame
raise dropped a window that had already been latched on.

`wy_latch_test.gb` re-arms WY=64 every VBlank and raises it to 200 at LY=100,
with the whole background colour 0 and the whole window colour 3, so the
window's extent is directly readable off the screen:

    lines   0.. 63   background
    lines  64..143   window        <- must survive the raise at line 100

The assertion is band-relative and made *within one frame*: a band below the
raise is compared against a band above it, both of which must be window.  That
is deliberate -- ChromA colourises DMG games through the GBC palette registers,
so its frame cannot be compared pixel-for-pixel with mGBA's, and an absolute
colour test would be measuring the palette rather than the window.

Measured before and after the fix, with GB line = GBA row - 8:

    stock    lines 64..99 window, 100..143 background   (retracted)
    fixed    lines 64..143 window                       (latched)
    mGBA     lines 64..143 window                       (latched)

Run: python3 test_roms/test_wy_latch.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
RUNNER = SCRIPT_DIR / "mgba_runner"
COMPILER = SCRIPT_DIR / "goomba_compile.py"
EMULATOR = PROJECT_DIR / "chroma.gba"
ROM = SCRIPT_DIR / "wy_latch_test.gb"

FRAMES = 400

# ChromA centres the 160x144 Game Boy screen in the GBA's 240x160 frame.
GBA_Y_OFFSET = 8
GBA_X_OFFSET = 40

# Bands to compare, in Game Boy scanlines.  ABOVE sits between WY and the
# raise, so it is window under any model; BELOW sits after the raise, and is
# window only if the coincidence latched.  REFERENCE sits above WY and is
# background, which is what makes "the window is showing" mean anything --
# without it a build that draws the window over the whole screen would pass.
BAND_REFERENCE = (20, 55)
BAND_ABOVE = (70, 95)
BAND_BELOW = (110, 140)

# The bands are flat fills, so a couple of percent of stray pixels is ample
# slack for any edge effects at the band boundaries.
TOLERANCE = 0.02


def band_mean(img, band):
    lo, hi = band
    w, _ = img.size
    total, count = 0, 0
    for y in range(lo + GBA_Y_OFFSET, hi + GBA_Y_OFFSET + 1):
        for x in range(GBA_X_OFFSET + 8, GBA_X_OFFSET + 152):
            total += img.getpixel((x, y))
            count += 1
    return total / count


def run():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        target = Path(tmp) / "wy.gba"
        shot = Path(tmp) / "wy.bmp"
        r = subprocess.run(
            [sys.executable, str(COMPILER), "-e", str(EMULATOR),
             "-o", str(target), str(ROM)],
            capture_output=True, text=True)
        if r.returncode != 0:
            print(f"ERROR: compile failed: {r.stderr[:300]}")
            sys.exit(2)
        r = subprocess.run(
            [str(RUNNER), str(target), str(FRAMES), str(shot)],
            capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            print(f"ERROR: runner exited {r.returncode}: {r.stderr[:300]}")
            sys.exit(2)
        return Image.open(shot).convert("L").copy()


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"), (ROM, ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    img = run()
    ref = band_mean(img, BAND_REFERENCE)
    above = band_mean(img, BAND_ABOVE)
    below = band_mean(img, BAND_BELOW)

    print(f"  background band  lines {BAND_REFERENCE[0]}-{BAND_REFERENCE[1]}: "
          f"{ref:6.1f}")
    print(f"  window   band    lines {BAND_ABOVE[0]}-{BAND_ABOVE[1]}: "
          f"{above:6.1f}   (between WY and the raise)")
    print(f"  window   band    lines {BAND_BELOW[0]}-{BAND_BELOW[1]}: "
          f"{below:6.1f}   (after the raise -- latched?)")

    bad = []
    span = abs(ref - above)
    if span < 16:
        bad.append(
            f"the background band ({ref:.1f}) and the window band above the "
            f"raise ({above:.1f}) are nearly identical, so the probe is not "
            f"drawing a window at all and nothing below can be judged")

    if not bad and abs(below - above) > span * TOLERANCE + 8:
        bad.append(
            f"the band after the raise ({below:.1f}) does not match the band "
            f"before it ({above:.1f}) -- raising WY mid-frame retracted a "
            f"window hardware had already latched on (#146)")

    if bad:
        print()
        for b in bad:
            print("FAIL: " + b)
        sys.exit(1)

    print()
    print("PASS: the window stays latched for the rest of the frame after a "
          "mid-frame WY raise")


if __name__ == "__main__":
    main()
