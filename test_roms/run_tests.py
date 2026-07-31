#!/usr/bin/env python3
"""Automated visual regression testing for ChromA.

Usage:
    python3 test_roms/run_tests.py                    # Run all tests, compare to baselines
    python3 test_roms/run_tests.py --rebaseline       # Generate new baselines
    python3 test_roms/run_tests.py --test cpu_instrs   # Run a specific test
    python3 test_roms/run_tests.py --diff-dir /tmp/diffs  # Save diff images

Prerequisites:
    - mgba_runner binary (compile with: make -f test_roms/Makefile.test)
    - goomba_compile.py (in test_roms/)
    - Test ROMs in test_roms/ (e.g., cpu_instrs.gb, cgb-acid2.gbc)
    - Pillow: pip3 install Pillow
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image, ImageChops, ImageDraw
except ImportError:
    print("ERROR: Pillow is required. Install with: pip3 install Pillow")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
RUNNER = SCRIPT_DIR / "mgba_runner"
COMPILER = SCRIPT_DIR / "goomba_compile.py"
EMULATOR = PROJECT_DIR / "chroma.gba"
BASELINE_DIR = SCRIPT_DIR / "baselines"
TEST_CONFIG = SCRIPT_DIR / "test_config.json"


def load_test_config():
    """Load test configuration from JSON file."""
    if not TEST_CONFIG.exists():
        return {}
    with open(TEST_CONFIG) as f:
        return json.load(f)


def compile_test_rom(rom_path, output_path):
    """Wrap a GB/GBC ROM with ChromA using goomba_compile.py."""
    result = subprocess.run(
        [sys.executable, str(COMPILER), "-e", str(EMULATOR), "-o", str(output_path), str(rom_path)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  ERROR compiling: {result.stderr}")
        return False
    return True


def run_test(gba_path, frames, output_bmp, inputs=None, screenshots=None):
    """Run a test ROM through mgba_runner and capture screenshot."""
    cmd = [str(RUNNER), str(gba_path), str(frames), str(output_bmp)]
    if inputs:
        for inp in inputs:
            cmd.extend(["--input", inp])
    if screenshots:
        for ss in screenshots:
            cmd.extend(["--screenshot", ss])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        print(f"  ERROR running: exit code {result.returncode}")
        print(f"  stderr: {result.stderr}")
        return False
    return True


# How many frames either side of a configured capture point are accepted as
# the same screenshot (issue #37).
#
# A host frame number is not a property of the emulated machine.  Any change
# that shifts emulation timing by a fraction of a frame -- a toolchain bump, a
# few bytes of IWRAM, a cycle-accuracy fix -- slides a game's animation
# relative to it, and a capture that lands on a blinking cursor, a cycling
# sprite or a drifting cloud then differs from its baseline while the scene is
# otherwise pixel-identical.  Issue #37 documents four tests failing that way
# for months; #114 moved six more and #117 another four, each time needing the
# diff images opened by hand to establish that nothing was actually
# mis-rendered.
#
# So a capture matches if the baseline turns up anywhere in [N-W, N+W].  The
# comparison stays *exact* -- no pixel tolerance, no masked regions -- because
# a real rendering change alters every frame in the window, not just one.
# What this deliberately gives up is sensitivity to a pure timing shift of
# <= W frames, which is precisely the thing #37 says is not a regression.
CAPTURE_WINDOW = 3


def compare_images(img_a_path, img_b_path, threshold=0, ignore=None):
    """Compare two images. Returns (match, diff_count, diff_image).

    `ignore` is a list of [x0, y0, x1, y1] rectangles blanked in *both* images
    before the comparison.  It exists for elements that blink on a period too
    long for the capture window to find the matching phase -- a text-advance
    arrow that is on for 16 frames and off for 16 cannot be recovered by
    looking three frames either side, and its state carries no information
    about whether rendering is correct.  Every rectangle in the config was
    measured, not guessed: run the suite against a deliberately retimed build
    and the differing pixels are exactly the blinking element.

    Deliberately narrow.  A blanket pixel tolerance would have to be ~4% to
    cover the cases seen here, which is well above the 1.3-2.2% real
    regressions #37 lists -- it would mask the very thing it is meant to
    catch.  A named 8x6 box does not.
    """
    img_a = Image.open(img_a_path).convert("RGB")
    img_b = Image.open(img_b_path).convert("RGB")

    if img_a.size != img_b.size:
        return False, -1, None

    if ignore:
        img_a = img_a.copy()
        img_b = img_b.copy()
        da, db = ImageDraw.Draw(img_a), ImageDraw.Draw(img_b)
        for x0, y0, x1, y1 in ignore:
            da.rectangle([x0, y0, x1 - 1, y1 - 1], fill=(0, 0, 0))
            db.rectangle([x0, y0, x1 - 1, y1 - 1], fill=(0, 0, 0))

    diff = ImageChops.difference(img_a, img_b)
    pixels = list(diff.getdata())
    diff_count = sum(1 for p in pixels if any(c > threshold for c in p))

    # Create a highlighted diff image
    diff_img = img_a.copy()
    draw = ImageDraw.Draw(diff_img)
    w = img_a.size[0]
    for i, p in enumerate(pixels):
        if any(c > threshold for c in p):
            x, y = i % w, i // w
            draw.point((x, y), fill=(255, 0, 0))

    return diff_count == 0, diff_count, diff_img


def skip_rebaseline_reason(test_info, include_xfail=False):
    """Why --rebaseline must not touch this test's baselines, or None.

    An expected_fail baseline is the reference for what the output is SUPPOSED
    to look like while a bug is open.  Overwriting it with the current output
    makes the broken rendering the new truth and silently retires the bug --
    Cannon Fodder's baselines document #36, for instance.  A blanket
    --rebaseline used to do exactly that, and the operator got a commit with
    no signal about which files were safe to keep (#99).
    """
    if test_info.get("expected_fail") and not include_xfail:
        return ("expected_fail: its baseline documents a known bug, and "
                "replacing it would retire that bug silently")
    return None


def rebaseline_screenshot(baseline_path, new_png_path):
    """Write new_png_path over baseline_path only if the pixels differ.

    Returns True if it wrote.  Re-encoding a pixel-identical capture still
    produces different PNG bytes, so writing unconditionally churned files for
    tests that were passing -- 7 of the 20 files in the #97 rebaseline and 2
    of the 29 in #100 were of that kind.
    """
    baseline_path = Path(baseline_path)
    if baseline_path.exists():
        match, _, _ = compare_images(baseline_path, new_png_path)
        if match:
            return False
    Image.open(new_png_path).save(baseline_path)
    return True


def discover_tests():
    """Find all test ROMs and their configurations."""
    config = load_test_config()
    tests = {}

    # Find all .gb and .gbc files in test_roms/
    for ext in ["*.gb", "*.gbc"]:
        for rom in SCRIPT_DIR.glob(ext):
            name = rom.stem
            test_cfg = config.get(name, {})
            if test_cfg.get("skip_visual"):
                # This ROM is exercised by a dedicated harness (SRAM/state
                # reads, not a screenshot) -- e.g. test_nexttimeout_nesting.py.
                # Without this, the glob above picked it up anyway, it had no
                # baseline image and never would, and MISSING-baseline used
                # to be silently excluded from the exit code, so it "passed"
                # while verifying nothing here.
                continue
            tests[name] = {
                "rom": rom,
                "frames": test_cfg.get("frames", 7200),
                "inputs": test_cfg.get("inputs", []),
                "screenshots": test_cfg.get("screenshots", []),
                "description": test_cfg.get("description", ""),
                "expected_fail": test_cfg.get("expected_fail", False),
                "capture_window": test_cfg.get("capture_window", CAPTURE_WINDOW),
                "ignore": test_cfg.get("ignore", {}),
            }

    return tests


def run_single_test(name, test_info, rebaseline=False, diff_dir=None, verbose=False,
                    include_xfail=False):
    """Run a single test and compare against baseline."""
    print(f"\n{'='*60}")
    print(f"Test: {name}")
    if test_info["description"]:
        print(f"  {test_info['description']}")
    print(f"  ROM: {test_info['rom'].name}")
    print(f"  Frames: {test_info['frames']}")

    if rebaseline:
        reason = skip_rebaseline_reason(test_info, include_xfail)
        if reason:
            print(f"  SKIPPED: {reason}")
            print(f"  (pass --include-xfail to rebaseline it anyway)")
            return "SKIPPED"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Compile test ROM
        gba_path = tmpdir / f"{name}_test.gba"
        print(f"  Compiling...")
        if not compile_test_rom(test_info["rom"], gba_path):
            return "ERROR"

        # Run test
        output_bmp = tmpdir / f"{name}_final.bmp"
        screenshot_bmps = []
        screenshots_args = []
        window = test_info.get("capture_window", CAPTURE_WINDOW)
        total = test_info["frames"]
        # Alternates for each capture: same screenshot, a few frames either
        # side, so an animation that has slid under a timing change can still
        # be recognised (#37).  Kept separate from the configured frame, which
        # stays the one that gets baselined.
        alt_bmps = {}
        for ss in test_info.get("screenshots", []):
            ss_name = ss.get("name", f"frame_{ss['frame']}")
            ss_bmp = tmpdir / f"{name}_{ss['frame']}.bmp"
            screenshots_args.append(f"{ss['frame']}:{ss_bmp}")
            screenshot_bmps.append((ss["frame"], ss_bmp, ss_name))
            alts = []
            for d in range(-window, window + 1):
                if d == 0:
                    continue
                f = ss["frame"] + d
                if f < 0 or f >= total:
                    continue
                alt = tmpdir / f"{name}_{ss['frame']}_alt{d}.bmp"
                screenshots_args.append(f"{f}:{alt}")
                alts.append(alt)
            alt_bmps[ss_name] = alts

        # The run's own final screenshot is taken after the last frame, so its
        # alternates are the frames just before it.
        final_alts = []
        for d in range(1, window + 1):
            f = total - 1 - d
            if f < 0:
                continue
            alt = tmpdir / f"{name}_final_alt{d}.bmp"
            screenshots_args.append(f"{f}:{alt}")
            final_alts.append(alt)
        alt_bmps["final"] = final_alts

        print(f"  Running {test_info['frames']} frames...")
        if not run_test(gba_path, test_info["frames"], output_bmp,
                        inputs=test_info.get("inputs", []),
                        screenshots=screenshots_args):
            return "ERROR"

        # Convert BMP to PNG
        output_png = tmpdir / f"{name}_final.png"
        Image.open(output_bmp).save(output_png)

        # Collect all screenshots to compare
        all_screenshots = [("final", output_png)]
        missing_screenshots = []
        for frame, bmp, ss_name in screenshot_bmps:
            if bmp.exists():
                png = tmpdir / f"{name}_{ss_name}.png"
                Image.open(bmp).save(png)
                all_screenshots.append((ss_name, png))
            else:
                # A screenshot scheduled at/after the run's frame count (or
                # otherwise never written by mgba_runner) used to be dropped
                # here silently, so the comparison against its baseline
                # never happened and the test still reported PASS.
                print(f"  {ss_name}: FAIL (screenshot at frame {frame} was never written)")
                missing_screenshots.append(ss_name)

        if rebaseline:
            if missing_screenshots:
                # Baselining a partial capture would bake in whatever the run
                # did manage to produce and drop the rest on the floor.
                print(f"  ERROR: not baselining a run that never wrote "
                      f"{', '.join(missing_screenshots)}")
                return "ERROR"

            BASELINE_DIR.mkdir(exist_ok=True)
            written = 0
            for ss_name, png in all_screenshots:
                baseline = BASELINE_DIR / f"{name}_{ss_name}.png"
                if rebaseline_screenshot(baseline, png):
                    written += 1
                    print(f"  Baseline saved: {baseline.name}")
                else:
                    print(f"  {ss_name}: unchanged, left alone")
            return "BASELINED" if written else "UNCHANGED"

        # Compare against baselines
        results = []
        for ss_name, png in all_screenshots:
            baseline = BASELINE_DIR / f"{name}_{ss_name}.png"
            if not baseline.exists():
                print(f"  WARNING: No baseline for {ss_name}. Run with --rebaseline first.")
                results.append("MISSING")
                continue

            ignore = test_info.get("ignore", {}).get(ss_name)
            match, diff_count, diff_img = compare_images(baseline, png, ignore=ignore)
            total_px = Image.open(png).size[0] * Image.open(png).size[1]

            # If the configured frame does not match, the baseline may simply
            # have slid a frame or two under a timing change.  Accept it if it
            # turns up anywhere in the window -- still an exact match, just not
            # necessarily at the exact host frame (#37).
            matched_offset = None
            if not match:
                for alt in alt_bmps.get(ss_name, []):
                    if not alt.exists():
                        continue
                    alt_png = tmpdir / (alt.stem + ".png")
                    Image.open(alt).save(alt_png)
                    alt_match, _, _ = compare_images(baseline, alt_png, ignore=ignore)
                    if alt_match:
                        match = True
                        matched_offset = alt.stem.split("alt")[-1]
                        break

            if match:
                if matched_offset is None:
                    print(f"  {ss_name}: PASS")
                else:
                    print(f"  {ss_name}: PASS (baseline found {matched_offset} "
                          f"frames away -- animation phase, not a rendering change)")
                results.append("PASS")
            else:
                pct = diff_count / total_px * 100
                print(f"  {ss_name}: FAIL ({diff_count} pixels differ, {pct:.1f}%)")
                results.append("FAIL")

                if diff_dir:
                    diff_path = Path(diff_dir)
                    diff_path.mkdir(exist_ok=True)
                    # Save actual, expected, and diff
                    Image.open(png).save(diff_path / f"{name}_{ss_name}_actual.png")
                    Image.open(baseline).save(diff_path / f"{name}_{ss_name}_expected.png")
                    if diff_img:
                        diff_img.save(diff_path / f"{name}_{ss_name}_diff.png")

                    # Create side-by-side comparison
                    actual = Image.open(png)
                    expected = Image.open(baseline)
                    w, h = actual.size
                    comparison = Image.new("RGB", (w * 3, h + 20), (40, 40, 40))
                    comparison.paste(expected, (0, 20))
                    comparison.paste(actual, (w, 20))
                    if diff_img:
                        comparison.paste(diff_img, (w * 2, 20))
                    draw = ImageDraw.Draw(comparison)
                    draw.text((5, 2), "Expected", fill=(255, 255, 255))
                    draw.text((w + 5, 2), "Actual", fill=(255, 255, 255))
                    draw.text((w * 2 + 5, 2), "Diff", fill=(255, 0, 0))
                    comparison.save(diff_path / f"{name}_{ss_name}_comparison.png")
                    print(f"  Diff saved to: {diff_path / f'{name}_{ss_name}_comparison.png'}")

        if missing_screenshots:
            results.append("FAIL")

        if "FAIL" in results:
            if test_info.get("expected_fail"):
                return "XFAIL"
            return "FAIL"
        if "MISSING" in results:
            return "MISSING"
        if test_info.get("expected_fail"):
            # Test is marked expected_fail but every screenshot matched its
            # baseline -- the underlying bug it exists to track was
            # apparently fixed. Flag it instead of silently reporting PASS,
            # so test_config.json gets updated rather than the regression
            # coverage quietly staying disabled forever.
            return "XPASS"
        return "PASS"


def main():
    parser = argparse.ArgumentParser(description="Automated visual regression testing for ChromA")
    parser.add_argument("--rebaseline", action="store_true", help="Generate new baseline images")
    parser.add_argument("--include-xfail", action="store_true",
                        help="With --rebaseline, also overwrite the baselines of "
                             "expected_fail tests. Those baselines are the record "
                             "of what the output should look like while a bug is "
                             "open, so this retires that record -- only pass it "
                             "when the bug is genuinely fixed and you are "
                             "updating test_config.json in the same change.")
    parser.add_argument("--test", "-t", action="append", help="Run specific test(s) by name")
    parser.add_argument("--diff-dir", "-d", default=None, help="Directory for diff images")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--list", "-l", action="store_true", help="List available tests")
    args = parser.parse_args()

    # Verify prerequisites
    if not RUNNER.exists():
        print(f"ERROR: mgba_runner not found at {RUNNER}")
        print("Build it with: make -f test_roms/Makefile.test")
        sys.exit(1)
    if not EMULATOR.exists():
        print(f"ERROR: chroma.gba not found at {EMULATOR}")
        print("Build it with: make")
        sys.exit(1)

    tests = discover_tests()

    if args.list:
        print("Available tests:")
        for name, info in sorted(tests.items()):
            baseline_exists = (BASELINE_DIR / f"{name}_final.png").exists()
            status = "has baseline" if baseline_exists else "no baseline"
            desc = f" - {info['description']}" if info['description'] else ""
            print(f"  {name} ({status}, {info['frames']} frames){desc}")
        return

    if not tests:
        print("No test ROMs found in test_roms/")
        return

    # Filter tests if --test specified
    if args.test:
        filtered = {}
        unknown = []
        for t in args.test:
            if t in tests:
                filtered[t] = tests[t]
            else:
                unknown.append(t)
                print(f"WARNING: Test '{t}' not found")
        tests = filtered
        if not tests:
            # A typo'd -t name used to fall through to the "no tests ran"
            # summary with an exit code of 0 -- silently running zero tests
            # instead of failing.
            print(f"ERROR: none of the requested tests exist: {', '.join(unknown)}")
            sys.exit(1)

    # Run tests
    results = {}
    for name in sorted(tests):
        result = run_single_test(name, tests[name],
                                 rebaseline=args.rebaseline,
                                 diff_dir=args.diff_dir,
                                 verbose=args.verbose,
                                 include_xfail=args.include_xfail)
        results[name] = result

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    passed = sum(1 for r in results.values() if r == "PASS")
    failed = sum(1 for r in results.values() if r == "FAIL")
    xfailed = sum(1 for r in results.values() if r == "XFAIL")
    xpassed = sum(1 for r in results.values() if r == "XPASS")
    missing = sum(1 for r in results.values() if r == "MISSING")
    errors = sum(1 for r in results.values() if r == "ERROR")
    baselined = sum(1 for r in results.values() if r == "BASELINED")
    unchanged = sum(1 for r in results.values() if r == "UNCHANGED")
    skipped = sum(1 for r in results.values() if r == "SKIPPED")

    for name, result in sorted(results.items()):
        status_char = {"PASS": ".", "FAIL": "F", "XFAIL": "x", "XPASS": "X",
                       "MISSING": "?", "ERROR": "E", "BASELINED": "B",
                       "UNCHANGED": "=", "SKIPPED": "-"}.get(result, "?")
        print(f"  [{status_char}] {name}: {result}")

    print()
    parts = []
    if passed: parts.append(f"{passed} passed")
    if failed: parts.append(f"{failed} FAILED")
    if xfailed: parts.append(f"{xfailed} expected failures")
    if xpassed: parts.append(f"{xpassed} UNEXPECTED PASSES")
    if missing: parts.append(f"{missing} missing baselines")
    if errors: parts.append(f"{errors} errors")
    if baselined: parts.append(f"{baselined} baselined")
    if unchanged: parts.append(f"{unchanged} already up to date")
    if skipped: parts.append(f"{skipped} skipped")
    print(", ".join(parts))

    if args.rebaseline:
        # Say plainly what was and was not touched.  The whole point of #99 is
        # that the operator should not have to reverse-engineer that from a
        # commit of N binary files.
        print()
        if baselined:
            print(f"Rewrote baselines for {baselined} test(s):")
            for name, r in sorted(results.items()):
                if r == "BASELINED":
                    print(f"  {name}")
        else:
            print("No baselines needed rewriting.")
        if skipped:
            print(f"\nLeft {skipped} expected_fail test(s) alone -- their "
                  f"baselines record what the output should look like while a "
                  f"known bug is open:")
            for name, r in sorted(results.items()):
                if r == "SKIPPED":
                    print(f"  {name}")
            print("Pass --include-xfail to rebaseline those too.")

    # MISSING baselines used to be excluded from the exit-code check entirely,
    # so tests with no baseline (verifying nothing) always reported success.
    # XPASS means a test config claims a known failure that no longer
    # reproduces -- that's a stale test_config.json entry, not a green build.
    sys.exit(1 if (failed or errors or missing or xpassed) else 0)


if __name__ == "__main__":
    main()
