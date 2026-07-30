#!/usr/bin/env python3
"""Host-side unit tests for the savestate record-chain walkers (src/sram.c).

Like the RLE, RTC and drawtextl unit suites, this needs no GBA toolchain, no
mGBA build and no ROM: it compiles src/sram.c with the host C compiler and
drives FindStateByIndex(), findstate() and drawstates() directly against a
synthetic heap.

Guards two bugs from issue #57:

  item 2  FindStateByIndex() compared a u16 record type against the delete
          menu's type = -1, which can never match, so the delete menu erased
          nothing.
  item 4  The walkers trusted sh->size with no bound against save_start, so a
          corrupt chain -- this heap lives in battery-backed cart SRAM shared
          with other Goomba-family forks -- walked off the end of the buffer.

Neither is observable on screen, which is why they are checked here rather
than through the emulator: the first is a missing effect and the second is an
out-of-bounds read that a GBA maps to more RAM.

Usage:
    python3 test_roms/test_sram_chain_unit.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
UNIT_DIR = SCRIPT_DIR / "unit"
SRC_C = UNIT_DIR / "test_sram_chain.c"
SRAM_C = PROJECT_DIR / "src" / "sram.c"
SRC_INC = PROJECT_DIR / "src"

# The section attributes are meaningful only to the GBA toolchain; mach-o and
# ELF hosts reject ".sbss"/".ewram", so define them away for the host build.
HOST_DEFINES = ["-DEWRAM_BSS=", "-DEWRAM_DATA=", "-DIWRAM_CODE="]

# sram.c casts pointers through u32 in using_flashcart(); that is correct on a
# 32-bit target and merely noisy on a 64-bit host.
HOST_WARN_OFF = ["-Wno-pointer-to-int-cast", "-Wno-int-to-pointer-cast"]


def main():
    for path in (SRC_C, SRAM_C):
        if not path.exists():
            print(f"ERROR: {path} not found")
            sys.exit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        binary = Path(tmpdir) / "test_sram_chain"

        compile_result = subprocess.run(
            ["cc", "-O1", "-Wall", f"-I{SRC_INC}", *HOST_DEFINES, *HOST_WARN_OFF,
             str(SRC_C), str(SRAM_C), "-o", str(binary)],
            capture_output=True, text=True
        )
        if compile_result.returncode != 0:
            print("FAIL: compile error")
            print(compile_result.stderr)
            sys.exit(1)

        run_result = subprocess.run(
            [str(binary)], capture_output=True, text=True, timeout=60
        )
        print(run_result.stdout, end="")
        if run_result.stderr:
            print(run_result.stderr, end="", file=sys.stderr)

        sys.exit(run_result.returncode)


if __name__ == "__main__":
    main()
