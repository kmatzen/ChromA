#!/usr/bin/env python3
"""Guards --rebaseline's own filtering (issue #99).

`run_tests.py --rebaseline` used to rewrite every baseline it could produce.
Two things went wrong with that:

  - expected_fail baselines were overwritten too.  Such a baseline is the
    reference for what the output is SUPPOSED to look like while a bug is
    open, so replacing it with the current output makes the broken rendering
    the new truth and silently retires the bug -- Cannon Fodder's baselines
    document #36.
  - baselines whose pixels had not changed were rewritten anyway, because
    re-encoding a pixel-identical capture still produces different PNG bytes.
    7 of the 20 files in the #97 rebaseline and 2 of the 29 in #100 were that.

Both meant the operator got a commit full of binary files with no signal about
which were safe to keep, and had to cross-reference the CI log by hand.

Host-side: no toolchain, no emulator, no ROMs -- just Pillow, so this runs on
every push rather than only in test-full.
"""

import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow is required. Install with: pip3 install Pillow")
    sys.exit(2)

import run_tests

failures = []


def check(cond, what):
    if cond:
        print(f"  PASS: {what}")
    else:
        print(f"  FAIL: {what}")
        failures.append(what)


def solid(path, colour, size=(8, 8)):
    Image.new("RGB", size, colour).save(path)


def main():
    print("=" * 60)
    print("expected_fail tests are excluded from --rebaseline")
    print("=" * 60)

    xfail = {"expected_fail": True}
    normal = {"expected_fail": False}

    check(run_tests.skip_rebaseline_reason(xfail) is not None,
          "an expected_fail test is skipped by default")
    check(run_tests.skip_rebaseline_reason(normal) is None,
          "an ordinary test is not skipped")
    check(run_tests.skip_rebaseline_reason(xfail, include_xfail=True) is None,
          "--include-xfail overrides the skip")
    check(run_tests.skip_rebaseline_reason({}) is None,
          "a test with no expected_fail key is not skipped")

    reason = run_tests.skip_rebaseline_reason(xfail) or ""
    check("expected_fail" in reason and "bug" in reason,
          "the skip reason explains itself rather than just saying 'skipped'")

    print()
    print("=" * 60)
    print("only baselines whose pixels changed are rewritten")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # A capture identical to the baseline must not be written, even though
        # re-encoding it would produce different bytes on disk.  The baseline
        # is deliberately stored with a different compression level so that
        # re-saving it WOULD change the file -- that is the real situation,
        # where baselines committed by an older Pillow re-encode differently
        # today despite identical pixels.
        baseline = tmp / "same.png"
        capture = tmp / "same_new.png"
        Image.new("RGB", (64, 64), (10, 20, 30)).save(baseline, compress_level=0)
        Image.new("RGB", (64, 64), (10, 20, 30)).save(capture, compress_level=9)
        before = baseline.read_bytes()
        check(before != capture.read_bytes(),
              "the fixture really does differ on disk while matching in pixels")
        wrote = run_tests.rebaseline_screenshot(baseline, capture)
        check(wrote is False, "a pixel-identical capture reports no write")
        check(baseline.read_bytes() == before,
              "a pixel-identical capture leaves the file byte-for-byte alone")

        # A capture that differs must be written.
        baseline = tmp / "diff.png"
        capture = tmp / "diff_new.png"
        solid(baseline, (10, 20, 30))
        solid(capture, (200, 20, 30))
        wrote = run_tests.rebaseline_screenshot(baseline, capture)
        check(wrote is True, "a changed capture reports a write")
        check(Image.open(baseline).convert("RGB").getpixel((0, 0)) == (200, 20, 30),
              "a changed capture actually lands on disk")

        # A single differing pixel still counts: the comparison is exact, so
        # "unchanged" must not quietly absorb a real regression.
        baseline = tmp / "onepx.png"
        capture = tmp / "onepx_new.png"
        solid(baseline, (0, 0, 0))
        img = Image.new("RGB", (8, 8), (0, 0, 0))
        img.putpixel((3, 3), (0, 0, 1))
        img.save(capture)
        check(run_tests.rebaseline_screenshot(baseline, capture) is True,
              "a one-pixel, one-level difference still counts as changed")

        # A baseline that does not exist yet must be created.
        baseline = tmp / "brand_new.png"
        capture = tmp / "brand_new_src.png"
        solid(capture, (1, 2, 3))
        check(run_tests.rebaseline_screenshot(baseline, capture) is True
              and baseline.exists(),
              "a missing baseline is created")

    print()
    print("=" * 60)
    if failures:
        print(f"{len(failures)} check(s) FAILED:")
        for f in failures:
            print(f"  {f}")
        print("\n--rebaseline must not touch expected_fail baselines or "
              "rewrite unchanged ones (#99)")
        sys.exit(1)
    print("PASS: --rebaseline skips expected_fail tests and only rewrites "
          "baselines whose pixels actually changed")
    sys.exit(0)


if __name__ == "__main__":
    main()
