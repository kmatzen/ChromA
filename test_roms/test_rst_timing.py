#!/usr/bin/env python3
"""Test RST instruction timing consistency.

Runs rst_timing_test.gb through jagoombacolor and reads results from
SRAM to verify all RST variants have identical timing (16 T-cycles)
and CALL has 24 T-cycles.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
RUNNER = SCRIPT_DIR / "mgba_runner"
COMPILER = SCRIPT_DIR / "goomba_compile.py"
EMULATOR = PROJECT_DIR / "jagoombacolor.gba"
ROM = SCRIPT_DIR / "rst_timing_test.gb"


def main():
    if not RUNNER.exists():
        print(f"ERROR: mgba_runner not found at {RUNNER}")
        sys.exit(1)
    if not EMULATOR.exists():
        print(f"ERROR: jagoombacolor.gba not found")
        sys.exit(1)
    if not ROM.exists():
        print(f"ERROR: rst_timing_test.gb not found — assemble it first")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        gba = tmpdir / "rst_test.gba"
        sav = tmpdir / "rst_test.sav"

        # Compile
        r = subprocess.run(
            [sys.executable, str(COMPILER), "-e", str(EMULATOR),
             "-o", str(gba), str(ROM)],
            capture_output=True, text=True
        )
        if r.returncode != 0:
            print(f"FAIL: compile error: {r.stderr}")
            sys.exit(1)

        # Run
        r = subprocess.run(
            [str(RUNNER), str(gba), "600", "/dev/null",
             "--savefile", str(sav)],
            capture_output=True, text=True, timeout=60
        )
        if r.returncode != 0:
            print(f"FAIL: runner error: {r.stderr}")
            sys.exit(1)

        # Read results from write-through region
        # Game has 8KB SRAM, GBA SRAM is 32KB, write-through at offset 0x6000
        data = sav.read_bytes()
        wt_offset = 0x6000
        results = data[wt_offset:wt_offset + 17]

        names = [
            "RST 00h", "RST 08h", "RST 10h", "RST 18h",
            "RST 20h", "RST 28h", "RST 30h", "RST 38h",
            "CALL"
        ]

        sentinel = results[16]
        if sentinel != 0xFF:
            print(f"FAIL: Test did not complete (sentinel=0x{sentinel:02X})")
            sys.exit(1)

        print("RST Timing Test Results:")
        all_pass = True
        for i, name in enumerate(names):
            delta = results[i]
            expected = 1  # DIV delta should be 1 (exactly 256 cycles)
            status = "PASS" if delta == expected else "FAIL"
            if delta != expected:
                all_pass = False
            print(f"  {name}: DIV delta={delta} (expect {expected}) {status}")

        mismatches = results[9]
        rst00_rst38_delta = results[10]
        print(f"  RST mismatches: {mismatches}")
        print(f"  RST00-RST38 delta: {rst00_rst38_delta}")

        if mismatches != 0:
            all_pass = False
        if rst00_rst38_delta != 0:
            all_pass = False

        print()
        if all_pass:
            print("PASS: All RST variants have identical timing")
        else:
            print("FAIL: RST timing mismatch detected")
        sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
