#!/usr/bin/env python3
"""MBC1 mode-1 banking test (issue #50, MBC1 half).

Real MBC1 always applies BANK2<<5 to the 4000-7FFF bank, in BOTH banking
modes.  chroma zeroed the high bits whenever mode 1 was selected, so on a
cart bigger than 512KB every bank select in mode 1 lost bits 5-6 and fetched
from the wrong half.  Mode 1 additionally maps bank BANK2<<5 at 0000-3FFF;
the mapper never called map0123_ at all, so the low half stayed pinned to
bank 0 forever.

The ROM is a full 1MB so banks $20/$21 exist to be distinguished, and the
mode-1 steps run from a stub copied into WRAM -- reading 0000-3FFF while it
is banked away means the code doing the reading cannot live there.

Measured on a build of the parent commit, both mode-1 checks fail while both
controls pass:

    mode 0 [4000]      0x21  want 0x21   control -- BANK2 has always worked here
    mode 1 [4000]      0x01  want 0x21   BANK2 stripped in mode 1
    mode 1 [0000]      0x00  want 0x20   low half never remapped
    restored [4000]    0x21  want 0x21   sanity
    BANK2=0, BANK1=5   0x05  want 0x05   control -- plain low banking
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
ROM = SCRIPT_DIR / "mbc1_mode1_test.gb"

FRAMES = 400
GAME_SRAM_SIZE = 0x2000

R_MODE0 = 0x00
R_MODE1_HIGH = 0x01
R_MODE1_LOW = 0x02
R_RESTORED = 0x03
R_PLAIN = 0x04
R_DONE = 0x0F


def run() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        gba, sav = tmp / "m1.gba", tmp / "m1.sav"
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
    print("results: " + " ".join(f"{b:02x}" for b in res[:16]))

    if res[R_DONE] != 0x5A:
        print(f"FAIL: the ROM did not run to completion "
              f"(done marker {res[R_DONE]:#04x})")
        sys.exit(1)

    bad = []

    # Controls first.  Both exercise banking on paths the broken build gets
    # right, so if either is wrong the cart is not banking at all and the
    # mode-1 verdicts below would be meaningless.
    if res[R_MODE0] != 0x21:
        bad.append(f"control: in mode 0 with BANK1=1 BANK2=1, [$4000] gave "
                   f"{res[R_MODE0]:#04x}, expected 0x21 -- high banking is "
                   f"broken outright, so the mode-1 results cannot be read")
    if res[R_PLAIN] != 0x05:
        bad.append(f"control: with BANK2=0 BANK1=5, [$4000] gave "
                   f"{res[R_PLAIN]:#04x}, expected 0x05 -- plain low banking "
                   f"is broken")

    if res[R_MODE1_HIGH] != 0x21:
        bad.append(f"in mode 1 with BANK1=1 BANK2=1, [$4000] gave "
                   f"{res[R_MODE1_HIGH]:#04x}, expected 0x21 -- BANK2<<5 "
                   f"applies to the 4000-7FFF bank in both modes, but the "
                   f"high bits are being zeroed in mode 1")
    if res[R_MODE1_LOW] != 0x20:
        bad.append(f"in mode 1 with BANK2=1, [$0000] gave "
                   f"{res[R_MODE1_LOW]:#04x}, expected 0x20 -- mode 1 maps "
                   f"bank BANK2<<5 at 0000-3FFF, but the low half is still "
                   f"pinned to bank 0")
    if res[R_RESTORED] != 0x21:
        bad.append(f"after returning to mode 0, [$4000] gave "
                   f"{res[R_RESTORED]:#04x}, expected 0x21 -- leaving mode 1 "
                   f"did not restore the 4000-7FFF bank")

    if bad:
        for b in bad:
            print(f"FAIL: {b}")
        sys.exit(1)

    print("\nPASS: BANK2 applies to 4000-7FFF in both modes, and mode 1 maps "
          "bank BANK2<<5 at 0000-3FFF")
    sys.exit(0)


if __name__ == "__main__":
    main()
