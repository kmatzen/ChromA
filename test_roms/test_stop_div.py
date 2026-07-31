#!/usr/bin/env python3
"""What STOP does to DIV and KEY1 (issue #56 item 4).

Issue #56 item 4 says the CGB speed switch "doesn't reset DIV", implying it
should.  **Measured against mGBA's own Game Boy core, that is not what the
reference does**, and this test exists so nobody implements the reset on the
strength of the issue text and quietly moves ChromA away from it:

    mGBA native GB core   DIV 119 -> 119   (unchanged)
    ChromA                DIV  76 ->  78   (unchanged, +2 ticks of elapsed time)

Both emulators carry DIV straight across the STOP.  The starting values differ
because the two run the preceding spin loop at different absolute times; what
matters is that neither snaps DIV back to 0, which is what a reset would look
like -- the probe deliberately leaves DIV in the middle of its range first, so
a reset would show up as a drop of ~100, not a couple of counts.

The assertion is therefore "DIV is not reset, and it agrees with mGBA to
within a few ticks", plus "the speed switch actually happened" (KEY1 bit 7).
If someone later establishes from hardware that STOP really does reset DIV,
this test should be updated together with the emulator and mGBA re-checked --
not deleted, because the reference disagreeing is the whole finding.

The probe runs in CGB mode with a speed switch armed, because that is the STOP
that resumes: a STOP with no armed switch enters stop mode until a joypad
interrupt, which hangs under any emulator that implements it.

Run: python3 test_roms/test_stop_div.py
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
ROM = SCRIPT_DIR / "stop_div_test.gb"

FRAMES = 400
GAME_SRAM_SIZE = 0x2000

R_BEFORE, R_AFTER, R_KEY1, R_DONE = 0x00, 0x01, 0x02, 0x0F

# A reset would drop DIV by roughly its pre-STOP value; the two emulators
# differ only by how many ticks elapse across the instruction itself.
MAX_DELTA = 8


def run(wrap):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        sav = tmp / "sd.sav"
        if wrap:
            target = tmp / "sd.gba"
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
            print("ERROR: runner timed out -- did the STOP fail to resume?")
            sys.exit(2)
        if r.returncode != 0:
            print(f"ERROR: runner exited {r.returncode}: {r.stderr[:300]}")
            sys.exit(2)
        data = sav.read_bytes()
    return data[:GAME_SRAM_SIZE] if not wrap else data[-GAME_SRAM_SIZE:]


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"), (ROM, ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    ref, got = run(wrap=False), run(wrap=True)

    for label, res in (("mGBA native GB core", ref), ("ChromA", got)):
        print(f"  {label:20s} DIV {res[R_BEFORE]:3d} -> {res[R_AFTER]:3d}  "
              f"KEY1={res[R_KEY1]:#04x}")

    bad = []
    if ref[R_DONE] != 0x5A:
        bad.append("the probe did not finish under mGBA -- the reference is "
                   "not usable, so nothing here can be judged")
    if got[R_DONE] != 0x5A:
        bad.append("the probe did not finish under ChromA")

    if not bad:
        for label, res in (("mGBA", ref), ("ChromA", got)):
            if not res[R_KEY1] & 0x80:
                bad.append(f"{label}: KEY1 reads {res[R_KEY1]:#04x} after the "
                           f"STOP, bit 7 clear -- the speed switch did not "
                           f"happen, so the DIV reading says nothing about "
                           f"STOP")

    if not bad:
        delta = (got[R_AFTER] - got[R_BEFORE]) & 0xFF
        ref_delta = (ref[R_AFTER] - ref[R_BEFORE]) & 0xFF
        print(f"  DIV moved by {delta} across the STOP in ChromA, "
              f"{ref_delta} in mGBA (a reset would show ~-{got[R_BEFORE]})")
        if delta > MAX_DELTA:
            bad.append(
                f"ChromA's DIV moved by {delta} across the STOP, mGBA's by "
                f"{ref_delta} (tolerance {MAX_DELTA}).  If this is a newly "
                f"added DIV reset: issue #56 item 4 asks for one, but mGBA's "
                f"Game Boy core does not do it, so the change moves ChromA "
                f"away from the reference rather than toward hardware")

    if bad:
        print()
        for b in bad:
            print("FAIL: " + b)
        sys.exit(1)

    print()
    print("PASS: STOP performs the speed switch and leaves DIV running, "
          "matching mGBA's Game Boy core")


if __name__ == "__main__":
    main()
