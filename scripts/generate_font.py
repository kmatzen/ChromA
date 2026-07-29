#!/usr/bin/env python3
"""Generate the GBA 4bpp menu font from a system font.

Outputs:
  src/font.lz77   LZ77-compressed 4bpp tile data, one 8x8 tile per slot
  src/fontpal.bin two 16-colour RGB555 palettes (normal, highlighted)

The tile layout is not chosen here -- it is read back out of the C code that
indexes it (see scripts/font_layout.py), because the two drifted apart once
before (#60).

Usage:
  python3 scripts/generate_font.py [font_name] [--bold]
  python3 scripts/generate_font.py "Monaco" --bold
  python3 scripts/generate_font.py --recompress   # keep the glyphs, redo LZ77
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

TILE_W, TILE_H = 8, 8
FONT_SIZE = 8

# Colour ramp tops, in RGB555.  Text is drawn with palette FONT_PALETTE_NUMBER
# and a highlighted row with the next palette up (pocketnes_text.c sets bit 12
# of the tilemap entry from bit 7 of the text byte), so fontpal.bin holds both
# and the highlight one must not be blank -- zero-padding it renders the
# selected menu row black on black.
NORMAL_TOP = 0x7FFF   # white
HILITE_TOP = 0x7FE0   # cyan
PALETTE_ENTRIES = 16
RAMP_LEVELS = 8       # palette indices 1..8; index 0 is transparent


def find_font(name=None, bold=False):
    """Try to load a font, falling back to defaults."""
    from PIL import ImageFont

    candidates = []
    if name:
        candidates.append(name)
    if bold:
        candidates += [
            "/System/Library/Fonts/SFCompact-Bold.otf",
            "/System/Library/Fonts/Menlo.ttc",
            "/System/Library/Fonts/Monaco.dfont",
        ]
    else:
        candidates += [
            "/System/Library/Fonts/SFCompact-Regular.otf",
            "/System/Library/Fonts/SFMono-Regular.otf",
            "/System/Library/Fonts/Menlo.ttc",
            "/System/Library/Fonts/Monaco.dfont",
        ]

    for path in candidates:
        try:
            return ImageFont.truetype(path, FONT_SIZE)
        except (OSError, IOError):
            continue

    return ImageFont.load_default()


def render_char(font, ch):
    """Render a single character to an 8x8 grayscale image."""
    from PIL import Image, ImageDraw

    img = Image.new('L', (TILE_W, TILE_H), 0)
    if ch == ' ':
        return img
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), ch, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = (TILE_W - w) // 2 - bbox[0]
    y = (TILE_H - h) // 2 - bbox[1]
    y = max(0, min(y, TILE_H - h))
    draw.text((x, y), ch, fill=255, font=font)
    return img


def img_to_4bpp_tile(img):
    """Convert an 8x8 grayscale image to 32 bytes of GBA 4bpp tile data."""
    pixels = list(img.getdata())
    tile = bytearray(32)
    for y in range(8):
        for x in range(0, 8, 2):
            idx = y * 8 + x
            # 0 is transparent; 1..RAMP_LEVELS run dark to bright.
            p0 = min(RAMP_LEVELS, pixels[idx] * (RAMP_LEVELS + 1) // 256)
            p1 = min(RAMP_LEVELS, pixels[idx + 1] * (RAMP_LEVELS + 1) // 256)
            tile[y * 4 + x // 2] = (p1 << 4) | p0
    return bytes(tile)


def _ramp(top):
    """Palette entries 0..15 ramping from transparent/black up to `top`."""
    r, g, b = top & 0x1F, (top >> 5) & 0x1F, (top >> 10) & 0x1F
    entries = [0x0000]
    for i in range(1, RAMP_LEVELS + 1):
        entries.append((r * i // RAMP_LEVELS)
                       | ((g * i // RAMP_LEVELS) << 5)
                       | ((b * i // RAMP_LEVELS) << 10))
    entries += [0x0000] * (PALETTE_ENTRIES - len(entries))
    return entries


def generate_palette():
    """Both 16-colour palettes, normal followed by highlighted."""
    pal = bytearray()
    for top in (NORMAL_TOP, HILITE_TOP):
        for entry in _ramp(top):
            pal.extend(struct.pack('<H', entry))
    return bytes(pal)


def render_tiles(layout, font):
    tile_data = bytearray()
    for ch in layout['tile_chars']:
        tile_data.extend(img_to_4bpp_tile(render_char(font, chr(ch))))
    return bytes(tile_data)


def save_preview(layout, font, path):
    from PIL import Image

    n = layout['num_chars']
    preview = Image.new('L', (n * TILE_W, TILE_H), 0)
    for i, ch in enumerate(layout['tile_chars']):
        preview.paste(render_char(font, chr(ch)), (i * TILE_W, 0))
    preview.resize((preview.width * 4, preview.height * 4),
                   Image.NEAREST).save(path)
    return path


def recompress():
    """Re-encode the committed tile data without touching the glyphs.

    The shipped stream was built by an encoder that emitted displacement-1
    back-references, which LZ77UnCompVram cannot decode (see gba_lz77.py).
    """
    with open(FONT_LZ77, 'rb') as f:
        old = f.read()
    tiles, old_min_disp = gba_lz77.decompress(old)
    new = gba_lz77.compress(tiles)
    roundtrip, new_min_disp = gba_lz77.decompress(new)
    if roundtrip != tiles:
        raise SystemExit('recompression changed the decoded tile data')

    print('Decoded %d bytes (%d tiles); min displacement %s -> %s'
          % (len(tiles), len(tiles) // 32, old_min_disp, new_min_disp))
    print('Stream %d -> %d bytes' % (len(old), len(new)))
    with open(FONT_LZ77, 'wb') as f:
        f.write(new)
    print('Wrote %s' % FONT_LZ77)


def main():
    argv = sys.argv[1:]
    if '--recompress' in argv:
        recompress()
        return

    bold = '--bold' in argv
    font_name = None
    for arg in argv:
        if not arg.startswith('-'):
            font_name = arg

    layout = font_layout.load()
    font = find_font(font_name, bold)
    name = ' '.join(font.getname()) if hasattr(font, 'getname') else 'default'
    print("Using font: %s" % name)
    print("Layout from src/: %d tiles, tile 0 = char %d"
          % (layout['num_chars'], layout['first_char']))

    tile_data = render_tiles(layout, font)
    print("Raw tile data: %d bytes (%d tiles)"
          % (len(tile_data), len(tile_data) // 32))

    compressed = gba_lz77.compress(tile_data)
    roundtrip, min_disp = gba_lz77.decompress(compressed)
    if roundtrip != tile_data:
        raise SystemExit('LZ77 round-trip mismatch -- refusing to write')
    print("LZ77 compressed: %d bytes (%d%%), min displacement %s"
          % (len(compressed), len(compressed) * 100 // len(tile_data), min_disp))

    with open(FONT_LZ77, 'wb') as f:
        f.write(compressed)
    print("Wrote %s" % FONT_LZ77)

    with open(FONT_PAL, 'wb') as f:
        f.write(generate_palette())
    print("Wrote %s" % FONT_PAL)

    print("Preview saved to %s"
          % save_preview(layout, font, '/tmp/font_preview.png'))


if __name__ == '__main__':
    main()
