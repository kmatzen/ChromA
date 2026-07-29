"""Derive the font tile layout from the C source that consumes it.

The generator and the committed assets drifted apart once already (#60): the
generator laid tiles out for characters 32..117 while the C code indexes them
as `character - 42`, so regenerating the font shifted every glyph by ten
slots.  Rather than restate the layout as constants that can drift again, both
scripts/generate_font.py and scripts/validate_font.py read it back out of
src/pocketnes_text.{c,h} and src/config.h.  If the C side is edited into a
shape this cannot parse, that is itself the drift signal -- fix both together.
"""

import os
import re

SRC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')

# The tilemap fill value in cls() and the FILL_PATTERN in pocketnes_text.c.
FONT_MEM_FIRSTCHAR = 0


class LayoutError(Exception):
    pass


def _read(src_dir, name):
    try:
        with open(os.path.join(src_dir, name), 'r') as f:
            return f.read()
    except IOError as exc:
        raise LayoutError('cannot read src/%s: %s' % (name, exc))


def _reduced_font(src_dir):
    m = re.search(r'^\s*#define\s+REDUCED_FONT\s+(\d+)', _read(src_dir, 'config.h'), re.M)
    if not m:
        raise LayoutError('no #define REDUCED_FONT in src/config.h')
    return int(m.group(1)) != 0


def _font_firstchar(src_dir, reduced):
    text = _read(src_dir, 'pocketnes_text.h')
    # Two #defines guarded by #if REDUCED_FONT / #else; take them in order.
    values = re.findall(r'^\s*#define\s+FONT_FIRSTCHAR\s+\(?([^)\n]+)\)?', text, re.M)
    if len(values) != 2:
        raise LayoutError('expected two FONT_FIRSTCHAR #defines in '
                          'src/pocketnes_text.h, found %d' % len(values))
    expr = values[0] if reduced else values[1]
    try:
        return int(eval(expr.strip(), {'__builtins__': {}}, {}))
    except Exception:
        raise LayoutError('cannot evaluate FONT_FIRSTCHAR expression %r' % expr)


def _c_char_literal(token):
    token = token.strip()
    if re.match(r'^\d+$', token):
        return int(token)
    m = re.match(r"^'(\\.|[^'])'$", token)
    if not m:
        raise LayoutError('unparsable char_lookup_1 entry %r' % token)
    body = m.group(1)
    if body.startswith('\\'):
        escapes = {'\\\\': 92, "\\'": 39, '\\"': 34, '\\n': 10, '\\t': 9, '\\0': 0}
        if body not in escapes:
            raise LayoutError('unhandled escape %r in char_lookup_1' % body)
        return escapes[body]
    return ord(body)


def _char_lookup(src_dir):
    text = _read(src_dir, 'pocketnes_text.c')
    # The table contains a literal '}', so the initialiser has to be closed on
    # "} ;" rather than on the first closing brace.
    m = re.search(r'char_lookup_1\s*\[\s*\]\s*=\s*\{(.*?)\}\s*;', text, re.S)
    if not m:
        raise LayoutError('no char_lookup_1 table in src/pocketnes_text.c')
    tokens = re.findall(r"'(?:\\.|[^'])'|\d+", m.group(1))
    if not tokens:
        raise LayoutError('char_lookup_1 initialiser is empty')
    return [_c_char_literal(t) for t in tokens]


def load(src_dir=SRC_DIR):
    """Return the tile layout the C code expects.

    Keys:
      first_char   nominal character of tile 0
      num_chars    number of tiles in the tileset
      tile_chars   per-tile character whose glyph must be rendered there
      substitutes  {rendered_char: tile} for the REDUCED_FONT aliases
    """
    reduced = _reduced_font(src_dir)
    font_firstchar = _font_firstchar(src_dir, reduced)

    # lookup_character(c) == c - 32 + FONT_FIRSTCHAR, so tile t holds char
    # t + 32 - FONT_FIRSTCHAR and tile 0 is the first character in the set.
    first_char = 32 - font_firstchar
    num_chars = 128 - first_char
    if not 0 < num_chars <= 128:
        raise LayoutError('FONT_FIRSTCHAR %d implies %d tiles'
                          % (font_firstchar, num_chars))

    tile_chars = [first_char + t for t in range(num_chars)]
    substitutes = {}

    if reduced:
        # Characters below '+' have no tile of their own; lookup_character maps
        # each to the slot of a rarely-used glyph that resembles it closely
        # enough ('!' -> '|', '(' -> '{', ...), so those slots keep their own
        # nominal glyph.  Exactly two of the aliases are not interchangeable
        # and the substituted character has to win the slot instead:
        #
        #   ' ' -> '*'  cls() fills the tilemap with tile FONT_MEM_FIRSTCHAR and
        #               lookup_character(' ') resolves to that same tile, so it
        #               must be blank rather than an asterisk.
        #   '*' -> 127  127 is unprintable, so the slot it lends to '*' is the
        #               only place an asterisk can live.
        table = _char_lookup(src_dir)
        for i, sub in enumerate(table):
            rendered = 32 + i
            tile = sub - first_char
            if not 0 <= tile < num_chars:
                raise LayoutError('char_lookup_1[%d] = %d maps outside the '
                                  'tileset' % (i, sub))
            substitutes[rendered] = tile

        space_tile = substitutes.get(ord(' '))
        if space_tile != FONT_MEM_FIRSTCHAR:
            raise LayoutError("' ' maps to tile %r but cls() fills with tile %d"
                              % (space_tile, FONT_MEM_FIRSTCHAR))
        tile_chars[space_tile] = ord(' ')

        star_tile = substitutes.get(ord('*'))
        if star_tile is None:
            raise LayoutError("'*' has no slot in char_lookup_1")
        tile_chars[star_tile] = ord('*')

    return {
        'reduced': reduced,
        'font_firstchar': font_firstchar,
        'first_char': first_char,
        'num_chars': num_chars,
        'tile_chars': tile_chars,
        'substitutes': substitutes,
    }
