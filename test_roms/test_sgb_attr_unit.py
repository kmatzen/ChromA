#!/usr/bin/env python3
"""Host-side unit tests for the SGB attribute commands (issue #136).

ATTR_BLK, ATTR_LIN, ATTR_DIV and ATTR_CHR (src/sgb_attr.c) decode into the
20x18 attribute map that ATTR_SET/PAL_SET already fill from a stored ATF.  All
four returned immediately before this, so a game colourising its screen with
them kept whatever the last ATTR_SET had left.

Like the other unit suites this needs no GBA toolchain, no mGBA build and no
ROM: it compiles src/sgb_attr.c with the host C compiler and calls the
decoders directly.  That matters more than usual here -- no renderer consumes
the attribute map yet (item 2 of #136), so there is nothing on screen to check
the decode against, and this suite is the only thing standing between the
documented rules and a silent misreading of them.

Usage:
    python3 test_roms/test_sgb_attr_unit.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
UNIT_DIR = SCRIPT_DIR / "unit"
SRC_C = UNIT_DIR / "test_sgb_attr.c"
ATTR_C = PROJECT_DIR / "src" / "sgb_attr.c"
SRC_INC = PROJECT_DIR / "src"

# The section attributes are meaningful only to the GBA toolchain; mach-o and
# ELF hosts reject ".sbss"/".ewram", so define them away for the host build.
HOST_DEFINES = ["-DEWRAM_BSS=", "-DEWRAM_DATA=", "-DIWRAM_CODE="]


def main():
    for path in (SRC_C, ATTR_C):
        if not path.exists():
            print(f"ERROR: {path} not found")
            sys.exit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        binary = Path(tmpdir) / "test_sgb_attr"

        compile_result = subprocess.run(
            ["cc", "-O1", "-Wall", "-fno-common", f"-I{SRC_INC}", *HOST_DEFINES,
             str(SRC_C), str(ATTR_C), "-o", str(binary)],
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
