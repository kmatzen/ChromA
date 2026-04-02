#!/usr/bin/env python3
"""Test Goomba menu features: save states, menu open/close, persistence.

Automated tests:
  - Quicksave/quickload round-trip (R+Select / R+Start)
  - Save state persistence across restarts
  - Menu open/close without game reset
  - SRAM write-through persistence (delegates to test_sram_writethrough.py)

Manual testing required (Goomba menu runs internal frame loop):
  - Menu save/load state via slot picker (L+R → Down → A)
  - Display settings, Other Settings, Speed Hacks submenus
  - Sleep, Restart, Exit menu items

Usage:
    python3 test_roms/test_menu.py
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
EMULATOR = PROJECT_DIR / "jagoombacolor.gba"
SML2_ROM = SCRIPT_DIR / "Super Mario Land 2 - 6 Golden Coins (USA, Europe) (Rev 2).gb"


def run(gba, frames, inputs, screenshots=None, savefile=None):
    cmd = [str(RUNNER), str(gba), str(frames), "/dev/null"]
    for inp in inputs:
        cmd.extend(["--input", inp])
    for ss in (screenshots or []):
        cmd.extend(["--screenshot", ss])
    if savefile:
        cmd.extend(["--savefile", str(savefile)])
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300).returncode == 0


def pixel_diff_pct(a, b):
    ia = Image.open(a).convert("RGB")
    ib = Image.open(b).convert("RGB")
    d = sum(1 for pa, pb in zip(ia.getdata(), ib.getdata()) if pa != pb)
    return d / (ia.size[0] * ia.size[1]) * 100


def compile_sml2(output):
    return subprocess.run(
        [sys.executable, str(COMPILER), "-e", str(EMULATOR),
         "-o", str(output), str(SML2_ROM)],
        capture_output=True, text=True
    ).returncode == 0


def test_quicksave_roundtrip(tmpdir):
    """Quicksave (R+Select) then quickload (R+Start) restores game state."""
    print("Test: Quicksave/quickload round-trip")
    gba = tmpdir / "sml2.gba"
    sav = tmpdir / "sml2.sav"
    if not compile_sml2(gba):
        return False

    sp = str(tmpdir / "sp.bmp")
    mv = str(tmpdir / "mv.bmp")
    ld = str(tmpdir / "ld.bmp")

    ok = run(gba, 8000,
             ["600:Start", "900:Start",
              "2600:R+Select",                    # quicksave
              "3000:Right", "3200:Right", "3400:Right",
              "3600:Right", "3800:Right", "4000:Right",
              "4400:R+Start"],                    # quickload
             screenshots=[f"2400:{sp}", f"4200:{mv}", f"6000:{ld}"],
             savefile=sav)
    if not ok:
        print("  FAIL: runner error")
        return False

    d_sp = pixel_diff_pct(sp, ld)
    d_mv = pixel_diff_pct(mv, ld)
    passed = d_sp < d_mv
    print(f"  Save point vs loaded: {d_sp:.1f}%")
    print(f"  Moved vs loaded: {d_mv:.1f}%")
    print(f"  {'PASS' if passed else 'FAIL'}")
    return passed


def test_quicksave_persistence(tmpdir):
    """Quicksave persists to .sav file and survives restart."""
    print("Test: Quicksave persistence")
    gba = tmpdir / "sml2.gba"
    sav = tmpdir / "sml2.sav"
    if not compile_sml2(gba):
        return False

    sp = str(tmpdir / "sp.bmp")

    # Run 1: play and quicksave
    run(gba, 4000,
        ["600:Start", "900:Start", "2600:R+Select"],
        screenshots=[f"2400:{sp}"],
        savefile=sav)

    # Run 2: fresh boot with .sav, quickload
    rl = str(tmpdir / "rl.bmp")
    run(gba, 4000,
        ["600:Start", "900:Start", "2000:R+Start"],
        screenshots=[f"3000:{rl}"],
        savefile=sav)

    d = pixel_diff_pct(sp, rl)
    passed = d < 15.0
    print(f"  Reload vs save point: {d:.1f}%")
    print(f"  {'PASS' if passed else 'FAIL'}")
    return passed


def test_menu_open_close(tmpdir):
    """L+R opens menu, B closes it, game resumes without reset."""
    print("Test: Menu open/close")
    gba = tmpdir / "sml2.gba"
    if not compile_sml2(gba):
        return False

    before = str(tmpdir / "before.bmp")
    menu = str(tmpdir / "menu.bmp")
    after = str(tmpdir / "after.bmp")

    run(gba, 3600,
        ["600:Start", "900:Start", "2000:L+R", "2400:B"],
        screenshots=[f"1800:{before}", f"2200:{menu}", f"3000:{after}"])

    menu_diff = pixel_diff_pct(before, menu)
    resume_diff = pixel_diff_pct(before, after)

    menu_ok = menu_diff > 5
    resume_ok = resume_diff < 30
    print(f"  Menu overlay: {menu_diff:.1f}% ({'visible' if menu_ok else 'NOT visible'})")
    print(f"  Resume: {resume_diff:.1f}% ({'OK' if resume_ok else 'RESET'})")
    print(f"  {'PASS' if menu_ok and resume_ok else 'FAIL'}")
    return menu_ok and resume_ok


def test_sram_persistence(tmpdir):
    """SRAM write-through persists (delegates to test_sram_writethrough.py)."""
    print("Test: SRAM persistence")
    result = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "test_sram_writethrough.py")],
        capture_output=True, text=True, timeout=600)
    passed = result.returncode == 0
    for line in result.stdout.strip().split("\n")[-3:]:
        print(f"  {line}")
    return passed


def main():
    if not RUNNER.exists():
        print(f"ERROR: mgba_runner not found")
        sys.exit(1)
    if not EMULATOR.exists():
        print(f"ERROR: jagoombacolor.gba not found")
        sys.exit(1)
    if not SML2_ROM.exists():
        print(f"ERROR: SML2 ROM not found")
        sys.exit(1)

    results = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        results.append(("Quicksave/load round-trip", test_quicksave_roundtrip(tmpdir)))
        results.append(("Quicksave persistence", test_quicksave_persistence(tmpdir)))
        results.append(("Menu open/close", test_menu_open_close(tmpdir)))
    results.append(("SRAM persistence", test_sram_persistence(None)))

    print(f"\n{'='*60}")
    passed = sum(1 for _, r in results if r)
    failed = sum(1 for _, r in results if not r)
    for name, r in results:
        print(f"  {'PASS' if r else 'FAIL'}: {name}")
    print(f"\nMenu tests: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
