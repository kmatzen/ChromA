#!/usr/bin/env python3

import argparse
from pathlib import Path


def build_goomba_rom(emulator_path: Path, rom_paths: list[Path], output_path: Path):
    if not emulator_path.exists():
        raise FileNotFoundError(f"Missing emulator: {emulator_path}")

    emulator_data = emulator_path.read_bytes()

    combined = bytearray(emulator_data)

    print(f"Adding {len(rom_paths)} ROM(s)...")

    for rom in rom_paths:
        if not rom.exists():
            raise FileNotFoundError(f"Missing ROM: {rom}")

        print(f"  -> {rom.name}")
        combined += rom.read_bytes()

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "wb") as f:
        f.write(combined)

    print(f"Built: {output_path}")
    print(f"Size: {output_path.stat().st_size} bytes")


def main():
    parser = argparse.ArgumentParser(description="Simple Goomba ROM builder (concat mode)")

    parser.add_argument(
        "-e", "--emulator",
        required=True,
        help="Path to jagoombacolor.gba"
    )

    parser.add_argument(
        "-o", "--output",
        required=True,
        help="Output GBA file"
    )

    parser.add_argument(
        "roms",
        nargs="+",
        help="GB/GBC ROM(s)"
    )

    args = parser.parse_args()

    build_goomba_rom(
        Path(args.emulator),
        [Path(r) for r in args.roms],
        Path(args.output)
    )


if __name__ == "__main__":
    main()
