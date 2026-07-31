#!/usr/bin/env python3
"""Compare two emulator builds capture-for-capture, without using baselines.

The visual suite answers "does this build match the stored baselines?", which
is the wrong question when you are changing rendering on purpose, and an
actively misleading one on a machine where some baselines already fail for
environmental reasons.  This answers "what does this change actually move?"
by running both builds over the same ROMs and diffing their own output.

Two regressions this session came from not having it:

  * A DMG-only sprite change moved 70 pixels of a CGB game's frame.  The
    sprite data was identical; an added stmfd/ldmfd pair on the per-frame
    path was enough, because this renderer runs against a real-time VCOUNT
    budget.  Only a direct build-to-build comparison shows that.

  * A window-latch change reported 0 pixels across six games and then failed
    CI at 37%.  The hand-rolled check compared the first two screenshots of
    each game; the damage was on later captures.  Hence --all-captures being
    the default and not an option.

Usage:
    python3 test_roms/compare_builds.py BASE.gba HEAD.gba
    python3 test_roms/compare_builds.py BASE.gba HEAD.gba --only POKEMON --only ZELDA
    python3 test_roms/compare_builds.py BASE.gba HEAD.gba --diff-dir /tmp/d

Exit status is 1 if any capture differs, so it can gate a change directly.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

SCRIPT_DIR = Path(__file__).parent
RUNNER = SCRIPT_DIR / "mgba_runner"
COMPILER = SCRIPT_DIR / "goomba_compile.py"
CONFIG = SCRIPT_DIR / "test_config.json"

ROM_EXTENSIONS = (".gb", ".gbc")
DEFAULT_FRAMES = 3000


def find_rom(name):
    for ext in ROM_EXTENSIONS:
        path = SCRIPT_DIR / (name + ext)
        if path.exists():
            return path
    return None


def capture(emulator, rom, entry, outdir, tag):
    """Run one ROM under one build, writing every configured screenshot."""
    gba = outdir / f"{tag}.gba"
    r = subprocess.run(
        [sys.executable, str(COMPILER), "-e", str(emulator),
         "-o", str(gba), str(rom)],
        capture_output=True, text=True)
    if r.returncode != 0:
        return None, f"compile failed: {r.stderr.strip()[:200]}"

    frames = entry.get("frames", DEFAULT_FRAMES)
    # A ROM with no configured screenshots gets one at the last frame it
    # actually reaches.  Asking for frame == the run length is rejected by the
    # runner ("it would never be captured"), which turned every such entry
    # into an error rather than a comparison.
    shots = entry.get("screenshots") or [{"frame": max(frames - 1, 0),
                                          "name": "final"}]
    cmd = [str(RUNNER), str(gba), str(frames), "/dev/null"]
    for spec in entry.get("inputs", []):
        cmd += ["--input", spec]
    paths = {}
    for shot in shots:
        p = outdir / f"{tag}_{shot['name']}.bmp"
        paths[shot["name"]] = p
        cmd += ["--screenshot", f"{shot['frame']}:{p}"]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return None, "runner timed out"
    if r.returncode != 0:
        return None, f"runner exited {r.returncode}: {r.stderr.strip()[:200]}"
    return paths, None


def diff_images(a, b):
    ia = Image.open(a).convert("RGB")
    ib = Image.open(b).convert("RGB")
    if ia.size != ib.size:
        raise ValueError(f"size mismatch: {ia.size} vs {ib.size}")
    n = sum(1 for x, y in zip(ia.getdata(), ib.getdata()) if x != y)
    return n, n / (ia.size[0] * ia.size[1]) * 100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base", help="emulator build to compare against")
    ap.add_argument("head", help="emulator build under test")
    ap.add_argument("--only", action="append", default=[],
                    help="substring filter on ROM name; repeatable")
    ap.add_argument("--diff-dir",
                    help="write the differing capture pairs here")
    args = ap.parse_args()

    base, head = Path(args.base), Path(args.head)
    for p in (base, head, RUNNER, COMPILER, CONFIG):
        if not p.exists():
            print(f"ERROR: {p} not found")
            sys.exit(2)

    config = json.load(open(CONFIG, encoding="utf-8"))
    diff_dir = Path(args.diff_dir) if args.diff_dir else None
    if diff_dir:
        diff_dir.mkdir(parents=True, exist_ok=True)

    moved, checked, skipped, errors = [], 0, [], []

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        for name in sorted(config):
            entry = config[name]
            if not isinstance(entry, dict):
                continue
            if args.only and not any(f.lower() in name.lower()
                                     for f in args.only):
                continue
            rom = find_rom(name)
            if rom is None:
                skipped.append(name)
                continue

            a_paths, err = capture(base, rom, entry, td, "base")
            if err:
                errors.append(f"{name}: base {err}")
                continue
            b_paths, err = capture(head, rom, entry, td, "head")
            if err:
                errors.append(f"{name}: head {err}")
                continue

            worst = None
            for shot in sorted(a_paths):
                if not (a_paths[shot].exists() and b_paths[shot].exists()):
                    errors.append(f"{name}: capture '{shot}' missing")
                    continue
                checked += 1
                n, pct = diff_images(a_paths[shot], b_paths[shot])
                if n:
                    moved.append((name, shot, n, pct))
                    if worst is None or n > worst[0]:
                        worst = (n, shot)
                    if diff_dir:
                        for side, paths in (("base", a_paths),
                                            ("head", b_paths)):
                            dest = diff_dir / f"{name}_{shot}_{side}.bmp"
                            dest.write_bytes(paths[shot].read_bytes())
            status = ("identical" if worst is None
                      else f"MOVED  worst {worst[0]} px in '{worst[1]}'")
            print(f"  {name[:46]:48s} {status}")

    print()
    print(f"{checked} captures compared; "
          f"{len({m[0] for m in moved})} ROM(s) moved")
    if skipped:
        print(f"skipped (ROM not present): {len(skipped)}")
    for e in errors:
        print(f"ERROR: {e}")

    if moved:
        print()
        print("Captures that moved:")
        for name, shot, n, pct in sorted(moved, key=lambda m: -m[2]):
            print(f"  {n:7d} px ({pct:5.2f}%)  {name} :: {shot}")
        print()
        print("A change that is meant to be invisible has failed here.  A "
              "change that is meant to alter rendering should be judged on "
              "exactly this list.")
        sys.exit(1)

    if errors:
        sys.exit(2)
    print()
    print("PASS: the two builds render every compared capture identically")


if __name__ == "__main__":
    main()
