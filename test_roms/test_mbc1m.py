#!/usr/bin/env python3
"""MBC1 multicart banking (issue #50).

An MBC1 multicart wires BANK1 as 4 bits instead of 5, so BANK2 shifts by 4 and
selects one of four 256KB games rather than one of four 512KB halves:

    plain MBC1   bank = (BANK2 << 5) | (BANK1 & 0x1F)
    MBC1M        bank = (BANK2 << 4) | (BANK1 & 0x0F)

Nothing in the header says which one a cart is -- a multicart's cartridge type
byte is a plain MBC1 -- so it has to be recognised by content.

Every byte at $4010 in the probe ROM holds the number of the bank it lives in,
so reading $4010 after a bank select reports which bank the mapper actually
mapped.  Two selects separate the models unambiguously, and the second pins the
4-bit mask specifically: with BANK1 bit 4 ignored it must land on the same bank
as the first.

    select                mGBA / hardware   plain MBC1 (ChromA before)
    BANK2=0 BANK1=$01                   1                            1
    BANK2=1 BANK1=$01                  17                           33
    BANK2=1 BANK1=$11                  17                           49
    BANK2=0 BANK1=$01 again             1                            1

mGBA's own Game Boy core detects the multicart and produces the left column;
ChromA produced the right one before this was implemented.

The ROM is generated rather than committed as source alone -- see
build_mbc1m.py, which stamps the per-bank signatures and the extra cartridge
headers that make detection fire.

Run: python3 test_roms/test_mbc1m.py
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
ROM = SCRIPT_DIR / "mbc1m_test.gb"

FRAMES = 300
GAME_SRAM_SIZE = 0x2000

# (offset, description, expected bank under MBC1M, what plain MBC1 gives)
CHECKS = [
    (0x00, "BANK2=0 BANK1=$01", 1, 1),
    (0x01, "BANK2=1 BANK1=$01", 17, 33),
    (0x02, "BANK2=1 BANK1=$11", 17, 49),
    (0x03, "BANK2=0 BANK1=$01 again", 1, 1),
]
R_DONE = 0x0F


def run(wrap):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        sav = tmp / "m.sav"
        if wrap:
            target = tmp / "m.gba"
            r = subprocess.run(
                [sys.executable, str(COMPILER), "-e", str(EMULATOR),
                 "-o", str(target), str(ROM)],
                capture_output=True, text=True)
            if r.returncode != 0:
                print(f"ERROR: compile failed: {r.stderr[:300]}")
                sys.exit(2)
        else:
            target = ROM
        try:
            r = subprocess.run(
                [str(RUNNER), str(target), str(FRAMES), "/dev/null",
                 "--savefile", str(sav)],
                capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            print("ERROR: runner timed out")
            sys.exit(2)
        if r.returncode != 0:
            print(f"ERROR: runner exited {r.returncode}: {r.stderr[:300]}")
            sys.exit(2)
        data = sav.read_bytes()
    return data[-GAME_SRAM_SIZE:] if wrap else data[:GAME_SRAM_SIZE]


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"), (ROM, ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path} "
                  f"(run: python3 test_roms/build_mbc1m.py)")
            sys.exit(2)

    ref, got = run(wrap=False), run(wrap=True)

    bad = []
    if ref[R_DONE] != 0x5A:
        bad.append("the probe did not finish under mGBA -- the reference is "
                   "not usable, so nothing here can be judged")
    if got[R_DONE] != 0x5A:
        bad.append("the probe did not finish under ChromA")

    if not bad:
        for off, what, want, plain in CHECKS:
            r, g = ref[off], got[off]
            print(f"  {what:24s} mGBA={r:3d}  ChromA={g:3d}  "
                  f"expect {want}{'' if g == want else '   <-- wrong'}")
            if r != want:
                bad.append(
                    f"{what}: mGBA reported bank {r}, expected {want} -- the "
                    f"reference is not treating this ROM as a multicart, so "
                    f"the ChromA reading below proves nothing.  Rebuild the "
                    f"probe with build_mbc1m.py")
            elif g != want:
                extra = (f" -- that is what a plain 5-bit MBC1 gives, so "
                         f"multicart detection did not fire") if g == plain \
                    else ""
                bad.append(f"{what}: ChromA mapped bank {g}, expected "
                           f"{want}{extra}")

    if bad:
        print()
        for b in bad:
            print("FAIL: " + b)
        sys.exit(1)

    print()
    print("PASS: an MBC1 multicart banks with a 4-bit BANK1, matching mGBA's "
          "Game Boy core")


if __name__ == "__main__":
    main()
