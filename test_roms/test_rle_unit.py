#!/usr/bin/env python3
"""Host-side unit tests for the savestate RLE codec (src/rle.c).

Unlike the rest of the suite, this needs no GBA toolchain, no mGBA build,
and no ROM — it compiles src/rle.c with the host C compiler and runs
assertions directly against rle_compress()/rle_decompress().

Usage:
    python3 test_roms/test_rle_unit.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
UNIT_DIR = SCRIPT_DIR / "unit"
SRC_C = UNIT_DIR / "test_rle.c"
RLE_C = PROJECT_DIR / "src" / "rle.c"
RLE_INC = PROJECT_DIR / "src"


def main():
    if not SRC_C.exists():
        print(f"ERROR: {SRC_C} not found")
        sys.exit(1)
    if not RLE_C.exists():
        print(f"ERROR: {RLE_C} not found")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        binary = Path(tmpdir) / "test_rle"

        compile_result = subprocess.run(
            ["cc", "-O2", "-Wall", f"-I{RLE_INC}",
             str(SRC_C), str(RLE_C), "-o", str(binary)],
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
