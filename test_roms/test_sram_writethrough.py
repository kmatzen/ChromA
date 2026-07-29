#!/usr/bin/env python3
"""Test SRAM write-through and save reload for chroma.

Tests:
  1. Write-through: sram_W2 writes to both emulated XGB_SRAM and GBA cart SRAM
     (8KB games only — 32KB+ overlaps the config area so write-through is
     disabled for those)
  2. Save reload:   a save persisted via Goomba's compressed save system can
                     be reloaded on a fresh boot with the same .sav file

Usage:
    python3 test_roms/test_sram_writethrough.py
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from elf_symbols import SymbolError, load_symbols

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
RUNNER = SCRIPT_DIR / "mgba_runner"
COMPILER = SCRIPT_DIR / "goomba_compile.py"
EMULATOR = PROJECT_DIR / "chroma.gba"

# XGB_SRAM is resolved from build/chroma.elf.map, not hardcoded.  The literal
# that used to sit here had no fallback path and no way to notice it had gone
# stale: after any layout change these tests would dump 32KB of unrelated
# EWRAM and compare *that* against cart SRAM.
try:
    XGB_SRAM_ADDR = load_symbols(['XGB_SRAM'])['XGB_SRAM']
except SymbolError as exc:
    print(f"ERROR: {exc}")
    sys.exit(1)

GBA_SRAM_BASE = 0x0E000000
GBA_CART_SIZE = 0x10000  # 64K flash cart

# Test outcomes.  SKIP used to be spelled "return True", which reported a test
# that verified nothing as a pass; it is now a distinct state that main()
# treats as a failure unless explicitly allowed.
PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


def compile_rom(rom_path, output_path):
    result = subprocess.run(
        [sys.executable, str(COMPILER), "-e", str(EMULATOR),
         "-o", str(output_path), str(rom_path)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  ERROR compiling: {result.stderr}")
        return False
    return True


def run_mgba(gba_path, frames, inputs, memdumps=None, savefile=None):
    """Run a ROM and return requested memory dumps as a dict of bytes."""
    cmd = [str(RUNNER), str(gba_path), str(frames), "/dev/null"]
    for inp in inputs:
        cmd.extend(["--input", inp])
    if savefile:
        cmd.extend(["--savefile", str(savefile)])
    dump_paths = {}
    for name, (addr, length, path) in (memdumps or {}).items():
        cmd.extend(["--memdump", f"{addr}:{length}:{path}"])
        dump_paths[name] = path

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        print(f"  ERROR running: {result.stderr[:500]}")
        return None

    dumps = {}
    for name, path in dump_paths.items():
        dumps[name] = Path(path).read_bytes()
    return dumps


# --- SML2: 8KB SRAM, 1 bank, MBC1+RAM+BATTERY ---
SML2_ROM_NAME = "Super Mario Land 2 - 6 Golden Coins (USA, Europe) (Rev 2).gb"
SML2_SRAM_SIZE = 8192

# --- Crystal: 32KB SRAM, 4 banks, MBC3+TIMER+RAM+BATTERY ---
CRYSTAL_ROM_NAME = "Pokemon - Crystal Version (USA, Europe) (Rev 1).gbc"
CRYSTAL_SRAM_SIZE = 32768
CRYSTAL_NUM_BANKS = 4


def crystal_advance_inputs():
    """A-spam to advance through Goomba menu, Game Freak logo, title, Oak
    intro, character naming, and into gameplay."""
    return [f"{f}:A" for f in range(300, 5500, 45)]


def test_writethrough(tmpdir):
    """Verify sram_W2 writes game save data to GBA cart SRAM.

    Uses Crystal (32KB SRAM, 4 banks) to test the hardest case — save_start
    must be moved down to 0x8000 to avoid overlapping the config area.
    """
    print(f"\n{'='*60}")
    print("Test: SRAM write-through (Crystal, 32KB)")

    crystal = SCRIPT_DIR / CRYSTAL_ROM_NAME
    if not crystal.exists():
        print(f"  SKIP: ROM not found ({CRYSTAL_ROM_NAME})")
        return SKIP

    gba_path = tmpdir / "crystal_wt.gba"
    if not compile_rom(crystal, gba_path):
        return FAIL

    inputs = crystal_advance_inputs() + [
        "7000:Start", "7200:Down", "7400:Down",  # navigate to SAVE
        "7600:A", "7900:A",                       # save the game
        "8400:A", "8600:B", "8800:B",             # dismiss + close menu
    ]

    sram_offset = GBA_CART_SIZE - CRYSTAL_SRAM_SIZE  # 0x8000
    dumps = run_mgba(
        gba_path, 9600, inputs,
        memdumps={
            "xgb": (XGB_SRAM_ADDR, CRYSTAL_SRAM_SIZE,
                    str(tmpdir / "wt_xgb.bin")),
            "gba": (GBA_SRAM_BASE + sram_offset, CRYSTAL_SRAM_SIZE,
                    str(tmpdir / "wt_gba.bin")),
        },
    )
    if dumps is None:
        return FAIL

    xgb, gba = dumps["xgb"], dumps["gba"]
    xgb_nz = sum(1 for b in xgb if b != 0)
    gba_nz = sum(1 for b in gba if b != 0)
    print(f"  XGB_SRAM: {xgb_nz} non-zero bytes")
    print(f"  GBA SRAM: {gba_nz} non-zero bytes")

    if xgb_nz == 0:
        # This is the whole premise of the test, not a reason to skip it.
        # The intro is driven by a fixed-frame A-spam script, so any timing
        # drift stops the run reaching the in-game save -- and reporting that
        # as a pass is exactly how a real write-through regression would be
        # converted into a green build.
        print(f"  FAIL: game never wrote to SRAM -- the scripted intro did "
              f"not reach an in-game save")
        return FAIL

    total_mm = 0
    for bank in range(CRYSTAL_NUM_BANKS):
        s, e = bank * 0x2000, (bank + 1) * 0x2000
        bnz = sum(1 for b in xgb[s:e] if b != 0)
        mm = sum(1 for a, b in zip(xgb[s:e], gba[s:e]) if a != b)
        total_mm += mm
        if bnz > 0 or mm > 0:
            print(f"  Bank {bank}: {bnz} non-zero, {mm} mismatches")

    match_pct = (1 - total_mm / CRYSTAL_SRAM_SIZE) * 100
    # Allow small mismatch from stack pushes that bypass sram_W2.
    result = PASS if match_pct >= 95.0 else FAIL
    print(f"  Match: {match_pct:.1f}% ({total_mm} mismatches)")
    print(f"  Result: {result}")
    return result


def test_save_reload(tmpdir):
    """Verify that a game save persists across sessions via write-through.

    Run 1: Play Crystal, do an in-game save.  Write-through puts the data
           directly in GBA cart SRAM, which mGBA persists to the .sav file.
    Run 2: Boot with the .sav from run 1, verify XGB_SRAM is restored
           (get_saved_sram copies from the write-through region).
    """
    print(f"\n{'='*60}")
    print("Test: Save reload (Crystal, 32KB)")

    crystal = SCRIPT_DIR / CRYSTAL_ROM_NAME
    if not crystal.exists():
        print(f"  SKIP: ROM not found ({CRYSTAL_ROM_NAME})")
        return SKIP

    gba_path = tmpdir / "crystal.gba"
    if not compile_rom(crystal, gba_path):
        return FAIL

    savefile = tmpdir / "crystal.sav"

    # --- Run 1: play and in-game save (write-through persists to .sav) ---
    run1_inputs = crystal_advance_inputs() + [
        "7000:Start", "7200:Down", "7400:Down",
        "7600:A", "7900:A",                       # save
        "8400:A", "8600:B", "8800:B",             # dismiss
    ]

    dumps1 = run_mgba(
        gba_path, 9600, run1_inputs,
        memdumps={
            "xgb": (XGB_SRAM_ADDR, CRYSTAL_SRAM_SIZE,
                    str(tmpdir / "run1_xgb.bin")),
        },
        savefile=savefile,
    )
    if dumps1 is None:
        return FAIL

    first_xgb = dumps1["xgb"]
    first_nz = sum(1 for b in first_xgb if b != 0)
    print(f"  Run 1 XGB_SRAM: {first_nz} non-zero bytes")

    if first_nz == 0:
        # See test_writethrough: not reaching the save is a harness failure,
        # not a pass.
        print(f"  FAIL: game never wrote to SRAM -- the scripted intro did "
              f"not reach an in-game save")
        return FAIL

    if not savefile.exists():
        print(f"  FAIL: .sav file not created")
        return FAIL
    print(f"  Save file: {savefile.stat().st_size} bytes")

    # --- Run 2: reload and verify ---
    run2_inputs = [f"{f}:A" for f in range(300, 3000, 45)]

    dumps2 = run_mgba(
        gba_path, 3600, run2_inputs,
        memdumps={
            "xgb": (XGB_SRAM_ADDR, CRYSTAL_SRAM_SIZE,
                    str(tmpdir / "run2_xgb.bin")),
        },
        savefile=savefile,
    )
    if dumps2 is None:
        return FAIL

    reload_xgb = dumps2["xgb"]
    reload_nz = sum(1 for b in reload_xgb if b != 0)
    print(f"  Run 2 XGB_SRAM: {reload_nz} non-zero bytes")

    # Compare non-empty banks.
    total_mm = 0
    total_compared = 0
    for bank in range(CRYSTAL_NUM_BANKS):
        s, e = bank * 0x2000, (bank + 1) * 0x2000
        orig_nz = sum(1 for b in first_xgb[s:e] if b != 0)
        if orig_nz == 0:
            continue
        mm = sum(1 for a, b in zip(first_xgb[s:e], reload_xgb[s:e]) if a != b)
        total_mm += mm
        total_compared += 0x2000
        if mm > 0:
            print(f"  Bank {bank}: {mm} mismatches (of {orig_nz} non-zero)")

    if total_compared == 0:
        # first_nz > 0 was checked above, so every non-zero byte would have to
        # have vanished between the two loops for this to happen. Treating it
        # as a pass hid whatever caused it.
        print(f"  FAIL: no populated banks to compare, though run 1 wrote "
              f"{first_nz} non-zero bytes")
        return FAIL

    match_pct = (1 - total_mm / total_compared) * 100
    result = PASS if match_pct >= 90.0 else FAIL
    print(f"  Match: {match_pct:.1f}% ({total_mm} mismatches in {total_compared} bytes)")
    print(f"  Result: {result}")
    return result


TESTS = [
    ("Write-through", test_writethrough),
    ("Save reload", test_save_reload),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-missing-roms", action="store_true",
        help="Report SKIP instead of failing when a game ROM is absent "
             "(for local runs without the private ROM bundle; CI always has "
             "them, so a missing ROM there means the download step broke)")
    args = parser.parse_args()

    if not RUNNER.exists():
        print(f"ERROR: mgba_runner not found at {RUNNER}")
        sys.exit(1)
    if not EMULATOR.exists():
        print(f"ERROR: chroma.gba not found at {EMULATOR}")
        sys.exit(1)

    results = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        for name, fn in TESTS:
            # Skipped tests used to be dropped from `results` entirely, so a
            # run where both ROMs were missing printed "0 passed, 0 failed"
            # and exited 0. Record every test, always.
            try:
                results.append((name, fn(tmpdir)))
            except (OSError, ValueError) as exc:
                print(f"  ERROR: {type(exc).__name__}: {exc}")
                results.append((name, FAIL))

    print(f"\n{'='*60}")
    passed = sum(1 for _, r in results if r == PASS)
    failed = sum(1 for _, r in results if r == FAIL)
    skipped = sum(1 for _, r in results if r == SKIP)
    for name, r in results:
        print(f"  {r}: {name}")
    print(f"\nSRAM tests: {passed} passed, {failed} failed, {skipped} skipped")

    if not results:
        print("ERROR: no tests ran")
        sys.exit(1)
    if skipped and not args.allow_missing_roms:
        print("ERROR: tests were skipped for missing ROMs. A skip verifies "
              "nothing, so it is not a pass -- pass --allow-missing-roms if "
              "that is expected locally.")
        sys.exit(1)
    if skipped == len(results):
        # Even when skips are allowed, a run that verified nothing at all is
        # not a successful run.
        print("ERROR: every test was skipped; nothing was verified")
        sys.exit(1)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
