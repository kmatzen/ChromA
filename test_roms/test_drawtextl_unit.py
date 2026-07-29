#!/usr/bin/env python3
"""Host-side unit tests for drawtextl()'s TEXTMEM branch (src/pocketnes_text.c).

Like the RLE and RTC unit suites, this needs no GBA toolchain, no mGBA build and
no ROM: it compiles src/pocketnes_text.c with the host C compiler and drives
drawtextl() directly against a stub TEXTMEM.

The bug it guards (issue #57 item 5) cannot be seen in a single screenshot --
it needs a long menu line, then a short one, then a scroll, and it corrupts an
off-screen shadow buffer that no test ROM can read back.  Here it is a memcmp.

Usage:
    python3 test_roms/test_drawtextl_unit.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
UNIT_DIR = SCRIPT_DIR / "unit"
SRC_C = UNIT_DIR / "test_drawtextl.c"
TEXT_C = PROJECT_DIR / "src" / "pocketnes_text.c"
SRC_INC = PROJECT_DIR / "src"

# The section attributes are meaningful only to the GBA toolchain; mach-o and
# ELF hosts reject ".sbss"/".ewram", so define them away for the host build.
HOST_DEFINES = ["-DEWRAM_BSS=", "-DEWRAM_DATA="]


def main():
    for path in (SRC_C, TEXT_C):
        if not path.exists():
            print(f"ERROR: {path} not found")
            sys.exit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        binary = Path(tmpdir) / "test_drawtextl"

        compile_result = subprocess.run(
            ["cc", "-O2", "-Wall", f"-I{SRC_INC}", *HOST_DEFINES,
             str(SRC_C), str(TEXT_C), "-o", str(binary)],
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
