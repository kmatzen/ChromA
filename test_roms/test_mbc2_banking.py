#!/usr/bin/env python3
"""MBC2 register-decode and RAM-model test (issue #50, MBC2 half).

Two separate bugs, both reachable from ordinary MBC2 game code:

  1. Register decode.  On MBC2 address bit 8 ALONE selects the register,
     anywhere in 0000-3FFF: A8 set = ROM bank select, A8 clear = RAM enable.
     chroma wired one handler per 8KB block instead, so a RAM enable written
     to 2000-3FFF and a bank select written to 0000-1FFF were both dropped.
  2. RAM model.  MBC2 has 512 half-bytes, not 8KB: A000-BFFF echoes every
     512 bytes and only the low nibble is connected, so reads return the
     upper nibble as 1.  chroma used a flat 8KB buffer with neither.

The emulator writes the full byte through to GBA SRAM, so the .sav holds raw
stored bytes; values the ROM read back through the cart are nibble-masked.

Measured on a build of the parent commit, every check below fails while the
control passes:

    A000 read     0x5a (want 0xfa)   nibble mask absent
    A200 echo     0x00 (want 0xfa)   no echo
    echo write    0x5a (want 0xf7)   write did not fold
    enable@2000   0x00 (want 0xf3)   RAM-enable decode dropped
    bank via 0100 0x01 (want 0x02)   bank-select decode dropped
    bank via 2100 0x03 (want 0x03)   control -- passes on both
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
ROM = SCRIPT_DIR / "mbc2_banking_test.gb"

FRAMES = 400
MBC2_RAM_SIZE = 512  # rammask 0x1FF + 1

R_READ = 0x10
R_ECHO_READ = 0x11
R_ECHO_WRITE = 0x12
R_BANK_LOW = 0x14
R_BANK_CTRL = 0x15
R_ENABLE_HIGH = 0x16
R_DONE = 0x1F


def run() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        gba, sav = tmp / "m2.gba", tmp / "m2.sav"
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
    # MBC2's write-through window is the last 512 bytes of the GBA SRAM chip.
    return data[len(data) - MBC2_RAM_SIZE:]


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"), (ROM, ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    res = run()
    print("results: " + " ".join(f"{b:02x}" for b in res[:32]))

    if res[R_DONE] != 0x5A:
        print(f"FAIL: the ROM did not run to completion "
              f"(done marker {res[R_DONE]:#04x})")
        sys.exit(1)

    bad = []

    # Control first.  Banking through the address games normally use works on
    # the broken build too; if this is wrong the cart is not running at all
    # and every verdict below is meaningless.
    if res[R_BANK_CTRL] != 0x03:
        bad.append(f"control: selecting bank 3 through 2100 gave signature "
                   f"{res[R_BANK_CTRL]:#04x}, expected 0x03 -- ROM banking is "
                   f"broken outright, so the decode results below cannot be "
                   f"interpreted")

    checks = [
        (R_READ, 0xFA,
         "reading back A000 after writing $5A -- MBC2 only wires up the low "
         "nibble, so the upper nibble must read as 1"),
        (R_ECHO_READ, 0xFA,
         "reading A200 -- MBC2 has 512 half-bytes, so A200 must echo A000"),
        (R_ECHO_WRITE, 0xF7,
         "reading A000 after writing $B7 to A200 -- the echoed write must "
         "land on A000"),
        (R_ENABLE_HIGH, 0xF3,
         "enabling RAM by writing $0A to 2000 -- on MBC2 it is A8 alone that "
         "picks the register, so a RAM enable is valid anywhere in 0000-3FFF"),
        (R_BANK_LOW, 0x02,
         "selecting bank 2 by writing to 0100 -- A8 set means ROM bank "
         "select, even below 2000"),
    ]
    for off, want, why in checks:
        if res[off] != want:
            bad.append(f"read {res[off]:#04x}, expected {want:#04x}: {why}")

    if bad:
        for b in bad:
            print(f"FAIL: {b}")
        sys.exit(1)

    print("\nPASS: MBC2 decodes its registers by A8 across 0000-3FFF, and its "
          "RAM echoes every 512 bytes with the upper nibble reading as 1")
    sys.exit(0)


if __name__ == "__main__":
    main()
