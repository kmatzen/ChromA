#!/usr/bin/env python3
"""Host-side unit tests for the VRAM dirty-tile bitmap (SetBits in src/dma.c).

No GBA toolchain, no mGBA build and no ROM: the test translation unit #includes
src/dma.c (SetBits and SetDirtyTiles are static) and stubs the handful of symbols
dma.c expects from the assembly half of the build.

Guards issue #57 item 7: SetBits did a read-modify-write one word past the end of
the 24-byte per-bank dirty-tile region whenever the bit range ended on a word
boundary.  For VRAM bank 1 that word is ewram_canary_2.  The mask was 0, so the
canary's value survived -- which is why the test uses an mmap guard page in a
forked child to catch the access rather than the result.

Usage:
    python3 test_roms/test_dirtybits_unit.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
UNIT_DIR = SCRIPT_DIR / "unit"
SRC_C = UNIT_DIR / "test_dirtybits.c"
DMA_C = PROJECT_DIR / "src" / "dma.c"
SRC_INC = PROJECT_DIR / "src"

# GBA-only placement attributes, defined away for the host build.  long_call is
# an ARM attribute clang warns about even once VRAM_CODE is empty, hence the
# -Wno-unknown-attributes.
HOST_DEFINES = ["-DEWRAM_BSS=", "-DEWRAM_DATA=", "-DVRAM_CODE=", "-DIWRAM_CODE="]


def main():
    for path in (SRC_C, DMA_C):
        if not path.exists():
            print(f"ERROR: {path} not found")
            sys.exit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        binary = Path(tmpdir) / "test_dirtybits"

        compile_result = subprocess.run(
            ["cc", "-O2", "-Wall", "-Wno-unknown-attributes",
             f"-I{SRC_INC}", *HOST_DEFINES,
             str(SRC_C), "-o", str(binary)],
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
