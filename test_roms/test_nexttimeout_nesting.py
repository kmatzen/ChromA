#!/usr/bin/env python3
"""Test nexttimeout_alt nesting hazards.

ChromA has three mechanisms that hijack `nexttimeout`, stash the old value in
`nexttimeout_alt`, and restore it later -- all sharing one global slot -- plus a
fourth site that overwrites `nexttimeout` outright:

  1. EI deferral            src/gbz80.s:1704  -> ei_finish
  2. immediate_check_irq_2  src/timeout.s:370 -> no_more_irq_hack
  3. checkIRQDelayed        src/timeout.s:546 -> checkMasterIRQ_minus12
  4. FF40_W (LCD on)        src/lcd.s:3760/3765

The only guard (src/timeout.s:365-367) stops (2) clobbering (3). Nothing stops
(2) clobbering (1), or (4) landing on top of (1).

Two ROMs are run, differing by ONE instruction:

  nexttimeout_control.gb      `EI; NOP; LDH [reg],a`  -- write outside the window
  nexttimeout_nesting_test.gb `EI; LDH [reg],a`       -- write inside the window

The control must pass. If it does not, this harness is broken and the result
says nothing about the emulator -- that is reported as an ERROR, not a FAIL.
Only when the control passes is a hazard-ROM failure attributable to the
deferral window.

Expected while the hazards are unfixed: control PASS, hazard FAIL.
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
CONTROL_ROM = SCRIPT_DIR / "nexttimeout_control.gb"
HAZARD_ROM = SCRIPT_DIR / "nexttimeout_nesting_test.gb"

PHASES = {
    0x00: "never started (SRAM not written)",
    0x01: "init done",
    0x02: "test C complete",
    0x03: "test A armed",
    0x04: "test A sequence survived",
    0x05: "test A complete",
}


def run_rom(rom):
    """Run one ROM through chroma and return the 16 result bytes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        gba = tmpdir / "t.gba"
        sav = tmpdir / "t.sav"

        r = subprocess.run(
            [sys.executable, str(COMPILER), "-e", str(EMULATOR), "-o", str(gba), str(rom)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            return None, f"compile error: {r.stderr}"

        try:
            r = subprocess.run(
                [str(RUNNER), str(gba), "600", "/dev/null", "--savefile", str(sav)],
                capture_output=True, text=True, timeout=120,
            )
        except subprocess.TimeoutExpired:
            return None, "runner timed out"
        if r.returncode != 0:
            return None, f"runner exited {r.returncode}: {r.stderr}"

        # 8KB game SRAM inside 32KB GBA SRAM -> write-through starts at 0x6000
        return sav.read_bytes()[0x6000:0x6010], None


def describe(res):
    return (f"phase=0x{res[0]:02X} ({PHASES.get(res[0], '?')}) isr={res[1]} "
            f"testC=0x{res[2]:02X} testA=0x{res[3]:02X} "
            f"LY {res[4]}->{res[5]} sentinel=0x{res[15]:02X}")


def evaluate(res):
    """Return list of failure strings for one run."""
    bad = []
    if res[15] != 0xFF:
        bad.append(f"ROM did not reach the end (stopped at phase 0x{res[0]:02X})")
    if res[2] != 0xAA:
        bad.append("test C: EI was lost -- ISR did not fire on a pending, enabled VBlank")
    if res[3] != 0xAA:
        bad.append("test A: LY stopped advancing -- scanline state machine lost")
    return bad


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (CONTROL_ROM, CONTROL_ROM.name), (HAZARD_ROM, HAZARD_ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    control, err = run_rom(CONTROL_ROM)
    if err:
        print(f"ERROR: control ROM: {err}")
        sys.exit(2)
    print(f"control (EI; NOP; LDH): {describe(control)}")

    control_bad = evaluate(control)
    if control_bad:
        print()
        for b in control_bad:
            print(f"ERROR: control ROM failed: {b}")
        print("The control puts the write OUTSIDE the EI deferral window, so it must")
        print("pass. This harness is broken; the result says nothing about nesting.")
        sys.exit(2)

    hazard, err = run_rom(HAZARD_ROM)
    if err:
        print(f"ERROR: hazard ROM: {err}")
        sys.exit(2)
    print(f"hazard  (EI; LDH):      {describe(hazard)}")
    print()

    hazard_bad = evaluate(hazard)
    if not hazard_bad:
        print("PASS: both unguarded nexttimeout_alt pairs survived")
        sys.exit(0)

    for b in hazard_bad:
        print(f"FAIL: {b}")
    print()
    print("Control passed and the hazard ROM differs by exactly one NOP, so the")
    print("failure is attributable to the instruction landing inside the EI")
    print("deferral window while nexttimeout_alt is live.")
    sys.exit(1)


if __name__ == "__main__":
    main()
