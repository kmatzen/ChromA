#!/usr/bin/env python3
"""Host-side unit tests for the ROM bank table (issue #57 item 6).

make_instant_pages() (src/cache.c) fills the 256-entry table the ARM banking
code indexes to find each 16KB GB ROM bank.  It filled all 256 entries as
rom_base + 16384*i unconditionally, so for any cart smaller than 4MB the
entries past the end of the ROM pointed outside it, while cart.s masked bank
numbers against the size in header byte 0x148 -- the two disagreed about how
big the cart was.

Like the other unit suites this needs no GBA toolchain, no mGBA build and no
ROM: it compiles src/cache.c with the host C compiler and inspects the table
directly.  Bank 0's VRAM shadow copy is stubbed out, since that address is
real on a GBA and a segfault here.

Usage:
    python3 test_roms/test_rom_banks_unit.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
UNIT_DIR = SCRIPT_DIR / "unit"
SRC_C = UNIT_DIR / "test_rom_banks.c"
CACHE_C = PROJECT_DIR / "src" / "cache.c"
SRC_INC = PROJECT_DIR / "src"

# The section attributes are meaningful only to the GBA toolchain; mach-o and
# ELF hosts reject ".sbss"/".ewram", so define them away for the host build.
HOST_DEFINES = ["-DEWRAM_BSS=", "-DEWRAM_DATA=", "-DIWRAM_CODE="]

# cache.c shadows bank 0 into VRAM, an address no host can map (64-bit macOS
# reserves the low 4GB as __PAGEZERO), so memcpy is renamed to a stub in the
# test file.  _FORTIFY_SOURCE has to go with it: its own memcpy macro is
# defined by <string.h> and would override the rename.
HOST_DEFINES += ["-D_FORTIFY_SOURCE=0", "-Dmemcpy=test_memcpy"]


def main():
    for path in (SRC_C, CACHE_C):
        if not path.exists():
            print(f"ERROR: {path} not found")
            sys.exit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        binary = Path(tmpdir) / "test_rom_banks"

        compile_result = subprocess.run(
            ["cc", "-O1", "-Wall", f"-I{SRC_INC}", *HOST_DEFINES,
             str(SRC_C), str(CACHE_C), "-o", str(binary)],
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
