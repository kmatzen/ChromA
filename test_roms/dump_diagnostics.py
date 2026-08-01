#!/usr/bin/env python3
"""Read the accuracy ROMs' own on-screen diagnostics (issue #138).

run_accuracy_tests.py compares ChromA's screen against a reference and reports
a pixel count, so a ROM that fails is never actually *read* -- but the Mooneye
ROMs print an expected-vs-actual register dump and the Blargg ROMs print a
per-case table.  That text is the difference between "ppu/intr_2_0_timing
XFAILs by 1.1%" and "LY reads $00 where it should read $01 at cycle $82".

Reading those diagnostics by hand is what turned two vague issues into
single-tick targets and produced the DIV/TIMA fix in #132 (four ROMs XFAIL ->
XPASS).  This does it for every ROM at once.

The text is decoded, not eyeballed: these ROMs draw with an 8x8 tile font in
pure black on white, so a glyph is a dictionary lookup (accuracy_font.py).
The atlas covers every glyph on all 49 committed reference screens; anything
outside it decodes as '?' rather than being guessed at.

Usage:
    python3 test_roms/dump_diagnostics.py                # every XFAIL entry
    python3 test_roms/dump_diagnostics.py --all          # every entry
    python3 test_roms/dump_diagnostics.py -t timer       # substring filter
    python3 test_roms/dump_diagnostics.py --unusable     # the unusable list
    python3 test_roms/dump_diagnostics.py --diff-only    # hide matching lines

Prerequisites are the same as run_accuracy_tests.py: `make`,
`make -f test_roms/Makefile.test`, and `fetch_accuracy_roms.py`.

The "unusable" ROMs are worth a look even though they have no valid reference
screen: lcdon_timing-GS is listed unusable because mGBA fails it too, but its
own diagnostic still says exactly where ChromA diverges -- which is how #145
got its cycle number.
"""

import argparse
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow is required. Install with: pip3 install Pillow")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from accuracy_font import decode_screen, render_bitmap
from run_accuracy_tests import (BASELINE_DIR, ROM_DIR, baseline_name, crop_of,
                                load_config, run_chroma)

# Frame budget for the "unusable" entries, which carry no frames field.
DEFAULT_FRAMES = 900


def decode_file(path, unknown):
    if not Path(path).exists():
        return None
    return decode_screen(Image.open(path), unknown)


def side_by_side(actual, expected, diff_only=False):
    """Render ChromA's text next to the reference, marking differing lines."""
    width = max([len(l) for l in actual] + [0] + [len("ChromA")])
    width = max(width, 6)
    rows = max(len(actual), len(expected or []))
    out = []
    out.append(f"    {'ChromA'.ljust(width)}   | reference")
    out.append(f"    {'-' * width}---+{'-' * 22}")
    for i in range(rows):
        a = actual[i] if i < len(actual) else ""
        e = expected[i] if expected and i < len(expected) else ""
        if expected is None:
            mark = " "
        else:
            mark = " " if a == e else "*"
        if diff_only and mark == " ":
            continue
        out.append(f"  {mark} {a.ljust(width)}   | {e}")
    return out


def dump_one(tag, info, cfg, tmpdir, expected_available=True, diff_only=False):
    rom = ROM_DIR / info["rom"]
    frames = info["frames"]
    print(f"\n{'=' * 68}")
    print(f"{tag}")
    if info.get("note"):
        print(f"  note: {info['note']}")
    if info.get("reason"):
        print(f"  unusable: {info['reason']}")

    if not rom.exists():
        print("  ERROR: ROM not found. Run fetch_accuracy_roms.py")
        return False

    bmp = tmpdir / (tag.replace("/", "__") + "_chroma.bmp")
    if not run_chroma(rom, frames, tmpdir, tag, bmp):
        print("  ERROR: run failed")
        return False

    unknown = []
    actual = decode_screen(crop_of(bmp, cfg["geometry"]["chroma_crop"]), unknown)
    expected = None
    if expected_available:
        base = BASELINE_DIR / baseline_name(tag)
        expected = decode_file(base, unknown)

    if not actual:
        print("  (blank screen -- the ROM printed nothing)")
    else:
        for line in side_by_side(actual, expected, diff_only):
            print(line)

    if unknown:
        print(f"\n  {len(unknown)} glyph(s) not in the atlas, shown as '?'.")
        print("  Add them to ATLAS in accuracy_font.py:")
        for bits in unknown:
            for row in render_bitmap(bits).split("\n"):
                print(f"      {row}")
            print()
    return True


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-t", "--test", action="append",
                    help="substring filter on the test name; repeatable")
    ap.add_argument("--all", action="store_true",
                    help="include entries that currently pass")
    ap.add_argument("--unusable", action="store_true",
                    help="dump the 'unusable' ROMs instead (no reference "
                         "screen exists, but their text is still readable)")
    ap.add_argument("--diff-only", action="store_true",
                    help="print only lines that differ from the reference")
    args = ap.parse_args()

    cfg = load_config()

    if args.unusable:
        # The unusable entries carry no frame count -- they were never meant
        # to be run -- so give them the same budget the suite's slowest
        # entries use.  These ROMs settle on a static screen well before that.
        entries = [(tag, dict(info, frames=info.get("frames", DEFAULT_FRAMES)))
                   for tag, info in cfg.get("unusable", {}).items()]
    else:
        entries = [(tag, info) for tag, info in cfg["tests"].items()
                   if args.all or info.get("expected_fail")]

    if args.test:
        entries = [(t, i) for t, i in entries
                   if any(f in t for f in args.test)]

    if not entries:
        print("No matching entries.")
        return 0

    kind = "unusable" if args.unusable else (
        "entries" if args.all else "XFAIL entries")
    print(f"Dumping on-screen diagnostics for {len(entries)} {kind}.")
    if not args.unusable:
        print("Lines marked '*' differ from the reference screen.")

    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        for tag, info in entries:
            dump_one(tag, info, cfg, tmpdir,
                     expected_available=not args.unusable,
                     diff_only=args.diff_only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
