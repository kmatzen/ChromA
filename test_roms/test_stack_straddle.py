#!/usr/bin/env python3
"""Stack straddling a 4K page boundary (issue #98).

push16/pop16/popAF resolved the host page once, from the first byte's address,
and reused that base for the second byte.  Guest pages either side of a 4K
boundary are not contiguous in host memory, so a stack straddling one sent its
second byte somewhere else entirely:

    SP=$DFFF   $E000 is echo RAM -> WRAM $C000; the base resolved from $DFFF
               reached XGB_HRAM, i.e. guest $FF80
    SP=$CFFF   with SVBK>=2, $D000 is a GBC_EXRAM bank; the base resolved from
               $CFFF reached XGB_RAM, i.e. WRAM bank 1
    SP=$9FFF   $A000 is cart RAM; the base resolved from $9FFF reached
               XGB_VRAM+$2000, i.e. VRAM bank 1
    SP=$FFFF   the second byte wraps to $0000 (ROM); the base resolved from
               $FFFF reached outside every buffer

stack_straddle_test.gb plants a different value at the correct target and at
the wrong one for each case, so the .sav says which was reached.  It is
CGB-only: on DMG the $CFFF/$D000 pages are contiguous and that bug is
invisible.
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
ROM = SCRIPT_DIR / "stack_straddle_test.gb"

FRAMES = 300
GAME_SRAM_SIZE = 0x2000     # 8KB, from the cart's RAM-size header byte
BASE = 0x100                # results live at A100, matching the .asm

R_POP_ECHO = BASE + 0x00
R_PUSH_ECHO = BASE + 0x01
R_PUSH_HRAM = BASE + 0x02
R_POPAF_ECHO = BASE + 0x03
R_POP_SVBK = BASE + 0x04
R_PUSH_SVBK2 = BASE + 0x05
R_PUSH_SVBK1 = BASE + 0x06
R_POP_WRAP = BASE + 0x07
R_POP_VRAM_LO = BASE + 0x08
R_POP_VRAM_HI = BASE + 0x09
R_CONTROL = BASE + 0x0A
R_DONE = BASE + 0x0F


def run() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        gba, sav = tmp / "straddle.gba", tmp / "straddle.sav"
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
                capture_output=True, text=True, timeout=180,
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
    print("results: " + " ".join(f"{b:02x}" for b in res[BASE:BASE + 0x10]))

    if res[R_DONE] != 0x5A:
        print(f"FAIL: the test ROM did not run to completion "
              f"(marker={res[R_DONE]:#04x}, expected 0x5a)")
        sys.exit(1)

    # An aligned pop cannot straddle anything.  If this fails the stack is
    # broken outright and every other result below is meaningless.
    if res[R_CONTROL] != 0xBB:
        print(f"FAIL: control POP BC at SP=$C200 returned "
              f"{res[R_CONTROL]:#04x}, expected 0xbb -- ordinary stack "
              f"access is broken, not just the straddle")
        sys.exit(1)

    bad = []

    def check(off, want, wrong, what, right_place, wrong_place):
        got = res[off]
        if got != want:
            detail = f" -- it reached {wrong_place} instead" if got == wrong else ""
            bad.append(f"{what}: got {got:#04x}, expected {want:#04x} from "
                       f"{right_place}{detail}")

    check(R_POP_ECHO, 0x11, 0x22, "POP BC with SP=$DFFF took its high byte",
          "WRAM $C000 (echo of $E000)", "HRAM $FF80")
    check(R_PUSH_ECHO, 0x33, 0x00, "PUSH BC with SP=$E001 put its high byte",
          "WRAM $C000", "somewhere else")
    check(R_PUSH_HRAM, 0x22, 0x33, "PUSH BC with SP=$E001 left HRAM $FF80",
          "untouched", "HRAM $FF80")
    check(R_POPAF_ECHO, 0x11, 0x22, "POP AF with SP=$DFFF took A",
          "WRAM $C000 (echo of $E000)", "HRAM $FF80")
    check(R_POP_SVBK, 0x66, 0x55,
          "POP BC with SP=$CFFF and SVBK=2 took its high byte",
          "WRAM bank 2 $D000", "WRAM bank 1")
    check(R_PUSH_SVBK2, 0x77, 0x00,
          "PUSH BC with SP=$D001 and SVBK=2 put its high byte",
          "WRAM bank 2 $D000", "somewhere else")
    check(R_PUSH_SVBK1, 0x55, 0x77,
          "PUSH BC with SP=$D001 and SVBK=2 left WRAM bank 1 $D000",
          "untouched", "WRAM bank 1")
    check(R_POP_WRAP, 0xA7, 0x00, "POP BC with SP=$FFFF took its high byte",
          "ROM $0000, wrapping", "unmapped memory")
    check(R_POP_VRAM_LO, 0x99, 0x00,
          "POP BC with SP=$9FFF took its low byte", "VRAM $9FFF", "elsewhere")
    check(R_POP_VRAM_HI, 0x88, 0x77,
          "POP BC with SP=$9FFF took its high byte", "cart RAM $A000",
          "VRAM bank 1")

    if bad:
        for b in bad:
            print(f"FAIL: {b}")
        print("\npush16/pop16/popAF must resolve the page of each byte they "
              "touch; pages either side of a 4K boundary are not contiguous "
              "in host memory (#98)")
        sys.exit(1)

    print("\nPASS: stacks straddling the WRAM/echo, SVBK, VRAM/cart-RAM and "
          "$FFFF/$0000 boundaries reach the right memory for both bytes")
    sys.exit(0)


if __name__ == "__main__":
    main()
