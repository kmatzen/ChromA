#!/usr/bin/env python3
"""Timer phase-coherence regression test (issue #44 item 1).

`checkTimerIRQ` detected one carry per scanline and then stored a flat
TMA<<24, discarding the sub-period remainder.  The timer restarted from phase
zero at every scanline boundary containing an overflow, so it drifted
steadily -- and `_FF05R`, which projects reads forward from that committed
value, inherited the error.

Detecting this needs no cycle-exact test code.  The timer is a free-running
counter with a fixed period and timer_phase_test.gb samples it with a loop of
fixed length, so the sequence of readings must be *periodic*.  That is a
property of any free-running counter sampled at a regular interval.  A
scanline is 456 T-cycles and the selected period is 16, so a scanline is 28.5
periods: an implementation that flattens the phase at scanline boundaries
cannot produce a periodic sequence.

The reference is mGBA's own Game Boy core running the same ROM, the same way
test_stat_ly.py and test_lcdc_flags.py establish theirs.  ChromA has to match
mGBA's *minimal period*, not its sample values: matching values additionally
requires the 4-cycle TIMA==0 reload window (issue #44 item 3), which is still
open -- mGBA reports $00 inside it and ChromA never does.

Measured: mGBA 4, ChromA 19 before the fix (44 of 60 period-4 comparisons
mismatched) and 4 after.
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
ROM = SCRIPT_DIR / "timer_phase_test.gb"

CHROMA_FRAMES = 900
NATIVE_FRAMES = 400
GAME_SRAM_SIZE = 0x2000

N_SAMPLES = 64
R_DONE = 0x40


def run(rom_or_gba, frames, strip_goomba_header):
    with tempfile.TemporaryDirectory() as tmp:
        sav = Path(tmp) / "phase.sav"
        try:
            r = subprocess.run(
                [str(RUNNER), str(rom_or_gba), str(frames), "/dev/null",
                 "--savefile", str(sav)],
                capture_output=True, text=True, timeout=300,
            )
        except subprocess.TimeoutExpired:
            print("ERROR: runner timed out")
            sys.exit(2)
        if r.returncode != 0:
            print(f"ERROR: runner exited {r.returncode}: {r.stderr[:400]}")
            sys.exit(2)
        data = sav.read_bytes()
    # ChromA's .sav is its own save heap with the game's cart RAM at the end;
    # mGBA's Game Boy core writes the cart RAM alone.
    if strip_goomba_header:
        data = data[len(data) - GAME_SRAM_SIZE:]
    return data


def compile_for_chroma(tmpdir):
    gba = Path(tmpdir) / "phase.gba"
    r = subprocess.run(
        [sys.executable, str(COMPILER), "-e", str(EMULATOR), "-o", str(gba),
         str(ROM)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"ERROR: compile failed: {r.stderr}")
        sys.exit(2)
    return gba


def minimal_period(samples):
    """Smallest p such that the sequence repeats with period p, or None."""
    for p in range(1, len(samples) // 2 + 1):
        if all(samples[i] == samples[i + p] for i in range(len(samples) - p)):
            return p
    return None


def violations(samples, p):
    return sum(1 for i in range(len(samples) - p) if samples[i] != samples[i + p])


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"), (ROM, ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    native = run(ROM, NATIVE_FRAMES, strip_goomba_header=False)
    with tempfile.TemporaryDirectory() as tmp:
        chroma = run(compile_for_chroma(tmp), CHROMA_FRAMES,
                     strip_goomba_header=True)

    n_samples = list(native[:N_SAMPLES])
    c_samples = list(chroma[:N_SAMPLES])

    print("mGBA reference: " + " ".join(f"{b:02x}" for b in n_samples[:16]) + " ...")
    print("ChromA:         " + " ".join(f"{b:02x}" for b in c_samples[:16]) + " ...")

    if native[R_DONE] != 0x5A:
        print(f"FAIL: the ROM did not complete under mGBA's Game Boy core "
              f"(marker={native[R_DONE]:#04x}) -- the reference is unusable")
        sys.exit(1)
    if chroma[R_DONE] != 0x5A:
        print(f"FAIL: the ROM did not complete under ChromA "
              f"(marker={chroma[R_DONE]:#04x}, expected 0x5a)")
        sys.exit(1)

    n_period = minimal_period(n_samples)
    c_period = minimal_period(c_samples)
    print(f"  mGBA minimal period:   {n_period}")
    print(f"  ChromA minimal period: {c_period}")

    if n_period is None:
        print("FAIL: mGBA's own readings are not periodic -- the reference is "
              "unusable, so this test cannot conclude anything")
        sys.exit(1)

    if c_period != n_period:
        v = violations(c_samples, n_period)
        print(f"FAIL: ChromA's TIMA readings repeat with period {c_period}, "
              f"not {n_period} ({v} of {len(c_samples) - n_period} "
              f"period-{n_period} comparisons mismatch).")
        print("      A free-running counter sampled at a fixed interval has "
              "to give a periodic sequence; an aperiodic one means the timer "
              "loses its sub-period phase, which is what storing a flat "
              "TMA<<24 per scanline does.")
        sys.exit(1)

    print(f"\nPASS: ChromA's timer keeps its phase across scanlines "
          f"(period {c_period}, matching mGBA)")
    sys.exit(0)


if __name__ == "__main__":
    main()
