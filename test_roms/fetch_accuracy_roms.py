#!/usr/bin/env python3
"""Download the pinned hardware-accuracy test ROM pack.

Usage:
    python3 test_roms/fetch_accuracy_roms.py            # download + extract
    python3 test_roms/fetch_accuracy_roms.py --check    # verify only, no download

The pack is https://github.com/c-sp/gameboy-test-roms, which redistributes
Blargg's test roms, the Mooneye Test Suite and others as prebuilt binaries.
Unlike the commercial game ROMs in test-roms-private, these are freely
redistributable, so this runs in the public `test` CI job with no secrets --
which is the whole point: accuracy coverage on every PR rather than only
after merge.

The release tag *and* the archive SHA-256 are pinned in accuracy_config.json.
The pin is deliberate for the same reason MGBA_PIN is: the baselines in
baselines/accuracy/ are the reference screens produced by these exact ROM
binaries, so a floating "latest" would silently invalidate them.
"""

import argparse
import hashlib
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONFIG = SCRIPT_DIR / "accuracy_config.json"
ROM_DIR = SCRIPT_DIR / "accuracy_roms"
CHUNK = 1 << 16


def load_pack():
    with open(CONFIG) as f:
        return json.load(f)["rom_pack"]


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest):
    print(f"Downloading {url}")
    with urllib.request.urlopen(url) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    print(f"  {dest.stat().st_size} bytes")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="Only report whether the ROMs are already extracted")
    ap.add_argument("--force", action="store_true",
                    help="Re-download and re-extract even if present")
    args = ap.parse_args()

    pack = load_pack()
    marker = ROM_DIR / ".version"
    have = marker.exists() and marker.read_text().strip() == pack["version"]

    if args.check:
        print(f"accuracy ROMs {pack['version']}: "
              f"{'present' if have else 'NOT present'} at {ROM_DIR}")
        return 0 if have else 1

    if have and not args.force:
        print(f"accuracy ROMs {pack['version']} already extracted at {ROM_DIR}")
        return 0

    archive = SCRIPT_DIR / f"game-boy-test-roms-{pack['version']}.zip"
    if not archive.exists() or args.force:
        download(pack["url"], archive)

    digest = sha256_of(archive)
    if digest != pack["sha256"]:
        # Refuse rather than extract: a changed archive means the reference
        # screens in baselines/accuracy/ no longer describe these ROMs.
        print(f"ERROR: SHA-256 mismatch for {archive.name}")
        print(f"  expected {pack['sha256']}")
        print(f"  got      {digest}")
        archive.unlink()
        return 1
    print(f"SHA-256 OK: {digest}")

    if ROM_DIR.exists():
        shutil.rmtree(ROM_DIR)
    ROM_DIR.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        z.extractall(ROM_DIR)
    marker.write_text(pack["version"] + "\n")
    archive.unlink()

    n = sum(1 for _ in ROM_DIR.rglob("*.gb")) + sum(1 for _ in ROM_DIR.rglob("*.gbc"))
    print(f"Extracted {n} ROMs to {ROM_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
