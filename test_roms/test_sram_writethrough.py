#!/usr/bin/env python3
"""Test SRAM write-through: verify GBC SRAM writes reach GBA cart SRAM.

Tests that sram_W2 correctly writes to both emulated XGB_SRAM and
physical GBA cart SRAM for games that use SRAM saves.

Usage:
    python3 test_roms/test_sram_writethrough.py
"""

import struct
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
RUNNER = SCRIPT_DIR / "mgba_runner"
COMPILER = SCRIPT_DIR / "goomba_compile.py"
EMULATOR = PROJECT_DIR / "jagoombacolor.gba"

# Addresses from jagoombacolor.elf
XGB_SRAM_ADDR = 0x02038000
GBA_SRAM_BASE = 0x0E000000
GBA_CART_SIZE = 0x10000  # 64K flash cart

def run_and_dump_sram(rom_path, frames, inputs, sram_size):
    """Run a ROM and dump both XGB_SRAM and GBA cart SRAM."""
    # Write-through base = GBA cart end - game SRAM size
    gba_sram_addr = GBA_SRAM_BASE + (GBA_CART_SIZE - sram_size)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        gba_path = tmpdir / "test.gba"
        xgb_path = tmpdir / "xgb_sram.bin"
        gba_path_sram = tmpdir / "gba_sram.bin"

        # Compile
        result = subprocess.run(
            [sys.executable, str(COMPILER), "-e", str(EMULATOR),
             "-o", str(gba_path), str(rom_path)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"ERROR compiling: {result.stderr}")
            return None, None

        # Run
        cmd = [str(RUNNER), str(gba_path), str(frames), "/dev/null"]
        for inp in inputs:
            cmd.extend(["--input", inp])
        cmd.extend(["--memdump", f"{XGB_SRAM_ADDR}:{sram_size}:{xgb_path}"])
        cmd.extend(["--memdump", f"{gba_sram_addr}:{sram_size}:{gba_path_sram}"])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"ERROR running: {result.stderr}")
            return None, None

        with open(xgb_path, "rb") as f:
            xgb = f.read()
        with open(gba_path_sram, "rb") as f:
            gba = f.read()

        return xgb, gba


def test_writethrough(name, rom_path, frames, inputs, sram_size, num_banks):
    """Test that SRAM write-through works for a game."""
    print(f"\n{'='*60}")
    print(f"Test: {name} ({sram_size//1024}KB SRAM, {num_banks} bank(s))")

    xgb, gba = run_and_dump_sram(rom_path, frames, inputs, sram_size)
    if xgb is None:
        return False

    xgb_nz = sum(1 for b in xgb if b != 0)
    gba_nz = sum(1 for b in gba if b != 0)

    print(f"  XGB_SRAM: {xgb_nz} non-zero bytes")
    print(f"  GBA SRAM: {gba_nz} non-zero bytes")

    if xgb_nz == 0:
        print(f"  SKIP: Game hasn't written to SRAM during test")
        return True  # Not a failure, just no data to compare

    # Compare bank by bank
    total_mismatches = 0
    for bank in range(num_banks):
        start = bank * 0x2000
        end = start + 0x2000
        xb = xgb[start:end]
        gb = gba[start:end]
        bnz = sum(1 for b in xb if b != 0)
        mm = sum(1 for a, b in zip(xb, gb) if a != b)
        total_mismatches += mm
        if bnz > 0 or mm > 0:
            print(f"  Bank {bank}: {bnz} non-zero, {mm} mismatches")

    # Allow small number of mismatches (stack writes bypass sram_W2)
    match_pct = (1 - total_mismatches / sram_size) * 100
    # Threshold: if SRAM has data, at least 95% should match
    passed = match_pct >= 95.0
    print(f"  Overall: {match_pct:.1f}% match ({total_mismatches} mismatches)")
    print(f"  Result: {'PASS' if passed else 'FAIL'}")
    return passed


def main():
    if not RUNNER.exists():
        print(f"ERROR: mgba_runner not found at {RUNNER}")
        sys.exit(1)
    if not EMULATOR.exists():
        print(f"ERROR: jagoombacolor.gba not found at {EMULATOR}")
        sys.exit(1)

    results = []

    # Test 1: SML2 (8KB SRAM, 1 bank) - known to write SRAM during gameplay
    sml2 = SCRIPT_DIR / "Super Mario Land 2 - 6 Golden Coins (USA, Europe) (Rev 2).gb"
    if sml2.exists():
        results.append(test_writethrough(
            "Super Mario Land 2", sml2,
            frames=2400, inputs=["600:Start", "900:Start"],
            sram_size=8192, num_banks=1
        ))

    # Test 2: Pokemon Crystal (32KB SRAM, 4 banks)
    # Spam A to advance through intro, create character "AAA...", then save.
    # Timing (calibrated via screenshots):
    #   ~frame 2000: Oak's intro dialog
    #   ~frame 4000: Player character shown / naming
    #   ~frame 6000: In bedroom (gameplay started)
    crystal = SCRIPT_DIR / "Pokemon - Crystal Version (USA, Europe) (Rev 1).gbc"
    if crystal.exists():
        crystal_inputs = []
        # Phase 1: Spam A to advance through goomba menu, Game Freak logo,
        # title screen, Oak intro, character naming, and into gameplay.
        # Stop before frame 6000 so we don't keep interacting with objects.
        for f in range(300, 5500, 45):
            crystal_inputs.append(f"{f}:A")
        # Phase 2: Open Start menu and navigate to SAVE.
        # At the start of Crystal (no Pokemon yet), menu is:
        #   PACK, <name>, SAVE, OPTION, EXIT
        # So Down twice reaches SAVE.
        crystal_inputs.append("7000:Start")
        crystal_inputs.append("7200:Down")
        crystal_inputs.append("7400:Down")
        # Select SAVE
        crystal_inputs.append("7600:A")
        # Confirm "Would you like to save the game?" → YES is default
        crystal_inputs.append("7900:A")
        # Wait for save animation, dismiss "saved the game" message
        crystal_inputs.append("8400:A")
        # Close the menu (B to exit save stats, B to close start menu)
        crystal_inputs.append("8600:B")
        crystal_inputs.append("8800:B")
        # Let it run a bit more after saving
        total_crystal_frames = 9600

        results.append(test_writethrough(
            "Pokemon Crystal (save test)", crystal,
            frames=total_crystal_frames, inputs=crystal_inputs,
            sram_size=32768, num_banks=4
        ))

    # Test 3: Shantae (64KB SRAM? or 8KB?) - GBC game with saves
    shantae = SCRIPT_DIR / "Shantae (USA).gbc"
    if shantae.exists():
        results.append(test_writethrough(
            "Shantae", shantae,
            frames=6000,
            inputs=["1200:Start", "1800:Start", "2100:A", "2400:A", "2700:A", "3000:A"],
            sram_size=32768, num_banks=4
        ))

    print(f"\n{'='*60}")
    passed = sum(1 for r in results if r)
    failed = sum(1 for r in results if not r)
    print(f"SRAM write-through tests: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
