#!/usr/bin/env python3
"""Host-side unit tests for the software MBC3 RTC (src/rtc.c).

Like test_rle_unit.py, this needs no GBA toolchain, no mGBA build and no ROM:
the clock is a pure function of the frame count, so it compiles src/rtc.c with
the host C compiler and checks the conversion directly.

That is the only practical way to pin the tick rate.  The old code divided the
frame count by a flat 60; a GB frame is 70224 dots of a 4194304Hz clock, i.e.
59.7275Hz, so the clock lost about 0.45% -- roughly 6.5 minutes per emulated
day.  Demonstrating 0.45% through the emulator at one-second resolution needs
something like five minutes of emulated time per run; here it is arithmetic.

Usage:
    python3 test_roms/test_rtc_unit.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
UNIT_DIR = SCRIPT_DIR / "unit"
SRC_C = UNIT_DIR / "test_rtc.c"
RTC_C = PROJECT_DIR / "src" / "rtc.c"
SRC_INC = PROJECT_DIR / "src"


def main():
    for path in (SRC_C, RTC_C):
        if not path.exists():
            print(f"ERROR: {path} not found")
            sys.exit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        binary = Path(tmpdir) / "test_rtc"

        compile_result = subprocess.run(
            ["cc", "-O2", "-Wall", f"-I{SRC_INC}",
             str(SRC_C), str(RTC_C), "-o", str(binary)],
            capture_output=True, text=True
        )
        if compile_result.returncode != 0:
            print("FAIL: compile error")
            print(compile_result.stderr)
            sys.exit(1)

        run_result = subprocess.run(
            [str(binary)], capture_output=True, text=True, timeout=30
        )
        print(run_result.stdout, end="")
        if run_result.stderr:
            print(run_result.stderr, end="", file=sys.stderr)

        sys.exit(run_result.returncode)


if __name__ == "__main__":
    main()
