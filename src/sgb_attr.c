/* SGB attribute commands: ATTR_BLK, ATTR_LIN, ATTR_DIV, ATTR_CHR (#136).
 *
 * These four decode into the 20x18 attribute map -- one palette number per
 * character cell -- that ATTR_SET/PAL_SET already fill from a stored ATF.
 * All four returned immediately (src/sgb.s), so a game that colourised its
 * screen with them got whatever the last ATTR_SET left behind, which for most
 * titles is nothing at all.
 *
 * Written in C rather than in sgb.s for the reason the other decoders here
 * are: the rules are fiddly (three regions and an implicit border rule in
 * ATTR_BLK alone), they are pure functions of a packet buffer, and that makes
 * them checkable on the host without a GBA toolchain, an emulator or a ROM.
 * The caller passes the attribute map in, so nothing here needs the GBA's
 * absolute addresses.
 *
 * Command layouts are from the Pan Docs / gbdev SGB documentation.  Only the
 * decode is implemented: no renderer consumes the map yet, which is item 2 of
 * #136 and a much larger change.  Nothing here can therefore change what is
 * drawn -- but it is not free.  Running the decode costs one capture of
 * Pokemon Yellow, an SGB title that actually sends these commands, 1.26% of
 * its Game Freak intro; inspected, and it is the Pikachu animation at a
 * different frame of its cycle, not corruption.  Stubbing the four functions
 * out while leaving the sgb.s wiring in place moves nothing, which is what
 * pins the cost to the decode itself rather than to code placement.
 */

#include "gba.h"

#define SGB_W 20
#define SGB_H 18
#define SGB_CELLS (SGB_W * SGB_H)

static void set_cell(u8 *attrs, int x, int y, int pal)
{
	if (x < 0 || x >= SGB_W || y < 0 || y >= SGB_H)
	{
		return;
	}
	attrs[y * SGB_W + x] = (u8)(pal & 3);
}

/* 04h ATTR_BLK -- colour the inside, border and outside of rectangles.
 *
 * packet[1] is the number of 6-byte data sets (01h..12h).  Each set is:
 *   [0] control code: bit 0 change inside, bit 1 change border,
 *                     bit 2 change outside
 *   [1] palettes:     bits 0-1 inside, 2-3 border, 4-5 outside
 *   [2..5]            X1, Y1, X2, Y2
 *
 * The border is the ring of cells on the rectangle's own edges.  When only
 * the inside or only the outside is being changed, the border takes that same
 * colour -- an explicit rule in the documentation, not an inference, and the
 * thing most likely to be got wrong by reading the bit fields alone.
 */
void sgb_attr_blk(const u8 *packet, u8 *attrs)
{
	int sets = packet[1] & 0x1F;
	const u8 *d = packet + 2;
	int s, x, y;

	if (sets > 0x12)
	{
		sets = 0x12;
	}

	for (s = 0; s < sets; s++, d += 6)
	{
		int ctrl = d[0] & 7;
		int pal_in = d[1] & 3;
		int pal_line = (d[1] >> 2) & 3;
		int pal_out = (d[1] >> 4) & 3;
		int x1 = d[2] & 0x1F, y1 = d[3] & 0x1F;
		int x2 = d[4] & 0x1F, y2 = d[5] & 0x1F;
		int do_in = ctrl & 1, do_line = ctrl & 2, do_out = ctrl & 4;

		if (!do_line)
		{
			if (do_in && !do_out)
			{
				pal_line = pal_in;
				do_line = 1;
			}
			else if (do_out && !do_in)
			{
				pal_line = pal_out;
				do_line = 1;
			}
		}

		/* Only the outside case has to walk the whole map; the other
		   two are bounded by the rectangle.  That matters: a packet may
		   carry 18 data sets, and scanning all 360 cells for each of
		   them was enough to move a Pokemon Yellow capture by 1.26%
		   through cost alone, on a renderer that runs against a
		   real-time VCOUNT budget. */
		if (do_out)
		{
			for (y = 0; y < SGB_H; y++)
			{
				for (x = 0; x < SGB_W; x++)
				{
					if (x < x1 || x > x2 || y < y1 || y > y2)
					{
						set_cell(attrs, x, y, pal_out);
					}
				}
			}
		}

		if (do_in)
		{
			for (y = y1 + 1; y < y2; y++)
			{
				for (x = x1 + 1; x < x2; x++)
				{
					set_cell(attrs, x, y, pal_in);
				}
			}
		}

		if (do_line)
		{
			for (x = x1; x <= x2; x++)
			{
				set_cell(attrs, x, y1, pal_line);
				set_cell(attrs, x, y2, pal_line);
			}
			for (y = y1; y <= y2; y++)
			{
				set_cell(attrs, x1, y, pal_line);
				set_cell(attrs, x2, y, pal_line);
			}
		}
	}
}

/* 05h ATTR_LIN -- colour whole character rows or columns.
 *
 * packet[1] is the number of one-byte data sets (01h..6Eh).  Each byte:
 *   bits 0-4  line number
 *   bits 5-6  palette
 *   bit 7     0 = vertical (a column), 1 = horizontal (a row)
 */
void sgb_attr_lin(const u8 *packet, u8 *attrs)
{
	int sets = packet[1];
	const u8 *d = packet + 2;
	int s, i;

	if (sets > 0x6E)
	{
		sets = 0x6E;
	}

	for (s = 0; s < sets; s++)
	{
		u8 v = d[s];
		int line = v & 0x1F;
		int pal = (v >> 5) & 3;

		if (v & 0x80)
		{
			for (i = 0; i < SGB_W; i++)
			{
				set_cell(attrs, i, line, pal);
			}
		}
		else
		{
			for (i = 0; i < SGB_H; i++)
			{
				set_cell(attrs, line, i, pal);
			}
		}
	}
}

/* 06h ATTR_DIV -- split the screen in two and colour both halves plus the
 * dividing line.  A single data set:
 *   packet[1] bits 0-1 palette below/right, 2-3 above/left, 4-5 the line,
 *             bit 6 0 = split left/right, 1 = split above/below
 *   packet[2] the X or Y coordinate of the dividing line
 */
void sgb_attr_div(const u8 *packet, u8 *attrs)
{
	int below = packet[1] & 3;
	int above = (packet[1] >> 2) & 3;
	int on_line = (packet[1] >> 4) & 3;
	int horizontal = packet[1] & 0x40;
	int coord = packet[2] & 0x1F;
	int x, y;

	for (y = 0; y < SGB_H; y++)
	{
		for (x = 0; x < SGB_W; x++)
		{
			int c = horizontal ? y : x;
			int pal = (c < coord) ? above : (c > coord) ? below
								    : on_line;
			set_cell(attrs, x, y, pal);
		}
	}
}

/* 07h ATTR_CHR -- colour individual characters in sequence.
 *
 *   packet[1]   starting X
 *   packet[2]   starting Y
 *   packet[3-4] number of data sets, little-endian (1..360)
 *   packet[5]   writing style: 0 = left to right, 1 = top to bottom
 *   packet[6..] two bits per character, first set in the most significant
 *               bits of each byte
 *
 * The walk wraps to the next row (or column) at the edge of the screen.
 */
void sgb_attr_chr(const u8 *packet, u8 *attrs)
{
	int x = packet[1] & 0x1F;
	int y = packet[2] & 0x1F;
	int count = packet[3] | (packet[4] << 8);
	int vertical = packet[5] & 1;
	const u8 *d = packet + 6;
	int i;

	if (count > SGB_CELLS)
	{
		count = SGB_CELLS;
	}
	if (x >= SGB_W)
	{
		x = 0;
	}
	if (y >= SGB_H)
	{
		y = 0;
	}

	for (i = 0; i < count; i++)
	{
		int pal = (d[i >> 2] >> (6 - 2 * (i & 3))) & 3;

		set_cell(attrs, x, y, pal);

		if (vertical)
		{
			if (++y >= SGB_H)
			{
				y = 0;
				if (++x >= SGB_W)
				{
					x = 0;
				}
			}
		}
		else
		{
			if (++x >= SGB_W)
			{
				x = 0;
				if (++y >= SGB_H)
				{
					y = 0;
				}
			}
		}
	}
}
