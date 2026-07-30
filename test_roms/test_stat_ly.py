#!/usr/bin/env python3
"""STAT (FF41) register-accuracy test (issue #52).

Six independent holes in the STAT emulation, all in the parts of the cluster
that guest code can observe:

  1. STAT bit 7 read back as 0.  It is wired high on hardware.  Nothing in
     FF41_R's LCD_HACKS dispatcher ORed it in, and the dispatcher has many
     exits, so the bit now lives in the stored STAT byte -- which is the
     immediate of the `mov r0,#imm` that every exit starts from.
  2. The mode bits freewheeled while the LCD was off.  FF41_R derives the mode
     from the cycle counter, which keeps counting when the LCD is disabled;
     hardware reports mode 0 the whole time.
  3. Writing FF41 fired a STAT IRQ off the *stored* mode field, which line0
     clears for the whole visible frame -- so enabling bit 3 or 5 mid-frame
     fired instantly, every time, on CGB as well as DMG and with the LCD off.
     The DMG STAT-write bug itself is real and is kept; it is now gated on
     DMG + LCD-on + a real current mode that is not mode 3.
  4. LYC writes raised STAT with the LCD disabled, off the free-running
     internal scanline counter.
  5. Entering line 144 asserts the mode-2 (OAM) condition as well as mode 1, so
     a game that arms only bit 5 still gets a STAT IRQ at VBlank start.  Only
     bit 4 was checked.
  6. STAT IRQ blocking was asymmetric: LYC coincidence suppressed mode-0/2
     interrupts, but mode-0 IE holding the line high through the preceding
     HBlank did not suppress the LYC edge.

The expected values are not taken on faith from the issue: this test runs the
same probe ROM directly in mGBA's own GB core and requires ChromA to agree with
it, so an independent implementation backs every assertion.  That reference run
also settled three questions the issue left open:

  - the DMG STAT-write bug must be preserved (mGBA sets IF bit 1 there too), so
    the LCD-off/CGB gates must not be written as a blanket suppression;
  - the line-144 mode-2 condition is not DMG-only, so it is not gated on model;
  - item 8 of the issue -- suppressing LYC edges when mode-0 IE held the line
    high through the preceding HBlank -- is NOT applied.  mGBA reports the same
    144 STAT IRQs per frame whether or not LYC IE is added to mode-0 IE, which
    is what ChromA already did; adding the block drops it to 143 and moves away
    from the reference.  The counts are asserted here to keep it that way.

The probe is run twice, once as a DMG ROM and once with the CGB flag set, since
the write-bug gate is model-dependent and most of the commercial visual
baselines are CGB titles.
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
ROM_DMG = SCRIPT_DIR / "stat_ly_test.gb"
ROM_CGB = SCRIPT_DIR / "stat_ly_test_cgb.gbc"

FRAMES = 900
GAME_SRAM_SIZE = 0x2000

R_AND_ON = 0x00         # AND of 64 FF41 reads, LCD on
R_OR_ON = 0x01          # OR of the same
R_MODES_OFF = 0x02      # OR of (FF41 & 3) over 256 reads, LCD off
R_AND_OFF = 0x03        # AND of those reads
R_OR_OFF = 0x04         # OR of those reads
R_IF_LYCW_OFF = 0x05    # IF after the LYC sweep with the LCD off
R_IF_STATW_OFF = 0x06   # IF after FF41 writes with the LCD off
R_IF_STATW_ON = 0x07    # IF after an FF41 write with the LCD on (DMG bug)
R_IF_MODE2_VBL = 0x09   # IF after LY 143->144 with mode-2 IE armed
R_COUNT_MODE0 = 0x0A    # 16-bit LE: STAT dispatches, 4 frames, mode-0 IE
R_COUNT_BOTH = 0x0C     # 16-bit LE: same with mode-0 + LYC IE
R_LYC0_DELAY = 0x0E     # 16-bit LE: LY=144 -> LYC=0 STAT IRQ, loop iterations
R_PHASE = 0x10          # last phase reached
R_DONE = 0x1F

STAT_BIT7 = 0x80
IF_STAT = 0x02
FRAMES_MEASURED = 4


def u16(res, off):
    return res[off] | (res[off + 1] << 8)


def run_chroma(rom):
    """Run the probe inside ChromA, itself running inside mGBA's GBA core."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        gba, sav = tmp / "stat.gba", tmp / "stat.sav"
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
            print(f"ERROR: reference run exited {r.returncode}: {r.stderr[:500]}")
            sys.exit(2)
        data = sav.read_bytes()
    return data[len(data) - GAME_SRAM_SIZE:]


def describe(label, res):
    print(f"  {label}:")
    print(f"    FF41 reads, LCD on:  AND={res[R_AND_ON]:#04x} "
          f"OR={res[R_OR_ON]:#04x}")
    print(f"    FF41 reads, LCD off: mode bits seen={res[R_MODES_OFF]:#04x} "
          f"AND={res[R_AND_OFF]:#04x} OR={res[R_OR_OFF]:#04x}")
    print(f"    IF: lyc-write/off={res[R_IF_LYCW_OFF]:#04x} "
          f"stat-write/off={res[R_IF_STATW_OFF]:#04x} "
          f"stat-write/on={res[R_IF_STATW_ON]:#04x} "
          f"mode2-at-144={res[R_IF_MODE2_VBL]:#04x}")
    print(f"    STAT IRQs over {FRAMES_MEASURED} frames: "
          f"mode0={u16(res, R_COUNT_MODE0)} "
          f"mode0+lyc={u16(res, R_COUNT_BOTH)}")
    print(f"    LY=144 -> LYC=0 IRQ: {u16(res, R_LYC0_DELAY)} iterations")


def check(model, res, ref, is_cgb):
    """Assert one model's results against the mGBA reference for the same ROM."""
    bad = []

    # ---- the reference has to show the behaviour we are testing for --------
    # Otherwise a pass below would only mean "both are broken the same way".
    if not ref[R_OR_ON] & STAT_BIT7:
        print(f"ERROR [{model}]: the mGBA reference does not set STAT bit 7; "
              f"the oracle is not behaving as documented hardware")
        sys.exit(2)
    if not is_cgb and not ref[R_IF_STATW_ON] & IF_STAT:
        print(f"ERROR [{model}]: the mGBA reference did not reproduce the DMG "
              f"STAT-write bug, so the statw-on control proves nothing")
        sys.exit(2)

    # ---- 1. bit 7 is wired high -------------------------------------------
    if not res[R_AND_ON] & STAT_BIT7:
        bad.append(f"STAT bit 7 was clear on at least one read with the LCD on "
                   f"(AND of 64 reads = {res[R_AND_ON]:#04x}); hardware wires "
                   f"it high, and mGBA agrees ({ref[R_AND_ON]:#04x})")
    if not res[R_AND_OFF] & STAT_BIT7:
        bad.append(f"STAT bit 7 was clear on at least one read with the LCD "
                   f"off (AND = {res[R_AND_OFF]:#04x}); it does not depend on "
                   f"the LCD being on")

    # A control, not a bug check: if the mode bits never changed with the LCD
    # on, the LCD-off assertion below would pass for the wrong reason.
    if res[R_OR_ON] & 0x03 == 0:
        bad.append("no mode bits were ever set across 64 FF41 reads with the "
                   "LCD on, so the LCD-off check below is vacuous")

    # ---- 2. mode bits read 0 while the LCD is off -------------------------
    if res[R_MODES_OFF] != 0x00:
        bad.append(f"the STAT mode bits reported {res[R_MODES_OFF]:#04x} with "
                   f"the LCD off; hardware reports mode 0 the whole time "
                   f"(mGBA: {ref[R_MODES_OFF]:#04x}).  The cycle counter keeps "
                   f"running while the LCD is disabled, so the mode must not "
                   f"be derived from it -- and switching the LCD off during "
                   f"VBlank must not leave mode 1 in the stored byte")

    # ---- 3./4. no STAT IRQ can be raised with the LCD off -----------------
    if res[R_IF_LYCW_OFF] & IF_STAT:
        bad.append(f"an LYC write raised a STAT IRQ with the LCD off "
                   f"(IF={res[R_IF_LYCW_OFF]:#04x}); the internal scanline "
                   f"counter free-runs while disabled, but hardware is not "
                   f"reporting it and drives no STAT line (mGBA: "
                   f"{ref[R_IF_LYCW_OFF]:#04x})")
    if res[R_IF_STATW_OFF] & IF_STAT:
        bad.append(f"writing FF41 raised a STAT IRQ with the LCD off "
                   f"(IF={res[R_IF_STATW_OFF]:#04x}); there is no STAT line to "
                   f"drive (mGBA: {ref[R_IF_STATW_OFF]:#04x})")

    # The write-triggered IRQ is model-dependent: it is a real DMG bug that has
    # to survive the gating above, and it does not exist on CGB at all.
    if is_cgb:
        if res[R_IF_STATW_ON] & IF_STAT:
            bad.append(f"writing FF41 raised a STAT IRQ on CGB "
                       f"(IF={res[R_IF_STATW_ON]:#04x}); the STAT-write bug is "
                       f"DMG-only and CGB has no write-triggered STAT IRQ "
                       f"(mGBA: {ref[R_IF_STATW_ON]:#04x})")
    else:
        if not res[R_IF_STATW_ON] & IF_STAT:
            bad.append(f"writing FF41 on DMG with the LCD on did NOT raise a "
                       f"STAT IRQ (IF={res[R_IF_STATW_ON]:#04x}); the DMG "
                       f"STAT-write bug is real and mGBA reproduces it "
                       f"({ref[R_IF_STATW_ON]:#04x}), so the LCD-off and CGB "
                       f"gates have been made too broad")

    # ---- 5. mode-2 condition asserts at VBlank start ----------------------
    if not res[R_IF_MODE2_VBL] & IF_STAT:
        bad.append(f"entering line 144 with only mode-2 IE armed raised no "
                   f"STAT IRQ (IF={res[R_IF_MODE2_VBL]:#04x}); the mode-2 "
                   f"condition asserts at VBlank start as well as mode 1 "
                   f"(mGBA: {ref[R_IF_MODE2_VBL]:#04x})")

    # ---- 6. LYC edges are NOT lost when mode-0 IE is also enabled ----------
    # See the module docstring: this is the opposite of what issue #52 item 8
    # asks for, and it is what the reference does.
    count_mode0 = u16(res, R_COUNT_MODE0)
    count_both = u16(res, R_COUNT_BOTH)
    ref_mode0 = u16(ref, R_COUNT_MODE0)
    ref_both = u16(ref, R_COUNT_BOTH)
    if count_mode0 == 0:
        bad.append(f"mode-0 IE produced no STAT interrupts at all over "
                   f"{FRAMES_MEASURED} frames, so the comparison below is "
                   f"vacuous")
    elif abs(count_both - count_mode0) > 1:
        bad.append(f"adding LYC IE to mode-0 IE changed the STAT count from "
                   f"{count_mode0} to {count_both} over {FRAMES_MEASURED} "
                   f"frames; mGBA reports {ref_mode0} and {ref_both}, i.e. no "
                   f"net change, so neither an extra nor a lost interrupt "
                   f"belongs here")

    return bad


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"),
                       (ROM_DMG, ROM_DMG.name), (ROM_CGB, ROM_CGB.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    failures = []
    for model, rom, is_cgb in (("DMG", ROM_DMG, False), ("CGB", ROM_CGB, True)):
        print(f"\n{model} ({rom.name}):")
        res = run_chroma(rom)
        ref = run_reference(rom)
        describe("ChromA", res)
        describe(f"mGBA {model} reference", ref)

        if res[R_DONE] != 0x5A:
            print(f"FAIL: the {model} ROM did not finish; it reached phase "
                  f"{res[R_PHASE]} and left the done marker at "
                  f"{res[R_DONE]:#04x}")
            sys.exit(1)
        if ref[R_DONE] != 0x5A:
            print(f"ERROR: the {model} reference run did not finish (phase "
                  f"{ref[R_PHASE]}), so it cannot be used as an oracle")
            sys.exit(2)

        # Informational only -- see the issue discussion of the LY=153->0
        # window (item 6), which this change deliberately does not touch.
        print(f"  note: LY=144 -> LYC=0 STAT IRQ took "
              f"{u16(res, R_LYC0_DELAY)} loop iterations in ChromA vs "
              f"{u16(ref, R_LYC0_DELAY)} in mGBA (not asserted)")

        failures += [f"[{model}] {b}" for b in check(model, res, ref, is_cgb)]

    print()
    if failures:
        for b in failures:
            print(f"FAIL: {b}")
        sys.exit(1)

    print("PASS: STAT bit 7, LCD-off mode reporting, the LCD-off IRQ gates, "
          "the DMG-only write bug, the line-144 mode-2 condition and the "
          "LYC/mode-0 IRQ counts all match mGBA on both DMG and CGB")


if __name__ == "__main__":
    main()
