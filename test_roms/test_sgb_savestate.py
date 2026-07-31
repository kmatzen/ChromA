#!/usr/bin/env python3
"""Adding an SGB section must not break ordinary savestates (issue #51).

SaveSgb returned 0 and LoadSgb returned false, so no SGB section was ever
written: a state taken during the SGB handshake came back with the packet
assembler mid-transfer, the screen mask lost and the multiplayer turn reset.
SaveSgb now emits a 16-byte section, gated on sgb_mode.

The gate is what this test asserts.  LoadState gives up on the *entire* state
the moment any section loader returns false, so a section emitted for a game
that should not have one would not degrade gracefully -- it would break every
savestate for that game.  The asserted half is therefore the DMG round-trip:
Super Mario Land 2 must never see an SGB section, and its states must keep
working exactly as before.

**What this does not prove**, stated plainly because it was measured rather
than assumed: nothing here checks that the section's contents are restored.
The only true-SGB ROM in the bundle, Kirby's Dream Land 2, renders a static
title screen across the entire window the harness can drive (0.0% change over
frames 2400-6000).  Rebuilding with LoadSgb forced to reject its own section
produced byte-identical screenshots and an identical GB WRAM dump, so every
screen- or memory-based assertion available here passes against a deliberately
broken build.  Zelda DX is SGB Enhanced but boots in CGB mode, so its SGB block
stays all-zero and no section is written at all.

The executable guard on the section's field offsets is in
scripts/validate_elf.sh, which fails the build if src/sgb.s is reordered.

Run: python3 test_roms/test_sgb_savestate.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
RUNNER = SCRIPT_DIR / "mgba_runner"
COMPILER = SCRIPT_DIR / "goomba_compile.py"
EMULATOR = PROJECT_DIR / "chroma.gba"
SGB_ROM = SCRIPT_DIR / "Kirby's Dream Land 2 (USA, Europe) (SGB Enhanced).gb"
DMG_ROM = SCRIPT_DIR / ("Super Mario Land 2 - 6 Golden Coins "
                        "(USA, Europe) (Rev 2).gb")


def pixel_diff_pct(a, b):
    ia = Image.open(a).convert("RGB")
    ib = Image.open(b).convert("RGB")
    if ia.size != ib.size:
        raise ValueError(f"size mismatch: {ia.size} vs {ib.size}")
    d = sum(1 for pa, pb in zip(ia.getdata(), ib.getdata()) if pa != pb)
    return d / (ia.size[0] * ia.size[1]) * 100


def nonblack_px(path):
    img = Image.open(path).convert("RGB")
    return sum(1 for p in img.getdata() if any(c > 10 for c in p))


def compile_rom(rom, out):
    r = subprocess.run(
        [sys.executable, str(COMPILER), "-e", str(EMULATOR),
         "-o", str(out), str(rom)],
        capture_output=True, text=True)
    if r.returncode != 0:
        print(f"ERROR: compile failed for {rom.name}: {r.stderr[:300]}")
        sys.exit(2)


def roundtrip(label, rom, tmpdir):
    """Save at 2600, move, load at 4400.  Returns the three screenshot paths."""
    gba, sav = tmpdir / f"{label}.gba", tmpdir / f"{label}.sav"
    compile_rom(rom, gba)
    sp = str(tmpdir / f"{label}_save.bmp")
    mv = str(tmpdir / f"{label}_moved.bmp")
    ld = str(tmpdir / f"{label}_loaded.bmp")

    cmd = [str(RUNNER), str(gba), "8000", "/dev/null"]
    for spec in ["600:Start", "900:Start", "2600:R+Select",
                 "3000:Right", "3200:Right", "3400:Right",
                 "3600:Right", "3800:Right", "4000:Right",
                 "4400:R+Start"]:
        cmd += ["--input", spec]
    for spec in [f"2400:{sp}", f"4200:{mv}", f"6000:{ld}"]:
        cmd += ["--screenshot", spec]
    cmd += ["--savefile", str(sav)]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        print(f"ERROR: runner timed out for {label}")
        sys.exit(2)
    if r.returncode != 0:
        print(f"ERROR: runner exited {r.returncode} for {label}: "
              f"{r.stderr[:300]}")
        sys.exit(2)

    return sp, mv, ld


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"),
                       (SGB_ROM, SGB_ROM.name), (DMG_ROM, DMG_ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    bad = []
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)

        # A DMG game must never get an SGB section, so its savestates have to
        # behave exactly as before.  Its screen does respond to input, so this
        # half is a real round-trip assertion: the restored frame has to match
        # the save point more closely than the moved-on point.
        sp, mv, ld = roundtrip("dmg", DMG_ROM, td)
        d_save, d_moved = pixel_diff_pct(sp, ld), pixel_diff_pct(mv, ld)
        print(f"  DMG (SML2)  round-trip: save={d_save:.1f}% "
              f"moved={d_moved:.1f}%")
        if d_save >= d_moved:
            bad.append(
                f"the DMG round-trip failed (save={d_save:.1f}% "
                f"moved={d_moved:.1f}%) -- the restored screen matches where "
                f"the game moved on to, not where it was saved.  Adding the "
                f"SGB section must not touch states for non-SGB games")

        # The SGB game is run too, but nothing here is asserted about it, and
        # that is a measured conclusion rather than caution.
        #
        # Kirby renders a static SGB title screen for this whole window, so a
        # pixel comparison cannot see whether a load took effect.  Rebuilding
        # with LoadSgb forced to reject its own section and re-running gave a
        # byte-identical result: 37196 non-black pixels either way, and a GB
        # WRAM dump identical between a run that loads and one that does not.
        # A "the screen is not blank" or "WRAM changed" assertion would
        # therefore have passed against a deliberately broken build -- it
        # would have been a vacuous assertion dressed up as coverage, which is
        # what test_menu_selfcheck exists to keep out of this suite.
        #
        # Verifying the section's contents needs a game whose behaviour
        # visibly depends on restored SGB state.  Until one is in the bundle,
        # the executable guard on this code is the field-offset check in
        # scripts/validate_elf.sh, and the numbers below are for the record.
        sp, mv, ld = roundtrip("sgb", SGB_ROM, td)
        print(f"  [diagnostic, not asserted] SGB (Kirby) after load: "
              f"{nonblack_px(ld)} non-black px, "
              f"{pixel_diff_pct(sp, ld):.1f}% from the pre-save frame")

    if bad:
        print()
        for b in bad:
            print("FAIL: " + b)
        sys.exit(1)

    print()
    print("PASS: adding the SGB section leaves non-SGB savestates untouched")


if __name__ == "__main__":
    main()
