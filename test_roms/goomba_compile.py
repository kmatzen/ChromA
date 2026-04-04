#!/usr/bin/env python3

import argparse
from pathlib import Path


def build_goomba_rom(emulator_path: Path, rom_path: Path, output_path: Path):
    if not emulator_path.exists():
        raise FileNotFoundError(f"Missing emulator: {emulator_path}")
    if not rom_path.exists():
        raise FileNotFoundError(f"Missing ROM: {rom_path}")

    combined = bytearray(emulator_path.read_bytes())
    print(f"  -> {rom_path.name}")
    combined += rom_path.read_bytes()

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "wb") as f:
        f.write(combined)

    print(f"Built: {output_path}")
    print(f"Size: {output_path.stat().st_size} bytes")


def main():
    parser = argparse.ArgumentParser(description="Goomba ROM builder")

    parser.add_argument(
        "-e", "--emulator",
        required=True,
        help="Path to chroma.gba"
    )

    parser.add_argument(
        "-o", "--output",
        required=True,
        help="Output GBA file"
    )

    parser.add_argument(
        "rom",
        help="GB/GBC ROM"
    )

    args = parser.parse_args()

    build_goomba_rom(
        Path(args.emulator),
        Path(args.rom),
        Path(args.output)
    )


if __name__ == "__main__":
    main()
