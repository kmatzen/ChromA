#!/usr/bin/env python3
"""Timer overflow / DIV-write glitch regression test (issue #44).

Two independent problems, neither of which needs cycle-exact test code to
demonstrate.

A. TIMA could read below TMA.  `checkTimerIRQ` detected a single carry per
   scanline and then stored TMA<<24 flat, throwing away both the extra wraps
   and the sub-period remainder; `_FF05R` projected the sub-scanline value
   modulo 256.  A scanline is ~28 timer periods wide at TAC=01, so both
   produced readings far below TMA -- a value real hardware can never hold
   once TIMA has reloaded.

B. The DIV-write falling-edge glitch never fired.  `_FF04W`/`_FF07W` tested
   dividereg bits 9/15/13/11, but dividereg only ever accumulates 456<<16
   multiples, so its bottom 19 bits are always zero.  The correct bits at
   that scaling are 25/19/21/23.

timer_overflow_test.gb measures B as a controlled pair: 64 back-to-back DIV
writes versus the same number of T-cycles spent on NOPs.  Everything else
about the two runs is identical, so the difference is exactly the number of
glitch increments.
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
ROM = SCRIPT_DIR / "timer_overflow_test.gb"

FRAMES = 900
GAME_SRAM_SIZE = 0x2000

R_MIN = 0x00            # lowest TIMA sampled in subtest A
R_MAX = 0x01            # highest TIMA sampled in subtest A
R_WRITES = 0x02         # TIMA after 64 DIV writes
R_NOPS = 0x03           # TIMA after the same span of NOPs
R_DONE = 0x0F

TMA = 0xF6              # what the ROM programs into TMA for subtest A
GLITCH_WRITES = 64
# The ROM's two runs are the same length but not byte-identical in setup, so
# a couple of ticks of slop is expected either way.  A working glitch adds one
# increment per write; a dead one adds none.  Anything past halfway is
# unambiguous -- measured 65 with the fix and 2 without.
GLITCH_MIN = GLITCH_WRITES // 2


def run() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        gba, sav = tmp / "timer.gba", tmp / "timer.sav"
        r = subprocess.run(
            [sys.executable, str(COMPILER), "-e", str(EMULATOR),
             "-o", str(gba), str(ROM)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"ERROR: compile failed: {r.stderr}")
            sys.exit(2)
        try:
            r = subprocess.run(
                [str(RUNNER), str(gba), str(FRAMES), "/dev/null",
                 "--savefile", str(sav)],
                capture_output=True, text=True, timeout=300,
            )
        except subprocess.TimeoutExpired:
            print("ERROR: runner timed out")
            sys.exit(2)
        if r.returncode != 0:
            print(f"ERROR: runner exited {r.returncode}: {r.stderr[:500]}")
            sys.exit(2)
        data = sav.read_bytes()
    return data[len(data) - GAME_SRAM_SIZE:]


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"), (ROM, ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    res = run()
    glitch = res[R_WRITES] - res[R_NOPS]
    print("results: " + " ".join(f"{b:02x}" for b in res[:16]))
    print(f"  A: TIMA range seen = {res[R_MIN]:#04x}..{res[R_MAX]:#04x} "
          f"(TMA={TMA:#04x})")
    print(f"  B: {res[R_WRITES]} after {GLITCH_WRITES} DIV writes vs "
          f"{res[R_NOPS]} after the same span of NOPs -> "
          f"{glitch} glitch increments")

    if res[R_DONE] != 0x5A:
        print(f"FAIL: the test ROM did not run to completion "
              f"(marker={res[R_DONE]:#04x}, expected 0x5a)")
        sys.exit(1)

    bad = []

    # A: once TIMA has overflowed it reloads from TMA, so it can never again
    # be below TMA.  No timing assumption -- this is a hardware invariant.
    if res[R_MIN] < TMA:
        bad.append(f"TIMA read {res[R_MIN]:#04x}, below TMA={TMA:#04x} -- it "
                   f"reloads from TMA on overflow, so this value is "
                   f"unreachable on hardware.  The scanline wrap drops the "
                   f"extra periods and the sub-period remainder")
    if res[R_MAX] != 0xFF:
        bad.append(f"TIMA never reached 0xFF (max {res[R_MAX]:#04x}) -- it is "
                   f"not counting up to the overflow at all")

    # B: the glitch has to actually clock TIMA.
    if glitch < GLITCH_MIN:
        bad.append(f"{GLITCH_WRITES} DIV writes clocked TIMA {glitch} extra "
                   f"times, expected about {GLITCH_WRITES} -- the DIV-write "
                   f"falling-edge path is testing dividereg bits that are "
                   f"always zero, so it never fires")

    if bad:
        for b in bad:
            print(f"FAIL: {b}")
        sys.exit(1)

    print("\nPASS: TIMA wraps through TMA and stays in range, and writing DIV "
          "clocks it on a falling edge")
    sys.exit(0)


if __name__ == "__main__":
    main()
