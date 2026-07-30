#!/usr/bin/env python3
"""Unit tests for test_roms/goomba_compile.py (issue #60 item 3).

The script appends a GB ROM to chroma.gba.  The emulator finds that ROM with a
32-bit load at `textstart + 0x104`, so the append point has to be 4-byte
aligned; on ARM7 an unaligned `ldr` rotates rather than faults, so getting this
wrong produces a cart that boots to "No ROM found!" and says nothing else.
There was no alignment step and no size limit.

Host-native: no toolchain, no emulator, no real ROM.

Run: python3 test_roms/test_goomba_compile.py
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import goomba_compile as gc


def make_rom(size=gc.MIN_ROM_BYTES, logo=True, title=b"TESTROM"):
    rom = bytearray(size)
    if logo:
        rom[0x104:0x108] = gc.GB_LOGO_PREFIX
    rom[0x134:0x134 + len(title)] = title
    return bytes(rom)


class GoombaCompileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, emulator_bytes, rom_bytes, **kw):
        emu = self.dir / "chroma.gba"
        rom = self.dir / "game.gb"
        out = self.dir / "combined.gba"
        emu.write_bytes(emulator_bytes)
        rom.write_bytes(rom_bytes)
        gc.build_goomba_rom(emu, rom, out, **kw)
        return out.read_bytes()

    # ------------------------------------------------------------ alignment
    def test_aligned_emulator_is_not_padded(self):
        emu = b"\xAA" * 1024              # already a multiple of 4
        rom = make_rom()
        out = self.build(emu, rom)
        self.assertEqual(len(out), len(emu) + len(rom))
        self.assertEqual(out[1024:1024 + len(rom)], rom)

    def test_unaligned_emulator_is_padded_to_four(self):
        for extra in (1, 2, 3):
            with self.subTest(extra=extra):
                emu = b"\xAA" * (1024 + extra)
                rom = make_rom()
                out = self.build(emu, rom)
                start = gc.align_up(len(emu), 4)
                self.assertEqual(start % 4, 0)
                self.assertEqual(out[start:start + len(rom)], rom)

    def test_header_word_lands_on_an_aligned_address(self):
        # This is the property main.c actually depends on.
        emu = b"\xAA" * 1023
        out = self.build(emu, make_rom())
        start = gc.align_up(1023, 4)
        self.assertEqual((start + 0x104) % 4, 0)
        self.assertEqual(out[start + 0x104:start + 0x108], gc.GB_LOGO_PREFIX)

    def test_align_up(self):
        self.assertEqual(gc.align_up(0, 4), 0)
        self.assertEqual(gc.align_up(1, 4), 4)
        self.assertEqual(gc.align_up(4, 4), 4)
        self.assertEqual(gc.align_up(5, 4), 8)

    # ----------------------------------------------------------- size limit
    def test_rejects_an_image_over_the_cart_window(self):
        emu = b"\xAA" * 1024
        rom = make_rom(size=gc.MAX_CART_BYTES)
        with self.assertRaises(gc.BuildError) as ctx:
            self.build(emu, rom)
        self.assertIn("32 MB", str(ctx.exception))

    def test_accepts_an_image_exactly_at_the_limit(self):
        emu = b"\xAA" * 1024
        rom = make_rom(size=gc.MAX_CART_BYTES - 1024)
        out = self.build(emu, rom)
        self.assertEqual(len(out), gc.MAX_CART_BYTES)

    # -------------------------------------------------------- ROM sanity
    def test_rejects_a_file_with_no_gb_header(self):
        with self.assertRaises(gc.BuildError) as ctx:
            self.build(b"\xAA" * 1024, make_rom(logo=False))
        self.assertIn("header logo", str(ctx.exception))

    def test_rejects_a_file_too_small_to_be_a_cartridge(self):
        with self.assertRaises(gc.BuildError) as ctx:
            self.build(b"\xAA" * 1024, make_rom(size=1024))
        self.assertIn("bytes", str(ctx.exception))

    def test_force_builds_anyway(self):
        out = self.build(b"\xAA" * 1024, make_rom(logo=False), force=True)
        self.assertEqual(len(out), 1024 + gc.MIN_ROM_BYTES)

    def test_missing_inputs_raise(self):
        with self.assertRaises(FileNotFoundError):
            gc.build_goomba_rom(self.dir / "nope.gba", self.dir / "nope.gb",
                                self.dir / "out.gba")

    # ------------------------------------------------- the real built image
    def test_built_chroma_gba_is_already_aligned(self):
        """The browser demo appends the guest ROM straight after chroma.gba
        with no padding step of its own, so the built image has to end on a
        4-byte boundary by construction.  It does today; this fails if a
        future linker or asset change makes it stop."""
        repo = Path(__file__).resolve().parent.parent
        for candidate in (repo / "chroma.gba", Path.cwd() / "chroma.gba"):
            if candidate.exists():
                size = candidate.stat().st_size
                self.assertEqual(
                    size % gc.APPEND_ALIGNMENT, 0,
                    "%s is %d bytes, not a multiple of %d -- the guest ROM "
                    "header would be read unaligned" %
                    (candidate, size, gc.APPEND_ALIGNMENT))
                return
        self.skipTest("chroma.gba not built here")


if __name__ == "__main__":
    unittest.main(verbosity=2)
