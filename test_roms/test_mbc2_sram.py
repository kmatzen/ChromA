#!/usr/bin/env python3
"""MBC2 SRAM write-through regression test (issue #47).

Runs mbc2_sram_echo_test.gb, which fills the entire A000-BFFF window with
0xAA on an MBC2 cart (512 bytes of RAM, window echoes on hardware).

sram_W2 must clamp the write-through offset to rammask.  Unclamped, the
echoed writes land past the 512-byte write-through region and mirror into
the low GBA-SRAM area holding the config/savestate heap -- on the broken
build this test observes ~7,680 bytes of 0xAA sprayed across the heap and
the config magic overwritten.

Checks on the resulting .sav (32KB GBA SRAM image):
  1. The MBC2 write-through window [chip_end-512, chip_end) contains the
     0xAA pattern (proves the ROM ran and writes reached GBA SRAM).
  2. The heap area [0, 0x6000) contains (almost) no 0xAA bytes.
     Threshold 64 allows legitimate config bytes; the failure mode is
     three orders of magnitude larger.
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
ROM = SCRIPT_DIR / "mbc2_sram_echo_test.gb"

HEAP_END = 0x6000
WINDOW = 512  # MBC2 rammask + 1
HEAP_AA_LIMIT = 64


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
                [str(RUNNER), str(gba), "300", "/dev/null", "--savefile", str(sav)],
                capture_output=True, text=True, timeout=120,
            )
        except subprocess.TimeoutExpired:
            print("ERROR: runner timed out")
            sys.exit(2)
        if r.returncode != 0:
            print(f"ERROR: runner exited {r.returncode}: {r.stderr}")
            sys.exit(2)

        data = sav.read_bytes()

    window = data[len(data) - WINDOW:]
    window_aa = window.count(0xAA)
    heap_aa = data[:HEAP_END].count(0xAA)

    print(f"save size: {len(data)} bytes")
    print(f"MBC2 window [{len(data) - WINDOW:#x},{len(data):#x}): "
          f"{window_aa}/{WINDOW} bytes of 0xAA")
    print(f"heap area [0,{HEAP_END:#x}): {heap_aa} bytes of 0xAA "
          f"(limit {HEAP_AA_LIMIT})")

    bad = []
    if window_aa != WINDOW:
        bad.append("write-through window does not contain the test pattern -- "
                   "the ROM did not run or writes never reached GBA SRAM")
    if heap_aa > HEAP_AA_LIMIT:
        bad.append("echoed MBC2 writes leaked into the config/savestate heap "
                   "(sram_W2 offset not clamped to rammask)")

    if bad:
        for b in bad:
            print(f"FAIL: {b}")
        sys.exit(1)
    print("PASS: MBC2 echoed writes fold into the write-through window; heap untouched")
    sys.exit(0)


if __name__ == "__main__":
    main()
