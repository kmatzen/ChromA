#!/usr/bin/env python3
"""IF (FF0F) register semantics regression test (issue #42).

Two related holes in the interrupt-flag emulation:

  1. _FF0FR returned the raw stored IF byte.  Hardware wires the top three
     bits high, so FF0F always reads back 0xE0 | IF.  Anything doing full-byte
     arithmetic on `ldh a,($FF0F)` -- Zerd no Densetsu is the known case --
     saw the wrong value.
  2. _FF0FW stored all 8 bits.  Only 5 interrupts exist, so the phantom upper
     bits could then match the same bits in IE (a full 8-bit R/W register on
     hardware, which a game may legitimately leave set).  checkIRQ ANDed
     IE & IF with no 0x1F mask, none of the five `tst` checks in the priority
     chain claimed the IRQ, and control fell out of _irqGBZ80_ into its
     unknown-IRQ tail -- which dispatches to vector 0x40.  A game that never
     enabled VBlank got VBlank interrupts anyway.

if_register_test.gb reads FF0F back after four writes, then idles with
IE=0xE0 (phantom bits only, no real interrupt enabled) counting any dispatch
on all five vectors, then repeats with IE=0x01 as a positive control.
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
ROM = SCRIPT_DIR / "if_register_test.gb"

FRAMES = 600
GAME_SRAM_SIZE = 0x2000

R_WROTE_00 = 0x00       # FF0F read back after writing $00
R_WROTE_FF = 0x01       # after writing $FF -- exactly $FF
R_WROTE_1F = 0x02       # after writing $1F -- exactly $FF
R_WROTE_E0 = 0x03       # after writing $E0 -- upper set, real bits clear
R_SPURIOUS = 0x04       # dispatches taken with IE=$E0
R_CONTROL = 0x05        # dispatches taken with IE=$01
R_SPUR_DONE = 0x06
R_CTRL_DONE = 0x07
R_DONE = 0x0F

IF_UPPER = 0xE0
IF_REAL = 0x1F


def run() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        gba, sav = tmp / "if.gba", tmp / "if.sav"
        r = subprocess.run(
            [sys.executable, str(COMPILER), "-e", str(EMULATOR),
             "-o", str(gba), str(ROM)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"ERROR: compile failed: {r.stderr}")
            sys.exit(2)
        cmd = [str(RUNNER), str(gba), str(FRAMES), "/dev/null",
               "--savefile", str(sav)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
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
    print(f"  FF0F after $00={res[R_WROTE_00]:#04x} $FF={res[R_WROTE_FF]:#04x} "
          f"$1F={res[R_WROTE_1F]:#04x} $E0={res[R_WROTE_E0]:#04x}")
    print(f"  dispatches: IE=$E0 -> {res[R_SPURIOUS]}, "
          f"IE=$01 -> {res[R_CONTROL]} (control)")

    # Both phases have to have run, or the counters below mean nothing.
    if res[R_SPUR_DONE] != 0x5A or res[R_CTRL_DONE] != 0x5A:
        print(f"FAIL: the ROM did not finish both phases "
              f"(spurious={res[R_SPUR_DONE]:#04x}, "
              f"control={res[R_CTRL_DONE]:#04x})")
        sys.exit(1)
    # The positive control: if a real VBlank never dispatched, a zero spurious
    # count would only mean interrupts are broken outright.
    if res[R_CONTROL] == 0:
        print(f"FAIL: no interrupt dispatched even with IE=$01 and IME=1 -- "
              f"interrupts are not working at all, so this run cannot tell us "
              f"anything about #42")
        sys.exit(1)

    bad = []

    if res[R_WROTE_00] & IF_UPPER != IF_UPPER:
        bad.append(f"FF0F read back {res[R_WROTE_00]:#04x} after writing $00; "
                   f"the upper 3 bits are wired high on hardware and must "
                   f"read 1 (expected the $E0 bits set)")

    if res[R_WROTE_FF] != 0xFF:
        bad.append(f"FF0F read back {res[R_WROTE_FF]:#04x} after writing $FF, "
                   f"expected $FF ($E0 phantom bits | $1F real flags)")

    if res[R_WROTE_1F] != 0xFF:
        bad.append(f"FF0F read back {res[R_WROTE_1F]:#04x} after writing $1F, "
                   f"expected $FF ($E0 phantom bits | $1F real flags)")

    if res[R_WROTE_E0] & IF_UPPER != IF_UPPER:
        bad.append(f"FF0F read back {res[R_WROTE_E0]:#04x} after writing $E0; "
                   f"the upper 3 bits must read 1")
    elif res[R_WROTE_E0] & IF_REAL == IF_REAL:
        bad.append(f"FF0F read back {res[R_WROTE_E0]:#04x} after writing $E0; "
                   f"writing the phantom bits must not set the 5 real "
                   f"interrupt flags")

    if res[R_SPURIOUS] != 0:
        bad.append(f"{res[R_SPURIOUS]} interrupt(s) dispatched with IE=$E0 -- "
                   f"none of the 5 real interrupts was enabled, so nothing "
                   f"may fire.  IF kept its phantom upper bits, they matched "
                   f"IE, and the priority chain fell through to the "
                   f"unknown-IRQ tail that dispatches to vector 0x40")

    if res[R_DONE] != 0x5A and not bad:
        bad.append(f"the ROM did not reach its final marker "
                   f"({res[R_DONE]:#04x})")

    if bad:
        for b in bad:
            print(f"FAIL: {b}")
        sys.exit(1)

    print("\nPASS: FF0F reads back 0xE0 | IF, writes touch only the 5 real "
          "flags, and phantom IE bits dispatch nothing")
    sys.exit(0)


if __name__ == "__main__":
    main()
