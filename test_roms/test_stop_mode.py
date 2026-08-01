#!/usr/bin/env python3
"""STOP with no armed speed switch parks the CPU and the joypad wakes it (#152).

ChromA's `_10` handler used to perform the CGB speed switch when one was armed
and otherwise do nothing but skip the operand byte, so a plain STOP ran
straight on.  There was no stop mode and no joypad wake.

`test_stop_div.py` cannot see this: it arms the speed switch first, precisely
because that is the STOP that resumes on its own.  This probe is the other
half, and it needs two runs to say anything at all:

    no input held   the probe must NOT finish   (the CPU is parked)
    a button held   the probe must finish       (the joypad woke it)

Either arm alone is satisfied by a broken build -- one that ignores STOP
finishes both, one that parks forever finishes neither.  Only the split is
evidence, so "did not finish" is asserted here rather than being a timeout.

mGBA's Game Boy core is run over the same ROM as a reference.  It is reported
either way, but only *required* to agree when it actually implements the park;
if the reference finishes the no-input arm then it has no stop mode of its own
and cannot judge ChromA's, which the output says explicitly rather than
silently passing.

Run: python3 test_roms/test_stop_mode.py
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
ROM = SCRIPT_DIR / "stop_mode_test.gb"

FRAMES = 600
GAME_SRAM_SIZE = 0x2000

R_REACHED, R_RESUMED, R_DONE = 0x00, 0x01, 0x0F

# Held from well after the probe has parked through to the end of the run, so
# the wake cannot be blamed on a press that was already down when STOP ran.
WAKE_INPUT = "200:A:300"


def run(wrap, press):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        sav = tmp / "sm.sav"
        if wrap:
            target = tmp / "sm.gba"
            r = subprocess.run(
                [sys.executable, str(COMPILER), "-e", str(EMULATOR),
                 "-o", str(target), str(ROM)],
                capture_output=True, text=True)
            if r.returncode != 0:
                print(f"ERROR: compile failed: {r.stderr[:300]}")
                sys.exit(2)
        else:
            target = ROM
        cmd = [str(RUNNER), str(target), str(FRAMES), "/dev/null",
               "--savefile", str(sav)]
        if press:
            cmd += ["--input", WAKE_INPUT]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            print("ERROR: runner timed out")
            sys.exit(2)
        if r.returncode != 0:
            print(f"ERROR: runner exited {r.returncode}: {r.stderr[:300]}")
            sys.exit(2)
        data = sav.read_bytes()
    return data[:GAME_SRAM_SIZE] if not wrap else data[-GAME_SRAM_SIZE:]


def describe(res):
    return (f"reached={res[R_REACHED]:#04x} resumed={res[R_RESUMED]:#04x} "
            f"done={res[R_DONE]:#04x}")


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"), (ROM, ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    ref_idle = run(wrap=False, press=False)
    ref_wake = run(wrap=False, press=True)
    got_idle = run(wrap=True, press=False)
    got_wake = run(wrap=True, press=True)

    print(f"  mGBA   no input : {describe(ref_idle)}")
    print(f"  mGBA   button   : {describe(ref_wake)}")
    print(f"  ChromA no input : {describe(got_idle)}")
    print(f"  ChromA button   : {describe(got_wake)}")

    bad = []

    # The probe has to have got as far as the STOP in every arm, or nothing
    # below distinguishes "parked" from "crashed on the way there".
    for label, res in (("mGBA no input", ref_idle), ("mGBA button", ref_wake),
                       ("ChromA no input", got_idle),
                       ("ChromA button", got_wake)):
        if res[R_REACHED] != 0x11:
            bad.append(f"{label}: never reached the STOP "
                       f"(A000={res[R_REACHED]:#04x}), so this run says "
                       f"nothing about stop mode")

    if not bad:
        if got_idle[R_DONE] == 0x5A:
            bad.append("ChromA ran straight through a STOP with no armed "
                       "speed switch -- there is no stop mode")
        if got_wake[R_DONE] != 0x5A:
            bad.append("ChromA never resumed from STOP with a button held -- "
                       "the joypad wake is missing, which hangs any game that "
                       "uses STOP deliberately")

    if not bad:
        ref_parks = ref_idle[R_DONE] != 0x5A
        ref_wakes = ref_wake[R_DONE] == 0x5A
        if ref_parks and ref_wakes:
            print("  reference: mGBA parks on STOP and wakes on the joypad -- "
                  "ChromA agrees")
        else:
            print(f"  reference: mGBA does not model stop mode "
                  f"(parks={ref_parks}, wakes={ref_wakes}), so it cannot "
                  f"judge this; ChromA is asserted against hardware "
                  f"behaviour alone")

    if bad:
        print()
        for b in bad:
            print("FAIL: " + b)
        sys.exit(1)

    print()
    print("PASS: STOP parks the CPU and a joypad press resumes it")


if __name__ == "__main__":
    main()
