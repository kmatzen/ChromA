#!/usr/bin/env python3
"""Instruction fetch across the echo/OAM region boundary (issue #116).

`encodePC` turns gb_pc into a raw host pointer and nothing re-evaluates it as
the CPU advances, so execution that runs off the end of a region keeps walking
into whatever host memory follows -- a different GB region entirely.  Echo RAM
ends at $FDFF and sits 0x1DFF into XGB_RAM, so an instruction whose operand
crosses into $FE00 read $DE00's byte out of WRAM instead of OAM, and the CPU
then wandered until it died.  The failure mode is a hang and a black screen
rather than a wrong value, which is what made it worth fixing: a ROM that
trips it is unrecoverable rather than subtly off.

The ROM stages three cases in increasing order of suspicion and writes a
progress byte after each, so a build that dies mid-way still says where:

    case 1  $A000, expect $55   an instruction wholly inside echo RAM
    case 2  $A001, expect $66   a single-byte RET on the last echo byte
    case 3  $A002, expect $77   an operand that crosses $FDFF -> $FE00

$DE00 holds $99 as a decoy: a straddle bug picks that up instead of the OAM
byte, so case 3 reading $99 is a different -- and more informative -- failure
than case 3 not running at all.

Reference, confirmed against mGBA's own Game Boy core: progress 3 with
$55/$66/$77.

Run: python3 test_roms/test_region_boundary.py
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
ROM = SCRIPT_DIR / "region_boundary_test.gb"

FRAMES = 900
GAME_SRAM_SIZE = 0x2000

R_CASE1, R_CASE2, R_CASE3 = 0x00, 0x01, 0x02
R_PROGRESS, R_DONE = 0x0E, 0x0F

DECOY = 0x99            # the byte at $DE00, which a straddle bug reads


def run() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        gba, sav = tmp / "region.gba", tmp / "region.sav"
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
    print(f"  case1={res[R_CASE1]:#04x} case2={res[R_CASE2]:#04x} "
          f"case3={res[R_CASE3]:#04x} progress={res[R_PROGRESS]} "
          f"done={res[R_DONE]:#04x}")

    bad = []

    if res[R_CASE1] != 0x55:
        bad.append(f"case 1 (wholly inside echo RAM) returned "
                   f"{res[R_CASE1]:#04x}, expected 0x55 -- executing *from* "
                   f"echo RAM is broken, which is #46 territory")
    if res[R_CASE2] != 0x66:
        bad.append(f"case 2 (RET on the last echo byte) returned "
                   f"{res[R_CASE2]:#04x}, expected 0x66")

    if res[R_CASE3] == DECOY:
        bad.append(f"case 3 read the $DE00 decoy ({DECOY:#04x}): the fetch "
                   f"crossed $FDFF -> $FE00 by walking linearly through "
                   f"XGB_RAM instead of reaching OAM")
    elif res[R_CASE3] != 0x77:
        bad.append(f"case 3 (operand crossing into OAM) returned "
                   f"{res[R_CASE3]:#04x}, expected 0x77")

    if res[R_PROGRESS] < 3:
        bad.append(f"only {res[R_PROGRESS]} of 3 cases completed -- the CPU "
                   f"stopped making progress, which is the hang this test "
                   f"exists for")
    if res[R_DONE] != 0x5A:
        bad.append(f"ROM did not reach its end marker "
                   f"(${res[R_DONE]:02X}, expected $5A)")

    if bad:
        print()
        for b in bad:
            print("FAIL: " + b)
        sys.exit(1)

    print()
    print("PASS: instruction fetch crosses $FDFF -> $FE00 into OAM correctly, "
          "and executing from echo RAM still works")


if __name__ == "__main__":
    main()
