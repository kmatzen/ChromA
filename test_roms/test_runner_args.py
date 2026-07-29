#!/usr/bin/env python3
"""Guard mgba_runner's argument validation (issue #58).

mgba_runner used to `continue` past anything it could not parse -- a
screenshot scheduled past the end of the run, a misspelled key name, a typo'd
flag, a missing colon -- and still exit 0.  Tests that asked for inputs and
screenshots therefore ran without them and reported success, which is exactly
the "harness cannot fail" class this file exists to prevent regressing.

Every case below is checked on *both* the exit status and the diagnostic, so
the test cannot be satisfied by an unrelated failure (a missing ROM also exits
non-zero).  Argument parsing happens before the ROM is loaded, so these run
without a ROM, an emulator build, or a toolchain -- only mgba_runner itself.

Usage: python3 test_roms/test_runner_args.py
"""

import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
RUNNER = SCRIPT_DIR / "mgba_runner"

# A path mCoreFind will reject, so a successful parse still stops before
# emulating anything.
NO_ROM = "/nonexistent/definitely-not-a.gba"
OUT = "/dev/null"

# (description, extra argv, frames, expected stderr substring)
REJECT_CASES = [
    ("screenshot past the run length",
     ["--screenshot", "500:/dev/null"], "100", "would never be captured"),
    ("screenshot exactly at the run length (frames are 0-indexed)",
     ["--screenshot", "100:/dev/null"], "100", "would never be captured"),
    ("screenshot missing its colon",
     ["--screenshot", "50"], "100", "expected frame:path"),
    ("screenshot with a non-numeric frame",
     ["--screenshot", "abc:/dev/null"], "100", "expected a non-negative integer"),
    ("screenshot missing its operand",
     ["--screenshot"], "100", "requires an argument"),
    ("misspelled flag",
     ["--screenshots", "50:/dev/null"], "100", "unrecognized argument"),
    ("input with an unknown key name",
     ["--input", "10:Stat"], "100", "unknown key"),
    ("input missing its colon",
     ["--input", "10"], "100", "expected frame:keys"),
    ("input with no key names",
     ["--input", "10:"], "100", "no key names"),
    ("memdump with too few fields",
     ["--memdump", "0x1000:4"], "100", "expected addr:len:file"),
    ("memdump with zero length",
     ["--memdump", "0x1000:0:/dev/null"], "100", "must be non-zero"),
    ("zero frames",
     [], "0", "must be at least 1"),
    ("negative frames",
     [], "-5", "must be at least 1"),
    ("non-numeric frames",
     [], "abc", "must be at least 1"),
]

# Argument sets that must parse cleanly. They still exit non-zero because the
# ROM does not exist -- what matters is that the parser raised no ERROR.
ACCEPT_CASES = [
    ("no options", []),
    ("screenshot inside the run", ["--screenshot", "50:/dev/null"]),
    ("input and savefile", ["--input", "10:Start", "--savefile", "/dev/null"]),
    ("multi-key input", ["--input", "10:L+R"]),
    ("hex memdump address", ["--memdump", "0x030038CC:4:/dev/null"]),
    ("decimal memdump address", ["--memdump", "33783808:16:/dev/null"]),
]


def invoke(extra, frames):
    return subprocess.run([str(RUNNER), NO_ROM, frames, OUT] + extra,
                          capture_output=True, text=True, timeout=60)


def main():
    if not RUNNER.exists():
        print(f"ERROR: mgba_runner not found at {RUNNER}")
        print("Build it with: make -f test_roms/Makefile.test")
        return 1

    failures = 0
    print("=== mgba_runner argument validation ===")

    for desc, extra, frames, marker in REJECT_CASES:
        r = invoke(extra, frames)
        if r.returncode == 0:
            print(f"  FAIL: {desc}: exited 0, should have been rejected")
            failures += 1
        elif marker not in r.stderr:
            print(f"  FAIL: {desc}: exited {r.returncode} but without the "
                  f"expected diagnostic {marker!r}")
            print(f"        stderr: {r.stderr.strip()[:200]}")
            failures += 1
        else:
            print(f"  ok: rejects {desc}")

    for desc, extra in ACCEPT_CASES:
        r = invoke(extra, "100")
        if "ERROR:" in r.stderr:
            print(f"  FAIL: {desc}: valid arguments rejected by the parser")
            print(f"        stderr: {r.stderr.strip()[:200]}")
            failures += 1
        else:
            print(f"  ok: accepts {desc}")

    total = len(REJECT_CASES) + len(ACCEPT_CASES)
    print(f"\n  {total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
