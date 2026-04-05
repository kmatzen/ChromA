#!/usr/bin/env python3
"""Generate a GBA 4bpp font tileset from a system font.

Outputs:
  src/font.lz77  — LZ77-compressed 4bpp tile data (86 tiles, 8x8)
  src/fontpal.bin — 16-color palette (RGB555)

Usage:
  python3 scripts/generate_font.py [font_name] [--bold]
  python3 scripts/generate_font.py "Monaco" --bold
  python3 scripts/generate_font.py  # uses default
"""

import struct
import sys
from PIL import Image, ImageDraw, ImageFont

# Config
TILE_W, TILE_H = 8, 8
FIRST_CHAR = 32  # space
NUM_CHARS = 86   # space (32) through } (125) + extras
FONT_SIZE = 8

def find_font(name=None, bold=False):
    """Try to load a font, falling back to defaults."""
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

    # Final fallback
    return ImageFont.load_default()


def render_char(font, ch):
    """Render a single character to an 8x8 grayscale image."""
    img = Image.new('L', (TILE_W, TILE_H), 0)
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), ch, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = (TILE_W - w) // 2 - bbox[0]
    y = (TILE_H - h) // 2 - bbox[1]
    # Nudge down slightly for better visual centering
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
            # Map 0-255 grayscale to 0-8 palette index (0=transparent, 1-8=dark to bright)
            p0 = min(8, pixels[idx] * 9 // 256)
            p1 = min(8, pixels[idx + 1] * 9 // 256)
            tile[y * 4 + x // 2] = (p1 << 4) | p0
    return bytes(tile)


def lz77_compress(data):
    """Simple GBA-compatible LZ77 compression (type 0x10)."""
    src = data
    dst = bytearray()

    # Header: type 0x10 | (decompressed_size << 8)
    header = 0x10 | (len(src) << 8)
    dst.extend(struct.pack('<I', header))

    pos = 0
    while pos < len(src):
        flag_byte_pos = len(dst)
        dst.append(0)
        flags = 0

        for bit in range(8):
            if pos >= len(src):
                break

            # Try to find a match in the sliding window
            best_len = 0
            best_off = 0
            max_search = min(pos, 4096)
            max_match = min(len(src) - pos, 18)

            for off in range(1, max_search + 1):
                match_len = 0
                while match_len < max_match and src[pos + match_len] == src[pos - off + match_len]:
                    match_len += 1
                if match_len >= 3 and match_len > best_len:
                    best_len = match_len
                    best_off = off

            if best_len >= 3:
                flags |= (0x80 >> bit)
                # Encode: byte0 = ((len-3)<<4) | (off-1)>>8, byte1 = (off-1)&0xFF
                dst.append(((best_len - 3) << 4) | ((best_off - 1) >> 8))
                dst.append((best_off - 1) & 0xFF)
                pos += best_len
            else:
                dst.append(src[pos])
                pos += 1

        dst[flag_byte_pos] = flags

    # Pad to 4-byte alignment
    while len(dst) % 4:
        dst.append(0)

    return bytes(dst)


def generate_palette():
    """Generate a 16-color grayscale palette in RGB555 format."""
    pal = bytearray(32)  # 16 colors × 2 bytes
    # Color 0: transparent (dark blue for debug visibility)
    pal[0:2] = struct.pack('<H', 0x5800)
    # Colors 1-8: grayscale ramp from black to white
    for i in range(8):
        gray = int(i * 255 / 7)
        r5 = gray >> 3
        g5 = gray >> 3
        b5 = gray >> 3
        rgb555 = r5 | (g5 << 5) | (b5 << 10)
        pal[(i + 1) * 2:(i + 2) * 2] = struct.pack('<H', rgb555)
    # Colors 9-15: black (unused)
    # Pad to 64 bytes (full 16-color palette × 2 palettes for highlight)
    pal.extend(b'\x00' * (64 - len(pal)))
    return bytes(pal)


def main():
    bold = '--bold' in sys.argv
    font_name = None
    for arg in sys.argv[1:]:
        if not arg.startswith('-'):
            font_name = arg

    font = find_font(font_name, bold)
    print(f"Using font: {font.getname() if hasattr(font, 'getname') else 'default'}")
    print(f"Rendering {NUM_CHARS} characters ({FIRST_CHAR}-{FIRST_CHAR + NUM_CHARS - 1})...")

    # Render all characters
    tile_data = bytearray()
    for i in range(NUM_CHARS):
        ch = chr(FIRST_CHAR + i)
        img = render_char(font, ch)
        tile_data.extend(img_to_4bpp_tile(img))

    print(f"Raw tile data: {len(tile_data)} bytes ({NUM_CHARS} tiles)")

    # Compress
    compressed = lz77_compress(tile_data)
    print(f"LZ77 compressed: {len(compressed)} bytes ({len(compressed) * 100 // len(tile_data)}%)")

    # Write files
    with open('src/font.lz77', 'wb') as f:
        f.write(compressed)
    print(f"Wrote src/font.lz77")

    pal = generate_palette()
    with open('src/fontpal.bin', 'wb') as f:
        f.write(pal)
    print(f"Wrote src/fontpal.bin")

    # Preview: render all chars to a strip image
    preview = Image.new('L', (NUM_CHARS * TILE_W, TILE_H), 0)
    for i in range(NUM_CHARS):
        ch = chr(FIRST_CHAR + i)
        img = render_char(font, ch)
        preview.paste(img, (i * TILE_W, 0))
    preview_scaled = preview.resize((preview.width * 4, preview.height * 4), Image.NEAREST)
    preview_scaled.save('/tmp/font_preview.png')
    print(f"Preview saved to /tmp/font_preview.png")


if __name__ == '__main__':
    main()
