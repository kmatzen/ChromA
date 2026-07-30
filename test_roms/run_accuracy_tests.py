#!/usr/bin/env python3
"""Hardware-accuracy test ROM suite (Mooneye Test Suite + Blargg) -- issue #65.

Usage:
    python3 test_roms/run_accuracy_tests.py                 # run the suite
    python3 test_roms/run_accuracy_tests.py -t <name>       # run specific test(s)
    python3 test_roms/run_accuracy_tests.py --list          # list the suite
    python3 test_roms/run_accuracy_tests.py --diff-dir DIR  # save diff images
    python3 test_roms/run_accuracy_tests.py --rebaseline    # regenerate references

Prerequisites: `make`, `make -f test_roms/Makefile.test`, and
`python3 test_roms/fetch_accuracy_roms.py`.

How a test passes
-----------------
Each ROM is run twice, which is the same reference trick test_stat_ly.py
already uses:

  * once natively on mGBA's own Game Boy core, cropped to the 160x144 LCD --
    this is the *reference*, committed under baselines/accuracy/;
  * once wrapped in chroma.gba on mGBA's GBA core, cropped to the same 160x144
    region of the 240x160 GBA frame.

Mooneye and Blargg ROMs settle on a static pass/fail screen ("Test OK",
"Test failed", "Passed", "Failed", or a register/assertion dump), so the two
screens are compared pixel-for-pixel.  ChromA renders these ROMs in the same
black-and-white shades mGBA does, so a correct emulation is bit-identical --
verified: the 14 passing entries below match their reference exactly.

Because the reference comes from mGBA and never from ChromA, --rebaseline
cannot bake ChromA's current broken output in as the new truth.  That is the
failure mode #99 was about, and it is structurally impossible here.

Why these ROMs and not others
-----------------------------
accuracy_config.json also carries an "unusable" list: ROMs where mGBA itself
does not produce a passing screen, so it cannot supply a correct reference.
Those are reported in the summary rather than silently dropped -- a suite that
quietly skips a third of its ROMs reads as "covered" when it is not.

Expected failures
-----------------
Entries marked expected_fail are accuracy bugs that are open today.  They
report XFAIL and do not fail the build.  When one starts matching its
reference it reports XPASS and *does* fail the build, so the fix gets recorded
in accuracy_config.json instead of the coverage quietly staying disabled --
the same XPASS contract run_tests.py uses.
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("ERROR: Pillow is required. Install with: pip3 install Pillow")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

# Reuse the comparison/compile/run primitives so there is a single definition
# of what "these two screens match" means across the visual suites.
from run_tests import RUNNER, EMULATOR, compile_test_rom, run_test, compare_images

PROJECT_DIR = SCRIPT_DIR.parent
CONFIG = SCRIPT_DIR / "accuracy_config.json"
ROM_DIR = SCRIPT_DIR / "accuracy_roms"
BASELINE_DIR = SCRIPT_DIR / "baselines" / "accuracy"


def load_config():
    with open(CONFIG) as f:
        return json.load(f)


def baseline_name(tag):
    return tag.replace("/", "__") + ".png"


def crop_of(bmp_path, box):
    return Image.open(bmp_path).convert("RGB").crop(tuple(box))


def border_is_blank(bmp_path, box):
    """True if everything outside the LCD area is a single flat colour.

    The crop offsets are a property of how ChromA frames the Game Boy screen
    inside the 240x160 GBA display.  If that framing ever changes, cropping
    the old box silently compares the wrong 160x144 pixels, so check the
    assumption instead of trusting it.
    """
    im = Image.open(bmp_path).convert("RGB")
    px = im.load()
    x0, y0, x1, y1 = box
    seen = set()
    for y in range(im.size[1]):
        for x in range(im.size[0]):
            if x0 <= x < x1 and y0 <= y < y1:
                continue
            seen.add(px[x, y])
            if len(seen) > 1:
                return False
    return True


def run_native(rom, frames, out_bmp):
    """Render the reference screen with mGBA's own Game Boy core."""
    return run_test(rom, frames, out_bmp)


def run_chroma(rom, frames, tmpdir, tag, out_bmp):
    gba = tmpdir / (tag.replace("/", "__") + ".gba")
    if not compile_test_rom(rom, gba):
        return False
    return run_test(gba, frames, out_bmp)


def run_one(tag, info, cfg, tmpdir, diff_dir=None):
    rom = ROM_DIR / info["rom"]
    frames = info["frames"]
    geom = cfg["geometry"]
    print(f"\n{'='*60}")
    print(f"Test: {tag}")
    if info.get("note"):
        print(f"  {info['note']}")
    print(f"  ROM: {info['rom']}  ({frames} frames)")

    if not rom.exists():
        print(f"  ERROR: ROM not found. Run fetch_accuracy_roms.py")
        return "ERROR"

    baseline = BASELINE_DIR / baseline_name(tag)
    if not baseline.exists():
        print(f"  MISSING: no reference at {baseline.name} (--rebaseline to create)")
        return "MISSING"

    bmp = tmpdir / (tag.replace("/", "__") + "_chroma.bmp")
    if not run_chroma(rom, frames, tmpdir, tag, bmp):
        return "ERROR"

    if not border_is_blank(bmp, geom["chroma_crop"]):
        print(f"  ERROR: content outside the expected {geom['chroma_crop']} LCD "
              f"area -- ChromA's screen framing changed, so the crop no longer "
              f"selects the Game Boy screen")
        return "ERROR"

    actual = crop_of(bmp, geom["chroma_crop"])
    png = tmpdir / (tag.replace("/", "__") + "_chroma.png")
    actual.save(png)

    match, diff_count, diff_img = compare_images(baseline, png)
    total = actual.size[0] * actual.size[1]

    if match:
        if info.get("expected_fail"):
            print(f"  XPASS: matches the reference, but is marked expected_fail.")
            print(f"         The bug looks fixed -- clear expected_fail for "
                  f"'{tag}' in accuracy_config.json.")
            return "XPASS"
        print(f"  PASS")
        return "PASS"

    pct = diff_count / total * 100
    kind = "XFAIL" if info.get("expected_fail") else "FAIL"
    print(f"  {kind}: {diff_count} pixels differ ({pct:.1f}%)")

    if diff_dir:
        d = Path(diff_dir)
        d.mkdir(parents=True, exist_ok=True)
        stem = tag.replace("/", "__")
        exp = Image.open(baseline).convert("RGB")
        w, h = actual.size
        comp = Image.new("RGB", (w * 3, h + 20), (40, 40, 40))
        comp.paste(exp, (0, 20))
        comp.paste(actual, (w, 20))
        if diff_img:
            comp.paste(diff_img, (w * 2, 20))
        dr = ImageDraw.Draw(comp)
        dr.text((5, 2), "mGBA reference", fill=(255, 255, 255))
        dr.text((w + 5, 2), "ChromA", fill=(255, 255, 255))
        dr.text((w * 2 + 5, 2), "Diff", fill=(255, 0, 0))
        comp.save(d / f"{stem}_comparison.png")
        print(f"  Diff saved to: {d / f'{stem}_comparison.png'}")

    return kind


def rebaseline(tags, cfg, tmpdir, force=False):
    """Regenerate reference screens from mGBA's Game Boy core."""
    geom = cfg["geometry"]
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    wrote = skipped = errors = 0
    for tag in tags:
        info = cfg["tests"][tag]
        rom = ROM_DIR / info["rom"]
        if not rom.exists():
            print(f"  {tag}: ERROR, ROM not found")
            errors += 1
            continue
        out = BASELINE_DIR / baseline_name(tag)
        bmp = tmpdir / (tag.replace("/", "__") + "_native.bmp")
        # The reference only needs the ROM to reach its result screen; these
        # settle well inside the run length used for the ChromA pass.
        if not run_native(rom, max(120, info["frames"] // 2), bmp):
            print(f"  {tag}: ERROR running natively")
            errors += 1
            continue
        new = crop_of(bmp, geom["native_crop"])
        if out.exists() and not force:
            png = tmpdir / (tag.replace("/", "__") + "_native.png")
            new.save(png)
            match, n, _ = compare_images(out, png)
            if match:
                print(f"  {tag}: unchanged")
            else:
                # A changed reference means mGBA's own output moved.  It may
                # now be a *failing* screen, which would silently redefine
                # "correct" for this test, so make a human look.
                print(f"  {tag}: reference CHANGED ({n} px) -- not overwriting. "
                      f"Confirm the new screen is still a passing screen, then "
                      f"re-run with --force.")
                skipped += 1
            continue
        new.save(out)
        print(f"  {tag}: reference written to {out.name}")
        wrote += 1
    print(f"\n{wrote} written, {skipped} left alone, {errors} errors")
    return 1 if errors or skipped else 0


def main():
    ap = argparse.ArgumentParser(
        description="Hardware-accuracy test ROM suite for ChromA",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--test", "-t", action="append", help="Run specific test(s)")
    ap.add_argument("--diff-dir", "-d", default=None, help="Directory for diff images")
    ap.add_argument("--list", "-l", action="store_true", help="List the suite")
    ap.add_argument("--rebaseline", action="store_true",
                    help="Regenerate reference screens from mGBA's Game Boy core")
    ap.add_argument("--force", action="store_true",
                    help="With --rebaseline, overwrite references that changed")
    args = ap.parse_args()

    cfg = load_config()
    tests = cfg["tests"]

    if args.list:
        print(f"Accuracy suite ({len(tests)} ROMs, pack {cfg['rom_pack']['version']}):")
        for tag, info in tests.items():
            mark = "xfail" if info.get("expected_fail") else "pass"
            print(f"  [{mark}] {tag}")
        print(f"\nUnusable ({len(cfg['unusable'])} ROMs, no correct reference "
              f"available from mGBA):")
        for tag, info in cfg["unusable"].items():
            print(f"  [skip] {tag}: {info['reason']}")
        return 0

    if not RUNNER.exists():
        print(f"ERROR: mgba_runner not found at {RUNNER}")
        print("Build it with: make -f test_roms/Makefile.test")
        return 1
    if not EMULATOR.exists():
        print(f"ERROR: chroma.gba not found at {EMULATOR}")
        print("Build it with: make")
        return 1
    if not ROM_DIR.exists():
        print(f"ERROR: accuracy ROMs not found at {ROM_DIR}")
        print("Fetch them with: python3 test_roms/fetch_accuracy_roms.py")
        return 1

    selected = list(tests)
    if args.test:
        selected, unknown = [], []
        for t in args.test:
            if t in tests:
                selected.append(t)
            else:
                unknown.append(t)
        if not selected:
            print(f"ERROR: none of the requested tests exist: {', '.join(unknown)}")
            return 1
        for u in unknown:
            print(f"WARNING: test '{u}' not found")

    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)

        if args.rebaseline:
            return rebaseline(selected, cfg, tmpdir, force=args.force)

        results = {}
        for tag in selected:
            results[tag] = run_one(tag, tests[tag], cfg, tmpdir, diff_dir=args.diff_dir)

    print(f"\n{'='*60}")
    print("ACCURACY SUITE SUMMARY")
    print(f"{'='*60}")
    counts = {}
    for tag, r in results.items():
        counts[r] = counts.get(r, 0) + 1
    char = {"PASS": ".", "FAIL": "F", "XFAIL": "x", "XPASS": "X",
            "MISSING": "?", "ERROR": "E"}
    for tag, r in results.items():
        if r != "XFAIL":
            print(f"  [{char.get(r, '?')}] {tag}: {r}")
    if counts.get("XFAIL"):
        print(f"  [x] {counts['XFAIL']} known accuracy failures (XFAIL), "
              f"listed in accuracy_config.json")

    print()
    order = ["PASS", "XFAIL", "FAIL", "XPASS", "MISSING", "ERROR"]
    print(", ".join(f"{counts[k]} {k}" for k in order if counts.get(k)))

    # Say what the suite did not cover, every run.  Silence here would read as
    # full coverage of the upstream suites.
    if cfg["unusable"]:
        print(f"\nNot covered ({len(cfg['unusable'])} ROMs): mGBA does not produce "
              f"a passing screen, so there is no correct reference to compare "
              f"against. Run with --list for the reasons.")

    bad = sum(counts.get(k, 0) for k in ("FAIL", "XPASS", "MISSING", "ERROR"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
