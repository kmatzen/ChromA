#!/usr/bin/env python3
"""Run all jagoombacolor test suites and report results.

Usage:
    python3 test_roms/run_all_tests.py          # Run everything
    python3 test_roms/run_all_tests.py --quick   # Skip slow SRAM tests

Exit code 0 = all pass, 1 = failures.
"""

import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent

def run_suite(name, cmd, timeout=600):
    """Run a test suite and return (passed, failed, output)."""
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
    quick = "--quick" in sys.argv
    start = time.time()
    results = []

    # 1. Visual regression tests (26 ROMs)
    ok, out = run_suite(
        "Visual Regression Tests (26 ROMs)",
        [sys.executable, str(SCRIPT_DIR / "run_tests.py")]
    )
    results.append(("Visual regression", ok))

    # 2. Menu + savestate tests (26 tests)
    ok, out = run_suite(
        "Menu & Savestate Tests (26 tests)",
        [sys.executable, str(SCRIPT_DIR / "test_menu.py")]
    )
    results.append(("Menu & savestates", ok))

    # 3. RST timing test
    ok, out = run_suite(
        "RST Timing Test",
        [sys.executable, str(SCRIPT_DIR / "test_rst_timing.py")]
    )
    results.append(("RST timing", ok))

    # 4. SRAM write-through tests (slow — involves multiple ROM runs)
    if not quick:
        ok, out = run_suite(
            "SRAM Write-Through Tests",
            [sys.executable, str(SCRIPT_DIR / "test_sram_writethrough.py")],
            timeout=300
        )
        results.append(("SRAM write-through", ok))
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

    return 0 if total_fail == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
