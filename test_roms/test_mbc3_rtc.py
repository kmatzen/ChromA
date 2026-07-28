#!/usr/bin/env python3
"""MBC3 RTC register test (issue #49, items 1-3).

  1. The RTC registers were read-only: selecting one installed empty_W, so
     the clock-set flows real games use had every write dropped.
  2. The day counter is a plain 9-bit binary count, but the reader ran it
     through calctime, which decodes BCD -- day 20 read back as 14.
  3. The DH register was hardwired to 0: no day bit 8, no halt bit, no
     512-day carry, even though gettime_sw already maintained bit 8.

Each register is written then read straight back with no latch in between,
so nothing here depends on the clock advancing.

Measured on a build of the parent commit, all five registers read 0 while
the control passes:

    control SRAM   0x5a  want 0x5a   plain RAM round-trip, works on both
    seconds        0x00  want 42
    minutes        0x00  want 37
    hours          0x00  want 21
    day low        0x00  want 200
    day high       0x00  want 0x81

A caveat worth stating: because the writes were dropped outright, the base
build cannot demonstrate the day-counter BCD bug *separately* -- there was
no stored value to mis-decode.  The day-low assertion still pins it going
forward: 200 is 0xC8, which a BCD decode would turn into 128, so a
regression that reinstates calctime on this register fails here.
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
ROM = SCRIPT_DIR / "mbc3_rtc_test.gb"

FRAMES = 400
GAME_SRAM_SIZE = 0x2000

R_CONTROL = 0x00
R_DONE = 0x0F

# (offset, register, written value, expected read-back)
CHECKS = [
    (0x01, "seconds", 42, 42),
    (0x02, "minutes", 37, 37),
    (0x03, "hours", 21, 21),
    (0x04, "day low", 200, 200),
    (0x05, "day high", 0x81, 0x81),
]


def run() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        gba, sav = tmp / "rtc.gba", tmp / "rtc.sav"
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

    # Control: while an RTC register is selected, A000-BFFF *is* the
    # register, so the ROM keeps switching back to RAM bank 0 to store its
    # results.  If that plain RAM round-trip is broken nothing below can be
    # trusted -- the results would not have been stored in the first place.
    if res[R_CONTROL] != 0x5A:
        bad.append(f"control: plain SRAM round-trip gave "
                   f"{res[R_CONTROL]:#04x}, expected 0x5a -- cart RAM is not "
                   f"working, so the RTC results below were never stored")

    for off, name, wrote, want in CHECKS:
        got = res[off]
        print(f"  {name:9s}: wrote {wrote:3d}  read {got:3d} ({got:#04x})  "
              f"expect {want:3d}{'' if got == want else '   <-- wrong'}")
        if got == want:
            continue
        if got == 0:
            bad.append(f"{name}: wrote {wrote}, read back 0 -- the write was "
                       f"dropped; selecting an RTC register must not make it "
                       f"read-only")
        else:
            bad.append(f"{name}: wrote {wrote}, read back {got} "
                       f"({got:#04x}), expected {want} -- value came back "
                       f"altered")

    if bad:
        for b in bad:
            print(f"FAIL: {b}")
        sys.exit(1)

    print("\nPASS: MBC3 RTC registers accept writes, the day counter is "
          "binary, and DH carries its day/halt/carry bits")
    sys.exit(0)


if __name__ == "__main__":
    main()
