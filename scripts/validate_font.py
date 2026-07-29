#!/usr/bin/env python3
"""Check the committed font assets against the C code that consumes them.

src/font.lz77 and src/fontpal.bin are binaries with no build step, so nothing
stopped them drifting away from src/pocketnes_text.{c,h} (#60).  This asserts
the invariants that drift would break, plus the LZ77UnCompVram displacement
constraint that emulators do not enforce but hardware does.

No toolchain, no emulator, no Pillow -- runs anywhere python3 does.
"""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import font_layout
import gba_lz77

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_LZ77 = os.path.join(REPO_ROOT, 'src', 'font.lz77')
FONT_PAL = os.path.join(REPO_ROOT, 'src', 'fontpal.bin')

TILE_BYTES = 32
PALETTE_ENTRIES = 16
PALETTES = 2          # normal + highlighted


def tile_pixels(tiles, index):
    """The 64 4bpp palette indices of one tile."""
    tile = tiles[index * TILE_BYTES:(index + 1) * TILE_BYTES]
    pixels = []
    for byte in tile:
        pixels.append(byte & 0x0F)
        pixels.append(byte >> 4)
    return pixels


def main():
    errors = []
    print('=== Font Asset Validation ===')

    try:
        layout = font_layout.load()
    except font_layout.LayoutError as exc:
        print('  FAIL: %s' % exc)
        return 1

    print('  Layout from src/: %d tiles, tile 0 = char %d, REDUCED_FONT=%d'
          % (layout['num_chars'], layout['first_char'], layout['reduced']))

    with open(FONT_LZ77, 'rb') as f:
        stream = f.read()
    with open(FONT_PAL, 'rb') as f:
        palette = f.read()

    # --- compressed stream -------------------------------------------------
    if len(stream) % 4:
        errors.append('font.lz77 is %d bytes; the BIOS reads the stream in '
                      '32-bit units so it must be a multiple of 4' % len(stream))

    try:
        tiles, min_disp = gba_lz77.decompress(stream)
    except ValueError as exc:
        print('  FAIL: font.lz77 does not decode: %s' % exc)
        return 1

    print('  font.lz77: %d bytes -> %d bytes (%d tiles), min displacement %s'
          % (len(stream), len(tiles), len(tiles) // TILE_BYTES, min_disp))

    if min_disp is not None and min_disp < gba_lz77.MIN_DISPLACEMENT:
        errors.append('font.lz77 contains a displacement-%d back-reference; '
                      'LZ77UnCompVram assembles two bytes per 16-bit VRAM '
                      'write and cannot resolve displacements below %d, so '
                      'glyphs corrupt on hardware. Re-run '
                      '`python3 scripts/generate_font.py --recompress`.'
                      % (min_disp, gba_lz77.MIN_DISPLACEMENT))

    if len(tiles) % 2:
        errors.append('decompressed font is %d bytes; LZ77UnCompVram writes '
                      'halfwords so it must be even' % len(tiles))

    if len(tiles) % TILE_BYTES:
        errors.append('decompressed font is %d bytes, not a whole number of '
                      '%d-byte tiles' % (len(tiles), TILE_BYTES))
    else:
        n_tiles = len(tiles) // TILE_BYTES
        if n_tiles != layout['num_chars']:
            errors.append('font.lz77 holds %d tiles but the C code indexes %d '
                          '(FONT_FIRSTCHAR=%d): every glyph from the mismatch '
                          'on renders as the wrong character'
                          % (n_tiles, layout['num_chars'],
                             layout['font_firstchar']))

    # --- tile content ------------------------------------------------------
    if len(tiles) >= TILE_BYTES:
        fill = font_layout.FONT_MEM_FIRSTCHAR
        if any(tile_pixels(tiles, fill)):
            errors.append('tile %d is not blank; cls() fills the tilemap with '
                          'it and lookup_character(\' \') resolves to it, so a '
                          'cleared screen would be painted with that glyph'
                          % fill)

    used = set()
    for byte in tiles:
        used.add(byte & 0x0F)
        used.add(byte >> 4)
    used.discard(0)
    print('  Tile data uses palette indices %s (0 = transparent)'
          % sorted(used))

    # --- palettes ----------------------------------------------------------
    expected_pal = PALETTES * PALETTE_ENTRIES * 2
    if len(palette) != expected_pal:
        errors.append('fontpal.bin is %d bytes; loadfontpal() copies %d '
                      '(%d palettes of %d colours)'
                      % (len(palette), expected_pal, PALETTES, PALETTE_ENTRIES))
    else:
        names = ('normal', 'highlight')
        for p in range(PALETTES):
            colours = struct.unpack_from('<%dH' % PALETTE_ENTRIES, palette,
                                         p * PALETTE_ENTRIES * 2)
            black = sorted(i for i in used if colours[i] == 0)
            if black:
                errors.append('%s palette leaves colour index %s black, but '
                              'the tile data draws with %s -- text is '
                              'invisible in that palette'
                              % (names[p], black, sorted(used)))
            print('  %-9s palette: %s' % (names[p],
                  ' '.join('%04X' % c for c in colours[:9])))

    if errors:
        for e in errors:
            print('  FAIL: %s' % e)
        return 1

    print('  All font asset constraints OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
