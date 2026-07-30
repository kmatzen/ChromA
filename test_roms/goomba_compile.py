#!/usr/bin/env python3
"""Append a GB/GBC ROM to chroma.gba to make a bootable cartridge image.

The emulator locates the guest ROM by reading a 32-bit word at `textstart +
0x104` and comparing it with the Nintendo logo magic (src/main.c).  `textstart`
is the first byte after the emulator image, so if that image does not end on a
4-byte boundary the load is unaligned -- and on ARM7 an unaligned `ldr` returns
a *rotated* word rather than faulting, so the comparison fails and the cart
boots to "No ROM found!" with nothing to indicate why.  chroma.gba happens to
be a multiple of 4 today; nothing enforced it, and nothing warned (#60).

This script now pads to the alignment the emulator requires, refuses to build
an image larger than the GBA's 32 MB cartridge window, and checks that the file
being appended actually looks like a Game Boy ROM.
"""

import argparse
from pathlib import Path

# main.c reads `*(u32*)(textstart + 0x104)`, so the append point must be
# 4-byte aligned for that load to be well-defined.
APPEND_ALIGNMENT = 4

# GBA cartridge address space is 0x08000000-0x09FFFFFF.
MAX_CART_BYTES = 32 * 1024 * 1024

# First four bytes of the Nintendo logo at 0x104 in every GB cart header; this
# is the value main.c compares against (0x6666edce, read little-endian).
GB_LOGO_PREFIX = bytes([0xCE, 0xED, 0x66, 0x66])

MIN_ROM_BYTES = 32 * 1024


def align_up(n, alignment):
    return (n + alignment - 1) // alignment * alignment


def check_rom(data):
    """Reasons `data` is not a usable GB ROM, as a list of phrases."""
    problems = []
    if len(data) < MIN_ROM_BYTES:
        problems.append("only %d bytes (smallest GB cartridge is %d)"
                        % (len(data), MIN_ROM_BYTES))
    if data[0x104:0x108] != GB_LOGO_PREFIX:
        problems.append("no Game Boy header logo at 0x104 (found %s, expected %s)"
                        % (data[0x104:0x108].hex(), GB_LOGO_PREFIX.hex()))
    return problems


class BuildError(Exception):
    """A build that would produce an image the hardware cannot run."""


def build_goomba_rom(emulator_path: Path, rom_path: Path, output_path: Path,
                     force: bool = False):
    if not emulator_path.exists():
        raise FileNotFoundError(f"Missing emulator: {emulator_path}")
    if not rom_path.exists():
        raise FileNotFoundError(f"Missing ROM: {rom_path}")

    emulator = emulator_path.read_bytes()
    rom = rom_path.read_bytes()

    problems = check_rom(rom)
    if problems:
        msg = "%s does not look like a Game Boy ROM: %s" % (
            rom_path.name, "; ".join(problems))
        if not force:
            raise BuildError(msg + " (pass --force to build anyway)")
        print("warning: " + msg)

    padding = align_up(len(emulator), APPEND_ALIGNMENT) - len(emulator)
    if padding:
        print("  padding emulator by %d byte(s) to a %d-byte boundary"
              % (padding, APPEND_ALIGNMENT))

    combined = bytearray(emulator)
    combined += b"\x00" * padding
    print(f"  -> {rom_path.name}")
    combined += rom

    if len(combined) > MAX_CART_BYTES:
        raise BuildError(
            "combined image is %.1f MB, over the GBA's %d MB cartridge window "
            "-- it would not be addressable on hardware"
            % (len(combined) / (1024 * 1024), MAX_CART_BYTES // (1024 * 1024)))

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "wb") as f:
        f.write(combined)

    print(f"Built: {output_path}")
    print("Size: %d bytes (%.2f MB of %d MB)"
          % (output_path.stat().st_size, len(combined) / (1024 * 1024),
             MAX_CART_BYTES // (1024 * 1024)))
    return len(combined)


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
        "--force",
        action="store_true",
        help="Build even if the ROM fails its header check"
    )

    parser.add_argument(
        "rom",
        help="GB/GBC ROM"
    )

    args = parser.parse_args()

    try:
        build_goomba_rom(
            Path(args.emulator),
            Path(args.rom),
            Path(args.output),
            force=args.force,
        )
    except BuildError as exc:
        raise SystemExit("error: %s" % exc)


if __name__ == "__main__":
    main()
