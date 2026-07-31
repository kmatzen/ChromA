#!/usr/bin/env python3
"""DMG orders overlapping sprites by X, not by OAM index (issue #53 item 3).

On DMG the sprite with the smaller X draws on top of an overlapping one
regardless of OAM order, with ties broken by the lower OAM index.  On CGB the
OAM index alone decides.  ChromA applied the CGB rule in both modes, because
GBA sprite priority *is* OAM index order and `OAMfinish` emitted entries
straight through in GB OAM order.

The probe places two 8x8 sprites so they overlap by four pixels, giving the
*later* OAM entry the *smaller* X:

    OAM[0]  X=60  solid colour 3   -> screen x 52..59
    OAM[1]  X=56  solid colour 1   -> screen x 48..55

    48..51  only OAM[1]   the X-rule winner
    52..55  overlap       the measurement
    56..59  only OAM[0]   the OAM-order winner

The overlap is then compared against the two single-sprite bands *within the
same frame*, so the result does not depend on how an emulator colours DMG
output -- which matters here, because ChromA colourises DMG games through the
GBC palette registers and its frame cannot be compared pixel-for-pixel with
mGBA's.  Each side only has to agree with itself.

Measured:

    mGBA native GB core   overlap == left band    (X rule)
    ChromA before         overlap == right band   (OAM order)
    ChromA after          overlap == left band    (X rule)

Run: python3 test_roms/test_sprite_x_priority.py
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
ROM = SCRIPT_DIR / "sprite_x_priority_test.gb"

# ChromA draws the 160x144 GB screen at this offset inside the GBA frame
# (SCREEN_X_START / SCREEN_Y_START in src/lcd.s).
CHROMA_ORIGIN = (40, 8)
NATIVE_ORIGIN = (0, 0)

ROWS = range(64, 72)          # the sprites sit at GB y 64..71
LEFT_BAND = (48, 52)          # only the smaller-X sprite
OVERLAP = (52, 56)
RIGHT_BAND = (56, 60)         # only the larger-X sprite


def band_colour(img, origin, span):
    ox, oy = origin
    x0, x1 = span
    px = [img.getpixel((ox + x, oy + y)) for x in range(x0, x1) for y in ROWS]
    return tuple(sum(c[i] for c in px) // len(px) for i in range(3))


def run(wrap):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        shot = tmp / "s.bmp"
        if wrap:
            target = tmp / "s.gba"
            r = subprocess.run(
                [sys.executable, str(COMPILER), "-e", str(EMULATOR),
                 "-o", str(target), str(ROM)],
                capture_output=True, text=True)
            if r.returncode != 0:
                print(f"ERROR: compile failed: {r.stderr[:300]}")
                sys.exit(2)
            frames = "400"
        else:
            target, frames = ROM, "200"
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
    return (band_colour(img, origin, LEFT_BAND),
            band_colour(img, origin, OVERLAP),
            band_colour(img, origin, RIGHT_BAND))


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"), (ROM, ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    bad = []
    for label, wrap in (("mGBA native GB core", False), ("ChromA", True)):
        left, mid, right = run(wrap)
        verdict = ("X rule" if mid == left else
                   "OAM order" if mid == right else "neither")
        print(f"  {label:20s} left={left} overlap={mid} right={right}  "
              f"-> {verdict}")

        if left == right:
            bad.append(
                f"{label}: the two single-sprite bands are the same colour "
                f"{left}, so the overlap cannot distinguish the two rules -- "
                f"the probe is not rendering what it should")
        elif mid == right:
            bad.append(
                f"{label}: the overlap matches the larger-X sprite, so the "
                f"sprite that is later in OAM won.  DMG breaks the tie by X, "
                f"not by OAM index")
        elif mid != left:
            bad.append(
                f"{label}: the overlap is {mid}, matching neither single "
                f"sprite band ({left} / {right}) -- the sprites are not "
                f"overlapping where this test expects")

    if bad:
        print()
        for b in bad:
            print("FAIL: " + b)
        sys.exit(1)

    print()
    print("PASS: DMG gives the smaller-X sprite priority over a later-OAM "
          "one, matching mGBA's Game Boy core")


if __name__ == "__main__":
    main()
