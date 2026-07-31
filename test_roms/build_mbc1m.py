#!/usr/bin/env python3
"""Build the MBC1M multicart probe ROM (issue #50).

An MBC1 multicart is not declared in the header -- the cartridge type is a
plain MBC1 -- so emulators detect one by content: a 1MB ROM that has a valid
cartridge header at the start of each 256KB game.  mGBA checks banks $10 and
$20 (offsets $40000 and $80000) and requires both to look like a ROM header.

So this stamps a copy of the ROM's own header at $40100 and $80100, which is
both what a real multicart looks like and the minimum that makes detection
fire.  It also writes each bank's own number at offset $10 within the bank, so
the probe can read $4010 and find out which bank the mapper actually mapped.

Run: python3 test_roms/build_mbc1m.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
ASM = SCRIPT_DIR / "mbc1m_test.asm"
OUT = SCRIPT_DIR / "mbc1m_test.gb"

ROM_SIZE = 0x100000          # 1MB: 64 banks of 16KB, what MBC1M carts are
BANK_SIZE = 0x4000
HEADER = (0x100, 0x150)      # copied to each game's start for detection
GAME_STARTS = (0x40000, 0x80000, 0xC0000)
SIGNATURE_OFF = 0x10         # read through $4010


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"ERROR: {' '.join(str(c) for c in cmd)}\n{r.stderr}")
        sys.exit(1)


def main():
    if not ASM.exists():
        print(f"ERROR: {ASM} not found")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as td:
        obj = Path(td) / "mbc1m.o"
        run(["rgbasm", "-o", str(obj), str(ASM)])
        run(["rgblink", "-o", str(OUT), str(obj)])
        # -m 0x03 = MBC1+RAM+BATTERY.  A real multicart has no RAM, but the
        # probe needs somewhere to leave its results, and detection keys on
        # content and size rather than the cartridge-type byte.
        # -r 2 = 8KB RAM, -p 0 = pad, ROM size byte is fixed up below.
        run(["rgbfix", "-v", "-p", "0", "-t", "MBC1M", "-m", "0x03",
             "-r", "2", str(OUT)])

    rom = bytearray(OUT.read_bytes())
    rom.extend(b"\x00" * (ROM_SIZE - len(rom)))
    del rom[ROM_SIZE:]

    # 1MB = 64 banks -> ROM size byte 0x05.  rgbfix sized the header for the
    # pre-expansion image, and detection checks the declared size.
    rom[0x148] = 0x05

    header = bytes(rom[HEADER[0]:HEADER[1]])
    for start in GAME_STARTS:
        rom[start + 0x100:start + 0x150] = header

    for bank in range(ROM_SIZE // BANK_SIZE):
        rom[bank * BANK_SIZE + SIGNATURE_OFF] = bank & 0xFF

    # The header checksum covers 0x134-0x14C and has to be recomputed after
    # the ROM-size byte changed; every copied header needs the same value.
    checksum = 0
    for b in rom[0x134:0x14D]:
        checksum = (checksum - b - 1) & 0xFF
    rom[0x14D] = checksum
    for start in GAME_STARTS:
        rom[start + 0x14D] = checksum

    OUT.write_bytes(bytes(rom))
    print(f"wrote {OUT} ({len(rom)} bytes, "
          f"{ROM_SIZE // BANK_SIZE} banks, headers at "
          f"{', '.join(hex(s) for s in GAME_STARTS)})")


if __name__ == "__main__":
    main()
