#!/usr/bin/env python3
"""How long LY reads 153 at the top of the frame (issue #52 item 6).

Line 153 is special: LY reads 153 only briefly and then reads 0 for the rest
of the line, still inside VBlank.  Issue #52 item 6 says ChromA holds that
window for 8 T-cycles where hardware holds it for about 4, and asks for the
constants in FF41_modifydata to be halved.

**Measured against mGBA's own Game Boy core, that is wrong**, and this test
exists to keep anyone from "fixing" it:

    mGBA native GB core          165 hits
    ChromA, 8-cycle window       166 hits     <- what ChromA does today
    ChromA, 4-cycle window       141 hits     <- what the issue asks for

Halving the constants moves ChromA *away* from the reference.  The 8-cycle
window is right, so the assertion below pins ChromA to mGBA rather than to the
issue text.

How the probe works.  The window is shorter than a single `ldh a,[$FF44]`
(12 T-cycles), so no polling loop can resolve it directly -- the first attempt
at this measured 1 hit on both emulators and discriminated nothing.  Instead
the loop is padded to a period of 68 T-cycles.  Every GB instruction takes a
multiple of 4, so a loop period is always a multiple of 4; 68 is the useful
choice because gcd(68, 70224) = 4, which makes the sampling phase visit every
4-cycle offset within a frame rather than stepping in 12s and straddling the
window.  The hit count is then proportional to the window's width, and a
4-cycle window differs from an 8-cycle one by about 2x.

The counts are close but not identical (165 vs 166) because the sweep does not
divide evenly into the run, so the tolerance below is a few counts wide -- far
narrower than the 24-count gap to the 4-cycle variant it needs to reject.

Run: python3 test_roms/test_ly153_window.py
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
ROM = SCRIPT_DIR / "ly153_window_test.gb"

FRAMES = 2400
GAME_SRAM_SIZE = 0x2000

# ChromA and mGBA need not agree to the count -- the phase sweep does not
# divide evenly into the run -- but they must agree far more closely than the
# 4-cycle variant the issue asks for, which lands ~24 counts low.
TOLERANCE = 8


def run(rom_path, wrap):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        sav = tmp / "ly.sav"
        if wrap:
            target = tmp / "ly.gba"
            r = subprocess.run(
                [sys.executable, str(COMPILER), "-e", str(EMULATOR),
                 "-o", str(target), str(rom_path)],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                print(f"ERROR: compile failed: {r.stderr}")
                sys.exit(2)
        else:
            target = rom_path
        try:
            r = subprocess.run(
                [str(RUNNER), str(target), str(FRAMES), "/dev/null",
                 "--savefile", str(sav)],
                capture_output=True, text=True, timeout=900,
            )
        except subprocess.TimeoutExpired:
            print("ERROR: runner timed out")
            sys.exit(2)
        if r.returncode != 0:
            print(f"ERROR: runner exited {r.returncode}: {r.stderr[:400]}")
            sys.exit(2)
        data = sav.read_bytes()[-GAME_SRAM_SIZE:]
    return data[0] | (data[1] << 8), data[2]


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"), (ROM, ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    ref, ref_done = run(ROM, wrap=False)
    got, got_done = run(ROM, wrap=True)

    print(f"  mGBA native GB core: {ref} hits (done={ref_done:#04x})")
    print(f"  ChromA:              {got} hits (done={got_done:#04x})")

    bad = []
    if ref_done != 0x5A:
        bad.append("the probe did not finish under mGBA -- the reference is "
                   "not usable, so nothing here can be judged")
    if got_done != 0x5A:
        bad.append("the probe did not finish under ChromA")
    if ref and abs(got - ref) > TOLERANCE:
        bad.append(f"ChromA sees LY=153 for a different length of time than "
                   f"mGBA: {got} hits against {ref} (tolerance {TOLERANCE}). "
                   f"Halving the FF41_modifydata line-153 constants, which "
                   f"#52 item 6 asks for, lands about 24 counts low -- that "
                   f"change is wrong and this test is here to say so.")

    if bad:
        print()
        for b in bad:
            print("FAIL: " + b)
        sys.exit(1)

    print()
    print("PASS: ChromA holds LY=153 for the same span as mGBA's Game Boy core")


if __name__ == "__main__":
    main()
