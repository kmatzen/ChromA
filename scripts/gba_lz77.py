"""GBA BIOS LZ77 (compression type 0x10) codec.

Shared by scripts/generate_font.py and scripts/validate_font.py.

The only subtlety here is MIN_DISPLACEMENT.  src/pocketnes_text.c decompresses
the font with LZ77UnCompVram (SWI 0x12), which assembles two decoded bytes at a
time and writes them to VRAM as one halfword, because VRAM cannot be written a
byte at a time.  A back-reference with displacement 1 points at the byte
immediately behind the write cursor -- which is still sitting in that unflushed
halfword rather than in VRAM -- so the BIOS reads a stale byte and the glyph
comes out corrupted.  Emulators that decompress through a plain byte buffer
(mGBA among them) do not reproduce this, so it only shows up on hardware.

Encoders must therefore never emit a displacement below 2 for VRAM targets.
"""

import struct

LZ77_TYPE = 0x10
MIN_DISPLACEMENT = 2      # 1 is unsafe for LZ77UnCompVram -- see above
MAX_DISPLACEMENT = 4096
MIN_MATCH = 3
MAX_MATCH = 18


def compress(data, min_displacement=MIN_DISPLACEMENT):
    """Compress to GBA LZ77 type 0x10, VRAM-safe by default."""
    src = bytes(data)
    dst = bytearray()
    dst.extend(struct.pack('<I', LZ77_TYPE | (len(src) << 8)))

    pos = 0
    while pos < len(src):
        flag_pos = len(dst)
        dst.append(0)
        flags = 0

        for bit in range(8):
            if pos >= len(src):
                break

            best_len = 0
            best_off = 0
            max_search = min(pos, MAX_DISPLACEMENT)
            max_match = min(len(src) - pos, MAX_MATCH)

            # Offsets below min_displacement are skipped rather than clamped:
            # a run that could only be encoded as displacement 1 is emitted as
            # literals instead.
            for off in range(min_displacement, max_search + 1):
                match_len = 0
                while (match_len < max_match
                       and src[pos + match_len] == src[pos - off + match_len]):
                    match_len += 1
                if match_len >= MIN_MATCH and match_len > best_len:
                    best_len = match_len
                    best_off = off

            if best_len >= MIN_MATCH:
                flags |= (0x80 >> bit)
                dst.append(((best_len - MIN_MATCH) << 4) | ((best_off - 1) >> 8))
                dst.append((best_off - 1) & 0xFF)
                pos += best_len
            else:
                dst.append(src[pos])
                pos += 1

        dst[flag_pos] = flags

    # The BIOS reads the stream in 32-bit units.
    while len(dst) % 4:
        dst.append(0)

    return bytes(dst)


def decompress(blob):
    """Decode a type 0x10 stream.

    Returns (data, min_displacement_seen).  min_displacement_seen is None when
    the stream contains no back-references at all.
    """
    if len(blob) < 4:
        raise ValueError('stream is shorter than its 4-byte header')

    header = struct.unpack('<I', blob[:4])[0]
    if header & 0xFF != LZ77_TYPE:
        raise ValueError('not LZ77 type 0x10 (header byte 0x%02X)' % (header & 0xFF))
    size = header >> 8

    out = bytearray()
    pos = 4
    min_disp = None

    while len(out) < size:
        if pos >= len(blob):
            raise ValueError('stream ran out %d bytes short of the declared %d'
                             % (size - len(out), size))
        flags = blob[pos]
        pos += 1
        for bit in range(8):
            if len(out) >= size:
                break
            if flags & (0x80 >> bit):
                if pos + 1 >= len(blob):
                    raise ValueError('truncated back-reference')
                b0, b1 = blob[pos], blob[pos + 1]
                pos += 2
                length = (b0 >> 4) + MIN_MATCH
                off = (((b0 & 0x0F) << 8) | b1) + 1
                if off > len(out):
                    raise ValueError('back-reference %d reaches before the '
                                     'start of the output' % off)
                min_disp = off if min_disp is None else min(min_disp, off)
                for _ in range(length):
                    out.append(out[len(out) - off])
            else:
                if pos >= len(blob):
                    raise ValueError('truncated literal')
                out.append(blob[pos])
                pos += 1

    return bytes(out[:size]), min_disp
