#!/usr/bin/env python3
"""Serial register behaviour and transfer duration (issue #153).

Runs serial_test.gb twice -- once wrapped in ChromA, once on mGBA's own Game
Boy core as the reference -- and compares four properties that ChromA got
wrong.  None of them need a second Game Boy attached: with no cable the other
end holds the line high, which is well defined.

    A. SB reads back the byte written to it, while no transfer has completed.
       ChromA returned a flat 0xFF.
    B. SC's unused bits read 1.  ChromA returned the stored byte.
    C. An internal-clock transfer takes 4096 T-cycles, measured as how long
       SC bit 7 stays set.  ChromA completed at the next scanline boundary,
       so at most 456.
    D. Once it completes SB reads 0xFF and the serial interrupt is requested.

D is the half that makes A safe, and it is why this can be landed when the
same read-back had to be reverted during the #110 work.  Pokemon's link-cable
detection writes a byte, starts a transfer and reads SB back; if it sees its
own byte it decides a cable is attached.  Returning the written byte without
modelling the transfer is what broke it.  With the transfer modelled, SB reads
0xFF once it finishes -- identical to the old behaviour -- and only reads
taken *during* the transfer differ.

Measured:

    mGBA native   SB_before=0x5a SC=0xff SB_after=0xff busy=68
    ChromA before SB_before=0xff SC=0x81 SB_after=0xff busy=5
    ChromA after  SB_before=0x5a SC=0xff SB_after=0xff busy=66

Usage:
    python3 test_roms/test_serial.py
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
ROM = SCRIPT_DIR / "serial_test.gb"

FRAMES = 600
GAME_SRAM_SIZE = 0x2000

R_SB_BEFORE = 0x00
R_SC_READ = 0x01
R_SB_AFTER = 0x02
R_COUNT_LO = 0x03
R_COUNT_HI = 0x04
R_IF = 0x05
R_DONE = 0x0F

# ChromA retires the transfer a scanline at a time, so its duration is
# quantised to 456 T-cycles out of 4096 -- about 11%.  The check is that the
# transfer lasts roughly as long as the reference, not that it is exact; the
# bug this guards against is a transfer an order of magnitude too short.
COUNT_TOLERANCE = 0.20


def run(rom, native):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        target, sav = tmp / "serial.gba", tmp / "serial.sav"
        if native:
            target = rom
        else:
            r = subprocess.run(
                [sys.executable, str(COMPILER), "-e", str(EMULATOR),
                 "-o", str(target), str(rom)],
                capture_output=True, text=True)
            if r.returncode != 0:
                print(f"ERROR: compile failed: {r.stderr}")
                sys.exit(2)
        try:
            r = subprocess.run(
                [str(RUNNER), str(target), str(FRAMES), "/dev/null",
                 "--savefile", str(sav)],
                capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            print("ERROR: runner timed out")
            sys.exit(2)
        if r.returncode != 0:
            print(f"ERROR: runner exited {r.returncode}: {r.stderr[:400]}")
            sys.exit(2)
        data = sav.read_bytes()
    return data[len(data) - GAME_SRAM_SIZE:]


def report(name, res):
    count = res[R_COUNT_LO] | (res[R_COUNT_HI] << 8)
    print(f"  {name:<14} SB_before={res[R_SB_BEFORE]:#04x} "
          f"SC={res[R_SC_READ]:#04x} SB_after={res[R_SB_AFTER]:#04x} "
          f"busy={count} IF={res[R_IF]:#04x}")
    return count


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"), (ROM, ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    chroma = run(ROM, native=False)
    native = run(ROM, native=True)

    print("Serial transfer and register read-back (issue #153)\n")
    c_count = report("ChromA", chroma)
    n_count = report("mGBA", native)
    print()

    bad = []
    if chroma[R_DONE] != 0x5A:
        print(f"FAIL: ChromA did not run the probe to completion "
              f"(marker={chroma[R_DONE]:#04x})")
        sys.exit(1)
    if native[R_DONE] != 0x5A:
        print("FAIL: the mGBA reference run did not complete")
        sys.exit(1)

    for idx, what in ((R_SB_BEFORE, "SB read back during a transfer"),
                      (R_SC_READ, "SC read back (unused bits)"),
                      (R_SB_AFTER, "SB read back after the transfer")):
        if chroma[idx] != native[idx]:
            bad.append(f"{what}: ChromA {chroma[idx]:#04x}, "
                       f"mGBA {native[idx]:#04x}")

    if not native[R_IF] & 0x08:
        print("NOTE: the reference did not request a serial interrupt; "
              "the IF check below is skipped")
    elif not chroma[R_IF] & 0x08:
        bad.append(f"no serial interrupt requested (IF={chroma[R_IF]:#04x}), "
                   f"mGBA sets bit 3")

    if n_count == 0:
        bad.append("the reference measured a zero-length transfer")
    elif abs(c_count - n_count) > n_count * COUNT_TOLERANCE:
        bad.append(f"transfer stayed busy for {c_count} poll iterations "
                   f"against mGBA's {n_count} -- more than "
                   f"{COUNT_TOLERANCE:.0%} apart.  A transfer an order of "
                   f"magnitude short means it is still completing at the "
                   f"scanline boundary rather than after 4096 T-cycles")

    if bad:
        for b in bad:
            print(f"FAIL: {b}")
        sys.exit(1)

    print("PASS: SB reads back the written byte during a transfer and 0xFF "
          "after it, SC's unused bits read 1, and the transfer lasts as long "
          "as mGBA's -- all matching the reference")
    sys.exit(0)


if __name__ == "__main__":
    main()
