#!/usr/bin/env python3
"""LY against time since the LCD was enabled (issue #145).

mooneye's lcdon_timing-GS reported a single point -- "at cycle $82 LY should
be $01 and reads $00" -- which says the first line after an LCD enable is
wrong but not how.  lcdon_ly_test.gb samples the whole curve instead: for
every delay from 0 to 255 machine cycles after the FF40 write, read LY once.

That turned the diagnosis around.  ChromA's only step in that window was at
delay 223, landing exactly on mGBA's *second* step -- the signature of a whole
line being spent, not of a mistimed one, and why #145's attempt at trimming
line 0 by 200 cycles changed nothing.  The cause was the entry point:
FF40_W pointed nexttimeout at toLineZero, which is not "the start of a frame"
but the *tail of line 153*, the part where LY reads 0 for the rest of that
line.  Enabling the LCD replayed that tail, so LY sat at 0 for it and then
again for the whole of line 0.

    before   LY 0->1 at 223                (one step in 256 cycles)
    after    LY 0->1 at 110, 1->2 at 224
    mGBA     LY 0->1 at 109, 1->2 at 223

The one-cycle offset from mGBA is deliberate and is the reason this test
pins exact values rather than comparing to the reference at runtime.  mGBA
*fails* lcdon_timing-GS, and #145 records that ChromA is closer to hardware
here -- it passes the STAT checks mGBA fails.  Sweeping the enable delay
against the ROM's own diagnostic:

    trim 0 machine cycles   ROM: cycle $6F, expected $01, actual $00
    trim 1                  LY phase passes; ROM moves on to its STAT checks
    trim 2                  ROM: cycle $6E, expected $00, actual $01

So the ROM brackets the first line to a single machine cycle, and the value
it wants is one cycle away from mGBA's.  Matching the ROM is the right call;
matching mGBA would reintroduce a failure the ROM detects.  If someone later
establishes otherwise from hardware, this test should be updated alongside
the emulator and the ROM's diagnostic re-read -- the disagreement is the
finding, not a reason to loosen the assertion.

Usage:
    python3 test_roms/test_lcdon_ly.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
RUNNER = SCRIPT_DIR / "mgba_runner"
COMPILER = SCRIPT_DIR / "goomba_compile.py"
EMULATOR = PROJECT_DIR / "chroma.gba"
ROM = SCRIPT_DIR / "lcdon_ly_test.gb"

FRAMES = 900
GAME_SRAM_SIZE = 0x2000
DONE = 0x100

# Where LY must step, in machine cycles after the FF40 write that enables the
# LCD.  See the module docstring for why these are exact and why they are one
# cycle off mGBA's 109/223.
EXPECT_FIRST_STEP = 110
EXPECT_SECOND_STEP = 224
# A scanline is 114 machine cycles; the gap between the steps is the check
# that the *line length* is right rather than only the starting offset.
EXPECT_LINE = 114


def run(rom, native):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        target, sav = tmp / "lcdon.gba", tmp / "lcdon.sav"
        if native:
            target = rom
        else:
            r = subprocess.run(
                [sys.executable, str(COMPILER), "-e", str(EMULATOR),
                 "-o", str(target), str(rom)],
                capture_output=True, text=True)
            if r.returncode != 0:
                print(f"ERROR: compile failed: {r.stderr}")
                sys.exit(2)
        try:
            r = subprocess.run(
                [str(RUNNER), str(target), str(FRAMES), "/dev/null",
                 "--savefile", str(sav)],
                capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            print("ERROR: runner timed out")
            sys.exit(2)
        if r.returncode != 0:
            print(f"ERROR: runner exited {r.returncode}: {r.stderr[:400]}")
            sys.exit(2)
        data = sav.read_bytes()
    return data[len(data) - GAME_SRAM_SIZE:]


def steps(samples):
    return [(i, samples[i - 1], samples[i])
            for i in range(1, 256) if samples[i] != samples[i - 1]]


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"), (ROM, ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    chroma = run(ROM, native=False)
    native = run(ROM, native=True)

    if chroma[DONE] != 0x5A:
        print(f"FAIL: ChromA did not complete the sweep "
              f"(marker={chroma[DONE]:#04x})")
        sys.exit(1)

    cs, ns = steps(chroma), steps(native)
    print(f"  ChromA LY steps: {cs}")
    print(f"  mGBA   LY steps: {ns}   (reference; see the docstring for the "
          f"deliberate one-cycle offset)")

    bad = []
    if len(cs) != 2:
        bad.append(f"expected exactly two LY steps in the first 256 machine "
                   f"cycles, got {len(cs)}: {cs}.  One step means a whole "
                   f"extra line is being spent at LY=0, which is the #145 bug")
    else:
        first, second = cs[0][0], cs[1][0]
        if first != EXPECT_FIRST_STEP:
            bad.append(f"LY 0->1 at {first} machine cycles after the enable, "
                       f"expected {EXPECT_FIRST_STEP} -- the first line is the "
                       f"wrong length")
        if second - first != EXPECT_LINE:
            bad.append(f"LY 1->2 came {second - first} machine cycles after "
                       f"LY 0->1, expected a normal scanline of {EXPECT_LINE}")
        if second != EXPECT_SECOND_STEP:
            bad.append(f"LY 1->2 at {second}, expected {EXPECT_SECOND_STEP}")

    if bad:
        for b in bad:
            print(f"FAIL: {b}")
        sys.exit(1)

    print("\nPASS: LY steps one machine cycle after mGBA and then on a normal "
          "114-cycle line, which is what lcdon_timing-GS's own diagnostic asks "
          "for")
    sys.exit(0)


if __name__ == "__main__":
    main()
