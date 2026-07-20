#!/usr/bin/env python3
"""HALT bug behavioral test (issue #41).

The visual harness entry for halt_bug_test compares a blank screen, which
passes whether or not the bug is emulated.  This script checks the ROM's
actual SRAM result protocol:

  A000 = A register after `db $76 / ld a,$12` with IME=0 and an enabled
         interrupt pending.  Hardware (DMG and CGB): PC fails to
         increment, the 0x3E opcode byte is read again as its own
         operand, A = 0x3E.  An emulator without the bug reports 0x12.
  A001 = bug-detected flag (0x01 expected)
  A010 = 0xFF sentinel (ROM reached the end)
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
ROM = SCRIPT_DIR / "halt_bug_test.gb"

# 8KB game SRAM inside 32KB GBA SRAM -> write-through starts at 0x6000
SAV_BASE = 0x6000


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"), (ROM, ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        gba = tmpdir / "t.gba"
        sav = tmpdir / "t.sav"

        r = subprocess.run(
            [sys.executable, str(COMPILER), "-e", str(EMULATOR), "-o", str(gba), str(ROM)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"ERROR: compile failed: {r.stderr}")
            sys.exit(2)

        try:
            r = subprocess.run(
                [str(RUNNER), str(gba), "600", "/dev/null", "--savefile", str(sav)],
                capture_output=True, text=True, timeout=120,
            )
        except subprocess.TimeoutExpired:
            print("ERROR: runner timed out")
            sys.exit(2)
        if r.returncode != 0:
            print(f"ERROR: runner exited {r.returncode}: {r.stderr}")
            sys.exit(2)

        res = sav.read_bytes()[SAV_BASE:SAV_BASE + 0x11]

    a_val, bug_flag, sentinel = res[0], res[1], res[16]
    print(f"A=0x{a_val:02X} bugflag=0x{bug_flag:02X} sentinel=0x{sentinel:02X}")

    bad = []
    if sentinel != 0xFF:
        bad.append("ROM did not reach the end (sentinel missing)")
    if a_val != 0x3E:
        bad.append(f"A=0x{a_val:02X}, expected 0x3E -- HALT bug byte "
                   "duplication not emulated (hardware has it on DMG and CGB)")
    if bug_flag != 0x01:
        bad.append("bug-detected flag not set")

    if bad:
        for b in bad:
            print(f"FAIL: {b}")
        sys.exit(1)
    print("PASS: HALT bug byte duplication matches hardware")
    sys.exit(0)


if __name__ == "__main__":
    main()
