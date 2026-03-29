#!/usr/bin/env python3
"""Automated visual regression testing for jagoombacolor.

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
EMULATOR = PROJECT_DIR / "jagoombacolor.gba"
BASELINE_DIR = SCRIPT_DIR / "baselines"
TEST_CONFIG = SCRIPT_DIR / "test_config.json"


def load_test_config():
    """Load test configuration from JSON file."""
    if not TEST_CONFIG.exists():
        return {}
    with open(TEST_CONFIG) as f:
        return json.load(f)


def compile_test_rom(rom_path, output_path):
    """Wrap a GB/GBC ROM with jagoombacolor using goomba_compile.py."""
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


def compare_images(img_a_path, img_b_path, threshold=0):
    """Compare two images. Returns (match, diff_count, diff_image)."""
    img_a = Image.open(img_a_path).convert("RGB")
    img_b = Image.open(img_b_path).convert("RGB")

    if img_a.size != img_b.size:
        return False, -1, None

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


def discover_tests():
    """Find all test ROMs and their configurations."""
    config = load_test_config()
    tests = {}

    # Find all .gb and .gbc files in test_roms/
    for ext in ["*.gb", "*.gbc"]:
        for rom in SCRIPT_DIR.glob(ext):
            name = rom.stem
            test_cfg = config.get(name, {})
            tests[name] = {
                "rom": rom,
                "frames": test_cfg.get("frames", 7200),
                "inputs": test_cfg.get("inputs", []),
                "screenshots": test_cfg.get("screenshots", []),
                "description": test_cfg.get("description", ""),
                "expected_fail": test_cfg.get("expected_fail", False),
            }

    return tests


def run_single_test(name, test_info, rebaseline=False, diff_dir=None, verbose=False):
    """Run a single test and compare against baseline."""
    print(f"\n{'='*60}")
    print(f"Test: {name}")
    if test_info["description"]:
        print(f"  {test_info['description']}")
    print(f"  ROM: {test_info['rom'].name}")
    print(f"  Frames: {test_info['frames']}")

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
        for ss in test_info.get("screenshots", []):
            ss_bmp = tmpdir / f"{name}_{ss['frame']}.bmp"
            screenshots_args.append(f"{ss['frame']}:{ss_bmp}")
            screenshot_bmps.append((ss["frame"], ss_bmp, ss.get("name", f"frame_{ss['frame']}")))

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
        for frame, bmp, ss_name in screenshot_bmps:
            if bmp.exists():
                png = tmpdir / f"{name}_{ss_name}.png"
                Image.open(bmp).save(png)
                all_screenshots.append((ss_name, png))

        if rebaseline:
            # Save as new baselines
            BASELINE_DIR.mkdir(exist_ok=True)
            for ss_name, png in all_screenshots:
                baseline = BASELINE_DIR / f"{name}_{ss_name}.png"
                Image.open(png).save(baseline)
                print(f"  Baseline saved: {baseline.name}")
            return "BASELINED"

        # Compare against baselines
        results = []
        for ss_name, png in all_screenshots:
            baseline = BASELINE_DIR / f"{name}_{ss_name}.png"
            if not baseline.exists():
                print(f"  WARNING: No baseline for {ss_name}. Run with --rebaseline first.")
                results.append("MISSING")
                continue

            match, diff_count, diff_img = compare_images(baseline, png)
            total = Image.open(png).size[0] * Image.open(png).size[1]

            if match:
                print(f"  {ss_name}: PASS")
                results.append("PASS")
            else:
                pct = diff_count / total * 100
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

        if "FAIL" in results:
            return "XFAIL" if test_info.get("expected_fail") else "FAIL"
        if "MISSING" in results:
            return "MISSING"
        return "PASS"


def main():
    parser = argparse.ArgumentParser(description="Automated visual regression testing for jagoombacolor")
    parser.add_argument("--rebaseline", action="store_true", help="Generate new baseline images")
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
        print(f"ERROR: jagoombacolor.gba not found at {EMULATOR}")
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
        for t in args.test:
            if t in tests:
                filtered[t] = tests[t]
            else:
                print(f"WARNING: Test '{t}' not found")
        tests = filtered

    # Run tests
    results = {}
    for name in sorted(tests):
        result = run_single_test(name, tests[name],
                                 rebaseline=args.rebaseline,
                                 diff_dir=args.diff_dir,
                                 verbose=args.verbose)
        results[name] = result

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    passed = sum(1 for r in results.values() if r == "PASS")
    failed = sum(1 for r in results.values() if r == "FAIL")
    xfailed = sum(1 for r in results.values() if r == "XFAIL")
    missing = sum(1 for r in results.values() if r == "MISSING")
    errors = sum(1 for r in results.values() if r == "ERROR")
    baselined = sum(1 for r in results.values() if r == "BASELINED")

    for name, result in sorted(results.items()):
        status_char = {"PASS": ".", "FAIL": "F", "XFAIL": "x", "MISSING": "?",
                       "ERROR": "E", "BASELINED": "B"}.get(result, "?")
        print(f"  [{status_char}] {name}: {result}")

    print()
    parts = []
    if passed: parts.append(f"{passed} passed")
    if failed: parts.append(f"{failed} FAILED")
    if xfailed: parts.append(f"{xfailed} expected failures")
    if missing: parts.append(f"{missing} missing baselines")
    if errors: parts.append(f"{errors} errors")
    if baselined: parts.append(f"{baselined} baselined")
    print(", ".join(parts))

    sys.exit(1 if failed or errors else 0)


if __name__ == "__main__":
    main()
