#!/usr/bin/env python3
"""Self-checks for the accuracy suite's own config and reference screens.

Host-native: no toolchain, no emulator, no ROM download, so this runs on every
push and PR even when the accuracy suite itself cannot.

This guards the failure mode the rest of the harness has repeatedly hit
(#58, #59, #99): a suite that still exits 0 while silently verifying nothing.
An entry whose reference screen is missing, the wrong size, or orphaned from
any test would otherwise only surface as a MISSING deep in a CI log.
"""

import json
import re
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow is required. Install with: pip3 install Pillow")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).parent
CONFIG = SCRIPT_DIR / "accuracy_config.json"
BASELINE_DIR = SCRIPT_DIR / "baselines" / "accuracy"

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
    return cond


def baseline_name(tag):
    return tag.replace("/", "__") + ".png"


def main():
    check(CONFIG.exists(), f"{CONFIG} is missing")
    if failures:
        print(failures[0])
        return 1
    cfg = json.loads(CONFIG.read_text())

    # --- rom_pack pin -------------------------------------------------------
    pack = cfg.get("rom_pack", {})
    for k in ("version", "url", "sha256"):
        check(k in pack and pack[k], f"rom_pack.{k} is missing or empty")
    if "sha256" in pack:
        check(re.fullmatch(r"[0-9a-f]{64}", pack["sha256"] or "") is not None,
              f"rom_pack.sha256 is not a 64-char lowercase hex digest: "
              f"{pack.get('sha256')!r}")
    if "url" in pack and "version" in pack:
        check(pack["version"] in pack["url"],
              f"rom_pack.url does not mention the pinned version "
              f"{pack['version']} -- the pin and the download would disagree")

    # --- geometry -----------------------------------------------------------
    geom = cfg.get("geometry", {})
    for name, frame_w, frame_h in (("chroma_crop", 240, 160),
                                   ("native_crop", 256, 224)):
        box = geom.get(name)
        if not check(isinstance(box, list) and len(box) == 4,
                     f"geometry.{name} must be [x0,y0,x1,y1]"):
            continue
        x0, y0, x1, y1 = box
        check((x1 - x0, y1 - y0) == (160, 144),
              f"geometry.{name} does not select a 160x144 Game Boy screen: "
              f"got {x1-x0}x{y1-y0}")
        check(0 <= x0 and 0 <= y0 and x1 <= frame_w and y1 <= frame_h,
              f"geometry.{name} {box} falls outside the {frame_w}x{frame_h} frame")

    tests = cfg.get("tests", {})
    unusable = cfg.get("unusable", {})
    check(bool(tests), "accuracy_config.json lists no tests")

    # --- no tag counted twice ----------------------------------------------
    both = set(tests) & set(unusable)
    check(not both, f"tags appear in both tests and unusable: {sorted(both)}")

    # --- rom paths are distinct --------------------------------------------
    seen = {}
    for tag, info in tests.items():
        rom = info.get("rom")
        if check(bool(rom), f"{tag}: no 'rom' path"):
            check(rom not in seen,
                  f"{tag} and {seen.get(rom)} both point at {rom}")
            seen[rom] = tag
        check(isinstance(info.get("frames"), int) and info["frames"] > 0,
              f"{tag}: 'frames' must be a positive integer")
        check(isinstance(info.get("expected_fail"), bool),
              f"{tag}: 'expected_fail' must be present and boolean")
        # A tag is derived from the rom path, so a mismatch means the baseline
        # filename and the ROM would drift apart.
        if rom:
            check(tag == rom[:-3] if rom.endswith(".gb") else tag == rom,
                  f"{tag}: tag does not match rom path {rom}")

    for tag, info in unusable.items():
        check(bool(info.get("reason", "").strip()),
              f"unusable/{tag}: needs a non-empty reason")

    # --- every test has a usable reference screen ---------------------------
    expected_files = set()
    for tag in tests:
        name = baseline_name(tag)
        expected_files.add(name)
        p = BASELINE_DIR / name
        if not check(p.exists(), f"{tag}: reference screen {name} is missing"):
            continue
        with Image.open(p) as im:
            check(im.size == (160, 144),
                  f"{tag}: reference {name} is {im.size}, expected (160, 144)")

    # --- no orphan references ----------------------------------------------
    if BASELINE_DIR.exists():
        for p in sorted(BASELINE_DIR.glob("*.png")):
            check(p.name in expected_files,
                  f"{p.name} has no entry in accuracy_config.json -- either a "
                  f"stale reference or a test that was dropped")

    n_xfail = sum(1 for i in tests.values() if i.get("expected_fail"))
    if failures:
        print(f"FAIL: {len(failures)} problem(s) in the accuracy suite config\n")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"PASS: accuracy suite config is consistent")
    print(f"  {len(tests)} tests ({len(tests) - n_xfail} passing, {n_xfail} expected-fail)")
    print(f"  {len(unusable)} unusable ROMs recorded with reasons")
    print(f"  {len(expected_files)} reference screens, all 160x144, no orphans")
    print(f"  ROM pack pinned at {pack['version']} ({pack['sha256'][:16]}...)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
