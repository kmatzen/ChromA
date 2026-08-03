#!/usr/bin/env python3
"""TIMA read projection against mGBA, sample for sample (#143).

`tima_sweep_test.gb` re-establishes a known origin 256 times -- timer off,
TMA/TIMA zeroed, DIV reset, then enabled at TAC=$04 -- spins for i iterations
of a fixed loop, and reads TIMA back.  The result is a 256-point staircase of
TIMA against elapsed time.

mGBA passes mooneye's `timer/tim00`, so it is a valid reference here, and the
comparison localises the disagreement instead of only showing that some sample
is wrong.

**#143 is open.** ChromA currently diverges at 9 of the 256 samples, and the
divergence is transient rather than a shifted staircase: the steps land where
mGBA puts them and both timer tests pass, so the committed counter is right
and the fault is in the read projection (`_FF05R`) or its overflow fold.  Note
it goes both ways -- samples 51 and 108 read one *low*, the other seven read
one high -- so it is not a single signed bias.

This file exists to make that number a measurement rather than a description:
the issue quoted it, but nothing ran it.  The assertion is on sample-for-sample
difference rather than transition indices, because one misplaced step moves two
transitions and the raw count overstates it.

Approaches ruled out so far, none of which should be repeated: the six listed
in #143, plus rebasing `line_cycles_base` onto the value `cycles` actually
holds at the start of the line.  That last one is a real bias -- the line
handler adds a whole scanline to an already-negative `cycles`, so `elapsed`
opens each line at the previous instruction's overshoot instead of at zero --
but correcting it moved the count 9 -> 10, and it cannot explain the low
readings at all, since a positive bias can only over-read.

Run: python3 test_roms/test_tima_sweep.py
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
ROM = SCRIPT_DIR / "tima_sweep_test.gb"

FRAMES = 900
GAME_SRAM_SIZE = 0x2000
N = 256
DONE = 0x1FF

# A characterisation bound, not a target.  9 is where this stands today; the
# target is 0, and this is written as "must not exceed" precisely so that a
# fix passes and only a regression fails.  Lower it when the count drops --
# leaving it slack would let the fault creep back after being fixed.
MAX_DIVERGENT = 9


def run(wrap):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        sav = tmp / "ts.sav"
        if wrap:
            target = tmp / "ts.gba"
            r = subprocess.run(
                [sys.executable, str(COMPILER), "-e", str(EMULATOR),
                 "-o", str(target), str(ROM)],
                capture_output=True, text=True)
            if r.returncode != 0:
                print(f"ERROR: compile failed: {r.stderr[:300]}")
                sys.exit(2)
        else:
            target = ROM
        r = subprocess.run(
            [str(RUNNER), str(target), str(FRAMES), "/dev/null",
             "--savefile", str(sav)],
            capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            print(f"ERROR: runner exited {r.returncode}: {r.stderr[:300]}")
            sys.exit(2)
        data = sav.read_bytes()
    return data[:GAME_SRAM_SIZE] if not wrap else data[-GAME_SRAM_SIZE:]


def transitions(seq):
    return [i for i in range(1, len(seq)) if seq[i] != seq[i - 1]]


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"), (ROM, ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    ref, got = run(wrap=False), run(wrap=True)

    bad = []
    for label, res in (("mGBA", ref), ("ChromA", got)):
        if res[DONE] != 0x5A:
            bad.append(f"{label}: the probe did not run to completion")
    if bad:
        for b in bad:
            print("FAIL: " + b)
        sys.exit(1)

    r, g = ref[:N], got[:N]
    diverging = [i for i in range(N) if r[i] != g[i]]

    print(f"  mGBA   transitions at {transitions(r)}")
    print(f"  ChromA transitions at {transitions(g)}")
    print(f"  {len(diverging)} of {N} samples differ")
    for i in diverging[:12]:
        print(f"    sample {i:3d}: mGBA {r[i]:3d}  ChromA {g[i]:3d}")

    if len(diverging) > MAX_DIVERGENT:
        print()
        print(f"FAIL: {len(diverging)} samples of the TIMA sweep disagree with "
              f"mGBA, up from the {MAX_DIVERGENT} this pins.  Isolated samples "
              f"one tick out are a fault in the read projection (_FF05R) or "
              f"its overflow fold, not drift in the committed counter -- the "
              f"steps themselves still land where mGBA puts them (#143)")
        sys.exit(1)

    print()
    if len(diverging) < MAX_DIVERGENT:
        print(f"PASS: {len(diverging)} divergent samples, an improvement on "
              f"the {MAX_DIVERGENT} pinned here -- lower MAX_DIVERGENT to "
              f"{len(diverging)} to hold the gain")
    elif diverging:
        print(f"PASS: {len(diverging)} divergent samples, unchanged (#143 is "
              f"open; the target is 0)")
    else:
        print("PASS: the TIMA read projection matches mGBA at all 256 samples")


if __name__ == "__main__":
    main()
