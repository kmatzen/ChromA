#!/usr/bin/env python3
"""LCDC (FF40) writes must not disturb the guest F register (issue #95).

`FF40W_entry` used r3 as a scratch register in two places -- `ldrb_ r3,scanline`
on the mid-frame sprite-enable/sprite-size path, and `ldr_ r3,nexttimeout` on
the LCD-turned-on path -- but r3 is `gb_flg`, the guest's F register.  IO write
handlers are entered by a direct jump from `io_write_tbl` with nothing saved, so
any LCDC write reaching either path silently wiped all four guest flags.

All four flags live in bits 28-31 of `gb_flg` (ARM's own NZCV positions, with H
in the V slot), so overwriting r3 with a scanline byte -- which only ever sets
bits 0-7 -- or with an IWRAM/ROM pointer, whose top nibble is 0, left every flag
decoding as 0.  The corruption was therefore deterministic rather than
timing-dependent: F read back $00, and always cleared rather than set.  The
guest-visible symptom was `jr z`/`jr c` never taken and `jr nz`/`jr nc` always
taken immediately after an LCDC write.

Writing an IO register cannot change F on hardware, so every slot must read back
exactly what its phase preset.  The expected values are not taken on faith: this
runs the same probe ROM directly in mGBA's own GB core and requires ChromA to
agree with it, so an independent implementation backs every assertion.

Two controls make a pass meaningful rather than vacuous:

  - `bit4` is a real LCDC value change to a bit neither r3 site tracks.  It was
    preserved even with the bug present, so it isolates the fault to those two
    paths and rules out the probe or the `push af` capture being at fault.  If
    it ever fails, something much broader than #95 is wrong.
  - `none` performs no IO write at all, proving the capture sequence itself does
    not disturb F.

The `inverse` phases preset F=$00 instead of $F0.  The bug only ever cleared
flags, so those phases passed while it was present; they are here to catch the
opposite regression -- a handler that spuriously *sets* flags -- which a probe
using only an all-set F value would miss.
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
ROM = SCRIPT_DIR / "lcdc_flags_test.gb"

FRAMES = 120
GAME_SRAM_SIZE = 0x2000

R_BIT1 = 0x00           # F after an LCDC bit 1 (sprite enable) change
R_BIT2 = 0x01           # F after an LCDC bit 2 (sprite size) change
R_LCDON = 0x02          # F after the LCD is turned on (bit 7 0->1)
R_BIT4 = 0x03           # F after an untracked bit 4 change (control)
R_NONE = 0x04           # F with no IO write at all (control)
R_LINE0 = 0x05          # F after a bit 1 change with the scanline byte near 0
R_BIT1_INV = 0x06       # same as R_BIT1 but preset F=$00
R_LCDON_INV = 0x07      # same as R_LCDON but preset F=$00
R_PHASE = 0x10          # last phase reached
R_DONE = 0x1F

F_ALL = 0xF0            # Z N H C all set -- what the main phases preset
F_NONE = 0x00           # what the inverse phases preset
DONE_MARK = 0x5A
PHASE_COUNT = 8

# (slot, preset, label, is_control)
CASES = (
    (R_BIT1, F_ALL, "an LCDC bit 1 (sprite enable) change", False),
    (R_BIT2, F_ALL, "an LCDC bit 2 (sprite size) change", False),
    (R_LCDON, F_ALL, "the LCD being turned on (bit 7 0->1)", False),
    (R_LINE0, F_ALL, "a bit 1 change with the scanline byte near 0", False),
    (R_BIT1_INV, F_NONE, "an LCDC bit 1 change, with F preset to $00", False),
    (R_LCDON_INV, F_NONE, "the LCD being turned on, with F preset to $00", False),
    (R_BIT4, F_ALL, "an untracked LCDC bit 4 change", True),
    (R_NONE, F_ALL, "no IO write at all", True),
)


def run_chroma(rom):
    """Run the probe inside ChromA, itself running inside mGBA's GBA core."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        gba, sav = tmp / "lcdc.gba", tmp / "lcdc.sav"
        r = subprocess.run(
            [sys.executable, str(COMPILER), "-e", str(EMULATOR),
             "-o", str(gba), str(rom)],
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


def run_reference(rom):
    """Run the probe directly in mGBA's own GB core, as a hardware reference."""
    with tempfile.TemporaryDirectory() as tmp:
        sav = Path(tmp) / "ref.sav"
        try:
            r = subprocess.run(
                [str(RUNNER), str(rom), str(FRAMES), "/dev/null",
                 "--savefile", str(sav)],
                capture_output=True, text=True, timeout=300,
            )
        except subprocess.TimeoutExpired:
            print("ERROR: reference run timed out")
            sys.exit(2)
        if r.returncode != 0:
            print(f"ERROR: reference run exited {r.returncode}: "
                  f"{r.stderr[:500]}")
            sys.exit(2)
        data = sav.read_bytes()
    return data[len(data) - GAME_SRAM_SIZE:]


def describe(label, res):
    print(f"  {label}:")
    print(f"    F after bit1={res[R_BIT1]:#04x} bit2={res[R_BIT2]:#04x} "
          f"lcdon={res[R_LCDON]:#04x} line0={res[R_LINE0]:#04x}")
    print(f"    controls:    bit4={res[R_BIT4]:#04x} "
          f"none={res[R_NONE]:#04x}   (both must be {F_ALL:#04x})")
    print(f"    inverse:     bit1={res[R_BIT1_INV]:#04x} "
          f"lcdon={res[R_LCDON_INV]:#04x}   (both must be {F_NONE:#04x})")
    print(f"    phase={res[R_PHASE]} done={res[R_DONE]:#04x}")


def check(res, ref):
    bad = []

    # ---- the oracle has to agree that F survives an IO write ---------------
    # Otherwise a pass below could only mean "both are broken the same way".
    for slot, preset, label, _ in CASES:
        if ref[slot] != preset:
            print(f"ERROR: the mGBA reference left F at {ref[slot]:#04x} after "
                  f"{label}, not the {preset:#04x} it preset.  Writing an IO "
                  f"register cannot change F on hardware, so the oracle is not "
                  f"behaving as documented and proves nothing")
            sys.exit(2)

    # ---- the controls first: they decide how to read any other failure -----
    for slot, preset, label, is_control in CASES:
        if not is_control:
            continue
        if res[slot] != preset:
            bad.append(f"CONTROL: F was {res[slot]:#04x} after {label}, not the "
                       f"{preset:#04x} preset (mGBA: {ref[slot]:#04x}).  This "
                       f"path reaches neither r3 site, so a failure here is "
                       f"broader than issue #95 -- treat the results below as "
                       f"unreliable until it is explained")

    # ---- the real assertions ----------------------------------------------
    for slot, preset, label, is_control in CASES:
        if is_control:
            continue
        if res[slot] == preset:
            continue
        extra = ""
        if preset == F_ALL and res[slot] == 0x00:
            extra = ("  F read back exactly $00, which is the signature of "
                     "gb_flg (r3) being overwritten with a value whose bits "
                     "28-31 are clear -- i.e. an IO handler using r3 as scratch")
        bad.append(f"F was {res[slot]:#04x} after {label}, not the "
                   f"{preset:#04x} preset (mGBA: {ref[slot]:#04x}).  Writing "
                   f"an IO register cannot change F on hardware.{extra}")

    return bad


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"), (ROM, ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    res = run_chroma(ROM)
    ref = run_reference(ROM)
    describe("ChromA", res)
    describe("mGBA DMG reference", ref)

    if res[R_DONE] != DONE_MARK:
        print(f"FAIL: the ROM did not finish; it reached phase {res[R_PHASE]} "
              f"of {PHASE_COUNT} and left the done marker at "
              f"{res[R_DONE]:#04x}")
        sys.exit(1)
    if ref[R_DONE] != DONE_MARK:
        print(f"ERROR: the reference run did not finish (phase "
              f"{ref[R_PHASE]}), so it cannot be used as an oracle")
        sys.exit(2)

    print()
    failures = check(res, ref)
    if failures:
        for b in failures:
            print(f"FAIL: {b}")
        sys.exit(1)

    print("PASS: the guest F register survives LCDC writes that change sprite "
          "enable, sprite size and the LCD on/off bit, on and off line 0, with "
          "flags both all-set and all-clear -- matching mGBA")


if __name__ == "__main__":
    main()
