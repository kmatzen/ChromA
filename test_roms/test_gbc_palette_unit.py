#!/usr/bin/env python3
"""Host-side unit tests for the CGB boot-palette licensee gate (issue #154).

GetGbcPaletteNumber() (src/gbcgamedetect.c) consulted the title-hash table for
every cart, but the CGB boot ROM only does so for Nintendo-licensed ones --
old licensee $014B == $01, or $014B == $33 with new licensee $0144-45 == "01".
The table is keyed on a one-byte title checksum, so third-party titles collide
into it; Mega Man - Dr. Wily's Revenge (old licensee $08, Capcom) was picking
up palette 88 that way.

Like the other unit suites this needs no GBA toolchain, no mGBA build and no
ROM: it compiles src/gbcgamedetect.c with the host C compiler and calls the
function directly.

Usage:
    python3 test_roms/test_gbc_palette_unit.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
UNIT_DIR = SCRIPT_DIR / "unit"
SRC_C = UNIT_DIR / "test_gbc_palette.c"
DETECT_C = PROJECT_DIR / "src" / "gbcgamedetect.c"
SRC_INC = PROJECT_DIR / "src"

# The section attributes are meaningful only to the GBA toolchain; mach-o and
# ELF hosts reject ".sbss"/".ewram", so define them away for the host build.
HOST_DEFINES = ["-DEWRAM_BSS=", "-DEWRAM_DATA=", "-DIWRAM_CODE="]


def main():
    for path in (SRC_C, DETECT_C):
        if not path.exists():
            print(f"ERROR: {path} not found")
            sys.exit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        binary = Path(tmpdir) / "test_gbc_palette"

        compile_result = subprocess.run(
            ["cc", "-O1", "-Wall", "-fno-common", f"-I{SRC_INC}", *HOST_DEFINES,
             str(SRC_C), str(DETECT_C), "-o", str(binary)],
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
