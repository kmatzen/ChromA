#!/usr/bin/env python3
"""When the mode-0 STAT interrupt actually arrives (#144).

ChromA raised the HBlank STAT interrupt from the scanline hook, which runs at
the *next* line boundary with LY already incremented -- roughly 204 cycles
after HBlank entry.

`test_stat_ly.py` cannot see this.  It counts STAT interrupts, and a late
interrupt is still exactly one interrupt: that suite reported the same 576
over four frames before and after the fix.  What distinguishes them is where
the PPU is when the handler runs, which is what this probe reads:

    on hardware   the handler for line N's HBlank runs during that HBlank,
                  so FF41 reads mode 0 and LY reads N
    a line late   the handler runs at the start of line N+1 -- OAM scan --
                  so FF41 reads a different mode and LY reads N+1

Measured against mGBA's own Game Boy core:

    mGBA     mode [0,0,0,...]  LY [16,17,18,...]
    before   mode [3,3,3,...]  LY [17,18,19,...]
    after    mode [0,0,0,...]  LY [16,17,18,...]

The middle row is why this test exists in this form.  An intermediate version
of the fix raised IF at HBlank entry and left delivery to the scanline chain,
and was **byte-for-byte identical to no fix at all** -- ChromA only tests for
interrupts at scanline boundaries, so moving the flag without moving the
dispatch moves nothing.  A test that only counted interrupts would have called
that a success.

Run: python3 test_roms/test_stat_mode0_timing.py
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
ROM = SCRIPT_DIR / "stat_mode0_timing_test.gb"

FRAMES = 300
GAME_SRAM_SIZE = 0x2000
SAMPLES = 8
MODE_BASE, LY_BASE, DONE = 0x00, 0x10, 0xFF


def run(wrap):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        sav = tmp / "sm.sav"
        if wrap:
            target = tmp / "sm.gba"
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
            capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            print(f"ERROR: runner exited {r.returncode}: {r.stderr[:300]}")
            sys.exit(2)
        data = sav.read_bytes()
    return data[:GAME_SRAM_SIZE] if not wrap else data[-GAME_SRAM_SIZE:]


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
            bad.append(f"{label}: the probe never collected its samples, so "
                       f"nothing below can be judged")
    if bad:
        for b in bad:
            print("FAIL: " + b)
        sys.exit(1)

    r_mode = list(ref[MODE_BASE:MODE_BASE + SAMPLES])
    g_mode = list(got[MODE_BASE:MODE_BASE + SAMPLES])
    r_ly = list(ref[LY_BASE:LY_BASE + SAMPLES])
    g_ly = list(got[LY_BASE:LY_BASE + SAMPLES])

    print(f"  mGBA    mode {r_mode}  LY {r_ly}")
    print(f"  ChromA  mode {g_mode}  LY {g_ly}")

    if any(m != 0 for m in r_mode):
        bad.append(f"mGBA itself reports mode {r_mode} inside the handler "
                   f"rather than 0, so the reference is not usable here")

    if not bad:
        if any(m != 0 for m in g_mode):
            bad.append(
                f"ChromA reads mode {g_mode} inside the mode-0 handler; "
                f"hardware is in HBlank there, so the interrupt is arriving "
                f"outside the HBlank it belongs to (#144)")
        if g_ly != r_ly:
            bad.append(
                f"ChromA reports LY {g_ly} inside the handler where mGBA "
                f"reports {r_ly} -- a raster effect keyed to LY sees the "
                f"wrong line (#144)")

    if bad:
        print()
        for b in bad:
            print("FAIL: " + b)
        sys.exit(1)

    print()
    print("PASS: the mode-0 STAT handler runs during HBlank of the line it "
          "belongs to, with the same LY mGBA reports")


if __name__ == "__main__":
    main()
