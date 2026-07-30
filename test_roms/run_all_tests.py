#!/usr/bin/env python3
"""Run all jagoombacolor test suites and report results.

Usage:
    python3 test_roms/run_all_tests.py                  # Run everything
    python3 test_roms/run_all_tests.py --quick          # Skip slow SRAM tests
    python3 test_roms/run_all_tests.py --diff-dir DIR   # Save visual diffs

Exit code 0 = all pass, 1 = failures.

This is the single entry point for the full suite: it is the only thing CI
needs to invoke. Running run_tests.py separately beforehand just executes the
26-ROM visual suite twice -- doubling both runtime and the exposure to any
flaky baseline -- which is why --diff-dir is forwarded from here instead.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent

# Per-suite wall-clock caps, in seconds.
#
# These were previously one shared default of 600 with the *slow* SRAM suite
# explicitly lowered to 300 -- backwards, and the menu suite (24 tests, most of
# them two or three full emulator runs of up to 300s each) shared that same
# 600s cap and could be killed on a slow runner while making normal progress.
# A timeout is a backstop against a hang, not a performance budget, so each
# suite gets a cap comfortably above its realistic worst case.
TIMEOUT_UNIT = 120        # host-native, no emulator
TIMEOUT_VISUAL = 2400     # 26 ROMs, one emulator run each
TIMEOUT_MENU = 3600       # 24 tests, 2-3 emulator runs each
TIMEOUT_SRAM = 1200       # 2 tests, 3 long Crystal runs
TIMEOUT_SHORT_ROM = 300   # single custom ROM


def run_suite(name, cmd, timeout):
    """Run a test suite and return (passed, output)."""
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=PROJECT_DIR
        )
        output = result.stdout + result.stderr
        print(output)
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT after {timeout}s")
        return False, "TIMEOUT"


def main():
    parser = argparse.ArgumentParser(description="Run all ChromA test suites")
    parser.add_argument("--quick", action="store_true",
                        help="Skip the slow SRAM write-through suite")
    parser.add_argument("--diff-dir", default=None,
                        help="Directory for visual-regression diff images "
                             "(forwarded to run_tests.py)")
    parser.add_argument("--allow-missing-roms", action="store_true",
                        help="Forwarded to the SRAM suite: tolerate absent "
                             "game ROMs instead of failing")
    args = parser.parse_args()

    start = time.time()
    results = []

    def suite(label, script, timeout, extra=()):
        ok, _ = run_suite(label, [sys.executable, str(SCRIPT_DIR / script), *extra],
                          timeout)
        results.append((label, ok))

    # 0. RLE codec unit tests (host-native, no ROM/toolchain needed)
    suite("RLE Codec Unit Tests", "test_rle_unit.py", TIMEOUT_UNIT)

    # 0a. Menu text and dirty-tile bitmap unit tests (issue #57 items 5 and 7).
    # Both bugs are invisible to the screenshot suites -- one corrupts an
    # off-screen shadow buffer, the other writes out of bounds with a zero mask
    # -- so they are checked directly against the C on the host.
    suite("Menu Text Row Unit Tests", "test_drawtextl_unit.py", TIMEOUT_UNIT)
    suite("Dirty Tile Bitmap Unit Tests", "test_dirtybits_unit.py", TIMEOUT_UNIT)

    # 0b. mgba_runner argument validation (issue #58) -- no ROM or toolchain
    # needed, and it guards the harness's own ability to report a problem, so
    # run it before anything that depends on the runner behaving.
    suite("Runner Argument Validation", "test_runner_args.py", TIMEOUT_UNIT)

    # 0c. Menu/SRAM harness self-checks (issue #59) -- host-native, and they
    # guard the assertions used by the two suites below.
    suite("Menu/SRAM Harness Self-Checks", "test_menu_selfcheck.py", TIMEOUT_UNIT)

    # 1. Visual regression tests (26 ROMs)
    visual_args = ["--diff-dir", args.diff_dir] if args.diff_dir else []
    suite("Visual Regression Tests (26 ROMs)", "run_tests.py", TIMEOUT_VISUAL,
          visual_args)

    # 2. Menu + savestate tests
    suite("Menu & Savestate Tests", "test_menu.py", TIMEOUT_MENU)

    # 3. RST timing test
    suite("RST Timing Test", "test_rst_timing.py", TIMEOUT_SHORT_ROM)

    # 4. MBC2 SRAM echo/write-through regression (issue #47) — fast, custom ROM
    suite("MBC2 SRAM Write-Through Test", "test_mbc2_sram.py", TIMEOUT_SHORT_ROM)

    # 4a. STAT/LY register accuracy (issue #52). Runs the probe twice per model
    # (once in ChromA, once in mGBA's own GB core as the reference), so it needs
    # room for four short emulator runs rather than one.
    suite("STAT/LY Register Accuracy Test", "test_stat_ly.py",
          TIMEOUT_SHORT_ROM * 4)

    # 5. SRAM write-through tests (slow — multiple full Crystal playthroughs).
    # test_menu.py used to invoke this script as well, so it ran twice.
    if not args.quick:
        sram_args = ["--allow-missing-roms"] if args.allow_missing_roms else []
        suite("SRAM Write-Through Tests", "test_sram_writethrough.py",
              TIMEOUT_SRAM, sram_args)
    else:
        print("\n  [SKIPPED] SRAM write-through (--quick)")

    # Summary
    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"  ALL TESTS SUMMARY ({elapsed:.0f}s)")
    print(f"{'='*60}")
    total_pass = 0
    total_fail = 0
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
        if ok:
            total_pass += 1
        else:
            total_fail += 1
    print(f"\n  {total_pass} suites passed, {total_fail} failed")

    if not results:
        print("  ERROR: no suites ran")
        return 1
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
