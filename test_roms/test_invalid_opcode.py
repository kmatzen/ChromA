#!/usr/bin/env python3
"""Invalid opcode / unmapped-region regression test (issue #56).

Three contained accuracy bugs, all reachable from ordinary GB code:

  1. Opcode $ED had a fully commented-out body and fell straight through into
     jr_fixup, which rewrites gb_pc from a stale register -- so executing one
     byte of garbage teleported the program counter.  Every other invalid
     opcode routes to _xx.
  2. FEA0-FEFF is not OAM.  OAM_W refuses to write past offset $A0, but
     OAM_R had no bound and read off the end of the 160-byte OAM buffer into
     whatever EWRAM follows it.  Hardware returns $00.
  3. KEY1 ($FF4D) only has bits 7 and 0; bits 1-6 read 1 on hardware.

The ROM runs the $ED subtest LAST, so on a build where it still teleports the
other two have already stored their results and can still be judged.
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
ROM = SCRIPT_DIR / "invalid_opcode_test.gb"

FRAMES = 600
GAME_SRAM_SIZE = 0x2000

R_BEFORE = 0x00         # $11 -- reached the $ED
R_AFTER = 0x01          # $22 -- the instruction after it ran
R_AFTER2 = 0x02         # $33 -- still executing straight-line code
R_UNUSED_OR = 0x03      # OR of every byte read from FEA0-FEFF
R_UNUSED_AND = 0x04     # AND of every byte read from FEA0-FEFF
R_KEY1 = 0x05           # KEY1 with bits 7 and 0 masked off
R_DONE = 0x0F


def run() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        gba, sav = tmp / "inv.gba", tmp / "inv.sav"
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
    print(f"  $ED markers: {res[R_BEFORE]:#04x} {res[R_AFTER]:#04x} "
          f"{res[R_AFTER2]:#04x} | FEA0-FEFF or={res[R_UNUSED_OR]:#04x} "
          f"and={res[R_UNUSED_AND]:#04x} | KEY1&0x7e={res[R_KEY1]:#04x}")

    bad = []

    # These two are stored before the $ED runs, so they are judged even on a
    # build where the $ED subtest kills the ROM.
    if res[R_UNUSED_OR] != 0x00 or res[R_UNUSED_AND] != 0x00:
        bad.append(f"FEA0-FEFF read back nonzero "
                   f"(or={res[R_UNUSED_OR]:#04x}, and={res[R_UNUSED_AND]:#04x}) "
                   f"-- that region is not OAM and returns 0x00 on hardware; "
                   f"the read is running off the end of the OAM buffer")

    if res[R_KEY1] != 0x7E:
        bad.append(f"KEY1 bits 1-6 read {res[R_KEY1]:#04x}, expected 0x7e -- "
                   f"only bits 7 and 0 exist and the rest read 1")

    if res[R_BEFORE] != 0x11:
        bad.append(f"the ROM never reached the $ED subtest "
                   f"(marker={res[R_BEFORE]:#04x})")
    elif res[R_AFTER] != 0x22 or res[R_AFTER2] != 0x33:
        bad.append(f"execution did not continue past an $ED byte "
                   f"(markers {res[R_AFTER]:#04x} {res[R_AFTER2]:#04x}, "
                   f"expected 0x22 0x33) -- $ED falls into jr_fixup, which "
                   f"rewrites the program counter from a stale register")
    elif res[R_DONE] != 0x5A:
        bad.append(f"the ROM did not reach its final marker "
                   f"({res[R_DONE]:#04x})")

    if bad:
        for b in bad:
            print(f"FAIL: {b}")
        sys.exit(1)

    print("\nPASS: an invalid opcode is skipped rather than moving PC, "
          "FEA0-FEFF reads 0x00, and KEY1's unused bits read 1")
    sys.exit(0)


if __name__ == "__main__":
    main()
