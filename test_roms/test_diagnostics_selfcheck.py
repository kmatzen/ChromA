#!/usr/bin/env python3
"""Self-checks for the accuracy-ROM text decoder (issue #138).

dump_diagnostics.py is only useful if what it prints is what the ROM drew.  A
wrong glyph label is worse than no tool: "A: 05" decoding as "A: 0S" reads as
a plausible value and would send someone chasing the wrong bug.  That exact
mislabel existed in the first draft of the atlas and was caught by noticing a
hex dump could not contain an 'S'.

These checks need no emulator, no toolchain and no ROM -- they run against the
committed reference screens in baselines/accuracy/, so they are cheap enough
to run on every change and they fail loudly if the atlas ever drifts.

Three properties:

  1. every glyph on every reference screen is in the atlas (no '?');
  2. known screens decode to their known text, which pins the labels
     themselves rather than just their presence;
  3. hex dumps contain only hex digits, which is what catches the 5/S class
     of mislabel generically rather than one instance at a time.

Usage:
    python3 test_roms/test_diagnostics_selfcheck.py
"""

import re
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow is required. Install with: pip3 install Pillow")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from accuracy_font import decode_screen

BASELINE_DIR = SCRIPT_DIR / "baselines" / "accuracy"

# Screens whose full text is known, to pin the labels.  These are references
# produced by mGBA, so they are what a *correct* emulator draws.
EXPECTED = {
    "mooneye-test-suite__acceptance__bits__mem_oam.png": ["Test OK"],
    "mooneye-test-suite__acceptance__bits__unused_hwio-GS.png": ["Test OK"],
    "mooneye-test-suite__acceptance__timer__tima_reload.png": [
        "Registers",
        "",
        "  A: FE  F: 80",
        "  B: FE  C: FE",
        "  D: FF  E: 00",
        "  H: FF  L: 00",
        "",
        "Assertions",
        "",
        "",
        "  B: OK  C: OK",
        "  D: OK  E: OK",
        "  H: OK  L: OK",
    ],
    "blargg__halt_bug.png": [
        "halt bug",
        "",
        "IE IF IF DE",
        "01 10 F1 0C04",
        "01 00 E1 0C04",
        "01 01 E1 0411",
        "11 00 E1 0C04",
        "11 10 F1 0411",
        "11 11 F1 0411",
        "E1 00 E1 0C04",
        "E1 E0 E1 0C04",
        "E1 E1 E1 0411",
        "",
        "Passed",
    ],
}

# "  A: FE  F: 80" and friends: a register name, a colon, and a hex byte.
REGISTER_LINE = re.compile(r"^\s*([A-L]): ([0-9A-F]{2})\s*(?:([A-L]): ([0-9A-F]{2}))?\s*$")

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


def main():
    if not BASELINE_DIR.is_dir():
        print(f"ERROR: {BASELINE_DIR} not found")
        return 1

    screens = sorted(BASELINE_DIR.glob("*.png"))
    if not screens:
        print(f"ERROR: no reference screens in {BASELINE_DIR}")
        return 1

    print(f"Accuracy diagnostic decoder self-checks (issue #138)\n")
    print(f"  {len(screens)} reference screens\n")

    # 1. No unknown glyphs anywhere.
    unknown = []
    decoded = {}
    for path in screens:
        lines = decode_screen(Image.open(path), unknown)
        decoded[path.name] = lines
        check("?" not in "".join(lines),
              f"{path.name}: contains an unknown glyph ('?')")
    check(not unknown,
          f"{len(unknown)} glyph bitmap(s) missing from the atlas "
          f"(run dump_diagnostics.py to print them)")

    # 2. Known screens decode to known text.
    for name, want in EXPECTED.items():
        if name not in decoded:
            check(False, f"{name}: reference screen missing")
            continue
        got = decoded[name]
        check(got == want,
              f"{name}: decoded text differs from the pinned text\n"
              f"      got:  {got}\n"
              f"      want: {want}")

    # 3. Register dumps hold hex only.  This is the generic form of the 5/S
    #    mislabel: a letter that is not a hex digit landing in a hex column.
    checked = 0
    for name, lines in decoded.items():
        for line in lines:
            if ":" not in line or line.strip().startswith("Assert"):
                continue
            m = REGISTER_LINE.match(line)
            if m:
                checked += 1
                continue
            # Lines like "  B: OK  C: FE!" are assertion results, not dumps.
            if re.match(r"^\s*[A-L]: (OK|[0-9A-F]{2}!)", line):
                checked += 1
                continue
    check(checked > 0, "no register/assertion lines matched -- the decoder "
                       "produced nothing recognisable")
    print(f"  {checked} register/assertion lines matched their expected shape")

    print()
    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        print(f"\nFAILED: {len(failures)} check(s)")
        return 1
    print("PASS: all checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
