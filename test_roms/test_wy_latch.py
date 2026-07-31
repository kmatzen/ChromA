#!/usr/bin/env python3
"""The window latches on for the frame once LY reaches WY (issue #53 item 1).

Hardware compares WY against LY once per line.  Once that coincidence has
happened the window stays on for the rest of the frame, and raising WY
afterwards does not retract it.  ChromA recomputed visibility as
`scanline >= WY` in `newmode` whenever a register changed, so a mid-frame
raise switched the window off from that line down.

The probe arms WY=64 during VBlank, lets the window trigger, then raises WY to
200 at LY=100 -- after the trigger and well above the bottom of the screen.
The window map is solid colour 3 and the background solid colour 0:

    correct   rows 64..143 all window        (the latch holds)
    broken    rows 64..99 window, 100..143 background

Two bands are sampled and compared *against each other within the same frame*
-- one just below WY, one well below the raise.  Equal means the window held.
Comparing bands rather than absolute colours keeps the reading independent of
how an emulator colours DMG output, which matters because ChromA colourises
DMG games through the GBC palette registers and its frame cannot be compared
pixel-for-pixel with mGBA's.

Measured:

    mGBA native GB core   both bands dark    latched
    ChromA before         lower band light   window dropped
    ChromA after          both bands dark    latched

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

# ChromA draws the 160x144 GB screen at this offset inside the GBA frame
# (SCREEN_X_START / SCREEN_Y_START in src/lcd.s).
CHROMA_ORIGIN = (40, 8)
NATIVE_ORIGIN = (0, 0)

COLUMNS = range(20, 60)
BAND_BELOW_WY = (70, 80)       # window is on here under either behaviour
BAND_BELOW_RAISE = (110, 125)  # the measurement: still window, or dropped?

# The two bands are solid fills of one colour each, so a real difference is
# the full swing between colour 3 and colour 0; anything under this is noise.
SAME_BAND_TOLERANCE = 20


def band_level(img, origin, span):
    ox, oy = origin
    y0, y1 = span
    px = [img.getpixel((ox + x, oy + y)) for x in COLUMNS for y in range(y0, y1)]
    return sum(sum(c) for c in px) // (len(px) * 3)


def run(wrap):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        shot = tmp / "w.bmp"
        if wrap:
            target = tmp / "w.gba"
            r = subprocess.run(
                [sys.executable, str(COMPILER), "-e", str(EMULATOR),
                 "-o", str(target), str(ROM)],
                capture_output=True, text=True)
            if r.returncode != 0:
                print(f"ERROR: compile failed: {r.stderr[:300]}")
                sys.exit(2)
            frames = "500"
        else:
            target, frames = ROM, "300"
        try:
            r = subprocess.run([str(RUNNER), str(target), frames, str(shot)],
                               capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            print("ERROR: runner timed out")
            sys.exit(2)
        if r.returncode != 0:
            print(f"ERROR: runner exited {r.returncode}: {r.stderr[:300]}")
            sys.exit(2)
        img = Image.open(shot).convert("RGB")
        img.load()
    origin = CHROMA_ORIGIN if wrap else NATIVE_ORIGIN
    return (band_level(img, origin, BAND_BELOW_WY),
            band_level(img, origin, BAND_BELOW_RAISE))


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"), (ROM, ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    bad = []
    for label, wrap in (("mGBA native GB core", False), ("ChromA", True)):
        above, below = run(wrap)
        held = abs(below - above) <= SAME_BAND_TOLERANCE
        print(f"  {label:20s} below-WY={above:3d}  below-raise={below:3d}  "
              f"-> {'latched' if held else 'window dropped'}")

        if above > 128:
            bad.append(
                f"{label}: the band just below WY reads {above}, i.e. light -- "
                f"the window is not on there at all, so the probe is not "
                f"rendering what this test assumes and the result below means "
                f"nothing")
        elif not held:
            bad.append(
                f"{label}: below the mid-frame WY raise the screen reads "
                f"{below} against {above} just below WY -- the window was "
                f"switched off by the raise.  Once LY has reached WY the "
                f"window is latched on for the rest of the frame")

    if bad:
        print()
        for b in bad:
            print("FAIL: " + b)
        sys.exit(1)

    print()
    print("PASS: raising WY after the window has triggered does not retract "
          "it, matching mGBA's Game Boy core")


if __name__ == "__main__":
    main()
