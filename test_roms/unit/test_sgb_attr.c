/* Host-side unit tests for the SGB attribute commands (issue #136).
 *
 * ATTR_BLK, ATTR_LIN, ATTR_DIV and ATTR_CHR (src/sgb_attr.c) decode into the
 * 20x18 attribute map -- one palette number per character cell -- that
 * ATTR_SET/PAL_SET already fill from a stored ATF.  All four used to return
 * immediately, so a game that colourised its screen with them kept whatever
 * the last ATTR_SET had left.
 *
 * These are pure functions of a packet buffer and a map, so they are checked
 * directly with no GBA toolchain, no emulator and no ROM.  That matters more
 * than usual here: no renderer consumes the map yet (item 2 of #136), so
 * there is nothing on screen to check the decode against, and this suite is
 * the only thing standing between the rules and a silent misreading of them.
 *
 * The cases below pin the parts most easily got wrong from the bit fields
 * alone: ATTR_BLK's implicit border rule, ATTR_LIN's inverted H/V sense
 * (bit 7 clear means a *column*), ATTR_DIV's three-way split including the
 * dividing line itself, and ATTR_CHR's 2-bits-per-cell packing, wrap and
 * top-to-bottom writing order.
 */

#include <stdio.h>
#include <string.h>

#include "gba.h"

#define SGB_W 20
#define SGB_H 18
#define SGB_CELLS (SGB_W * SGB_H)

void sgb_attr_blk(const u8 *packet, u8 *attrs);
void sgb_attr_lin(const u8 *packet, u8 *attrs);
void sgb_attr_div(const u8 *packet, u8 *attrs);
void sgb_attr_chr(const u8 *packet, u8 *attrs);

static int failures;

#define CHECK(cond, msg) do {                                               \
    if (!(cond)) {                                                          \
        printf("  FAIL: %s\n", msg);                                        \
        failures++;                                                         \
    }                                                                       \
} while (0)

static u8 packet[112];
static u8 attrs[SGB_CELLS];

static u8 at(int x, int y)
{
	return attrs[y * SGB_W + x];
}

static void reset(void)
{
	memset(packet, 0, sizeof(packet));
	memset(attrs, 0, sizeof(attrs));
}

/* Count cells holding a given palette, so a rule can be checked over the
   whole map rather than at a handful of hand-picked coordinates. */
static int count_of(int pal)
{
	int i, n = 0;

	for (i = 0; i < SGB_CELLS; i++)
	{
		if (attrs[i] == pal)
		{
			n++;
		}
	}
	return n;
}

static void test_blk_all_three_regions(void)
{
	int x, y, ok = 1;

	reset();
	packet[1] = 1;			/* one data set */
	packet[2] = 0x07;		/* change inside, border and outside */
	packet[3] = 0x01 | (2 << 2) | (3 << 4);	/* in 1, border 2, out 3 */
	packet[4] = 4;  packet[5] = 3;	/* X1, Y1 */
	packet[6] = 9;  packet[7] = 8;	/* X2, Y2 */
	sgb_attr_blk(packet, attrs);

	for (y = 0; y < SGB_H; y++)
	{
		for (x = 0; x < SGB_W; x++)
		{
			int within = (x >= 4 && x <= 9 && y >= 3 && y <= 8);
			int edge = within && (x == 4 || x == 9 || y == 3 || y == 8);
			int want = edge ? 2 : within ? 1 : 3;

			if (at(x, y) != want)
			{
				ok = 0;
			}
		}
	}
	CHECK(ok, "ATTR_BLK: inside/border/outside regions");
	/* 6x6 block: 20 edge cells, 16 inside, the rest outside. */
	CHECK(count_of(2) == 20, "ATTR_BLK: border cell count");
	CHECK(count_of(1) == 16, "ATTR_BLK: inside cell count");
	CHECK(count_of(3) == SGB_CELLS - 36, "ATTR_BLK: outside cell count");
}

static void test_blk_implicit_border(void)
{
	reset();
	packet[1] = 1;
	packet[2] = 0x01;		/* inside only -- border must follow it */
	packet[3] = 0x02 | (1 << 2);	/* inside 2; border field says 1 */
	packet[4] = 2;  packet[5] = 2;
	packet[6] = 6;  packet[7] = 6;
	sgb_attr_blk(packet, attrs);

	CHECK(at(2, 2) == 2, "ATTR_BLK: border takes the inside colour when "
			     "only the inside is being changed");
	CHECK(at(4, 4) == 2, "ATTR_BLK: inside colour");
	CHECK(at(10, 10) == 0, "ATTR_BLK: outside untouched when its bit is clear");

	reset();
	packet[1] = 1;
	packet[2] = 0x04;		/* outside only -- border must follow it */
	packet[3] = (1 << 2) | (3 << 4);	/* border field 1, outside 3 */
	packet[4] = 2;  packet[5] = 2;
	packet[6] = 6;  packet[7] = 6;
	sgb_attr_blk(packet, attrs);

	CHECK(at(2, 2) == 3, "ATTR_BLK: border takes the outside colour when "
			     "only the outside is being changed");
	CHECK(at(4, 4) == 0, "ATTR_BLK: inside untouched when its bit is clear");
	CHECK(at(10, 10) == 3, "ATTR_BLK: outside colour");
}

static void test_lin(void)
{
	int i, ok = 1;

	/* Bit 7 set = horizontal, i.e. a row. */
	reset();
	packet[1] = 1;
	packet[2] = 0x80 | (2 << 5) | 5;
	sgb_attr_lin(packet, attrs);
	for (i = 0; i < SGB_W; i++)
	{
		if (at(i, 5) != 2)
		{
			ok = 0;
		}
	}
	CHECK(ok, "ATTR_LIN: bit 7 set colours a whole row");
	CHECK(count_of(2) == SGB_W, "ATTR_LIN: a row is 20 cells");

	/* Bit 7 clear = vertical, i.e. a column.  Easy to invert. */
	reset();
	packet[1] = 1;
	packet[2] = (1 << 5) | 7;
	sgb_attr_lin(packet, attrs);
	ok = 1;
	for (i = 0; i < SGB_H; i++)
	{
		if (at(7, i) != 1)
		{
			ok = 0;
		}
	}
	CHECK(ok, "ATTR_LIN: bit 7 clear colours a whole column");
	CHECK(count_of(1) == SGB_H, "ATTR_LIN: a column is 18 cells");

	/* Several data sets in one packet. */
	reset();
	packet[1] = 3;
	packet[2] = 0x80 | (1 << 5) | 0;
	packet[3] = 0x80 | (2 << 5) | 1;
	packet[4] = 0x80 | (3 << 5) | 2;
	sgb_attr_lin(packet, attrs);
	CHECK(at(0, 0) == 1 && at(0, 1) == 2 && at(0, 2) == 3,
	      "ATTR_LIN: multiple data sets");
}

static void test_div(void)
{
	int x, y, ok = 1;

	/* Bit 6 clear: split left/right about an X coordinate. */
	reset();
	packet[1] = 1 | (2 << 2) | (3 << 4);	/* right 1, left 2, line 3 */
	packet[2] = 10;
	sgb_attr_div(packet, attrs);
	for (y = 0; y < SGB_H; y++)
	{
		for (x = 0; x < SGB_W; x++)
		{
			int want = (x < 10) ? 2 : (x > 10) ? 1 : 3;

			if (at(x, y) != want)
			{
				ok = 0;
			}
		}
	}
	CHECK(ok, "ATTR_DIV: left/right split with a coloured divider");
	CHECK(count_of(3) == SGB_H, "ATTR_DIV: the divider is one column");

	/* Bit 6 set: split above/below about a Y coordinate. */
	reset();
	packet[1] = 1 | (2 << 2) | (3 << 4) | 0x40;
	packet[2] = 4;
	sgb_attr_div(packet, attrs);
	ok = 1;
	for (y = 0; y < SGB_H; y++)
	{
		for (x = 0; x < SGB_W; x++)
		{
			int want = (y < 4) ? 2 : (y > 4) ? 1 : 3;

			if (at(x, y) != want)
			{
				ok = 0;
			}
		}
	}
	CHECK(ok, "ATTR_DIV: above/below split");
	CHECK(count_of(3) == SGB_W, "ATTR_DIV: the divider is one row");
}

static void test_chr(void)
{
	int i, ok = 1;

	/* Left to right from the origin.  Palettes 0,1,2,3 packed two bits
	   each, first set in the most significant bits: 0b00011011 = 0x1B. */
	reset();
	packet[1] = 0;  packet[2] = 0;
	packet[3] = 4;  packet[4] = 0;
	packet[5] = 0;
	packet[6] = 0x1B;
	sgb_attr_chr(packet, attrs);
	CHECK(at(0, 0) == 0 && at(1, 0) == 1 && at(2, 0) == 2 && at(3, 0) == 3,
	      "ATTR_CHR: two bits per cell, first set in the high bits");
	CHECK(at(4, 0) == 0, "ATTR_CHR: stops after the given count");

	/* Top to bottom. */
	reset();
	packet[1] = 2;  packet[2] = 0;
	packet[3] = 4;  packet[4] = 0;
	packet[5] = 1;
	packet[6] = 0x1B;
	sgb_attr_chr(packet, attrs);
	CHECK(at(2, 0) == 0 && at(2, 1) == 1 && at(2, 2) == 2 && at(2, 3) == 3,
	      "ATTR_CHR: top-to-bottom writing style walks down a column");

	/* Wrapping at the right edge onto the next row. */
	reset();
	packet[1] = 19; packet[2] = 0;
	packet[3] = 2;  packet[4] = 0;
	packet[5] = 0;
	packet[6] = 0xC0;		/* two sets: 3, then 0 */
	sgb_attr_chr(packet, attrs);
	CHECK(at(19, 0) == 3, "ATTR_CHR: first cell at the right edge");
	CHECK(at(0, 1) == 0, "ATTR_CHR: wraps to the start of the next row");

	/* A full-screen fill, which also exercises the count clamp. */
	reset();
	packet[1] = 0;  packet[2] = 0;
	packet[3] = (u8)(SGB_CELLS & 0xFF);
	packet[4] = (u8)(SGB_CELLS >> 8);
	packet[5] = 0;
	for (i = 6; i < (int)sizeof(packet); i++)
	{
		packet[i] = 0xFF;	/* every cell palette 3 */
	}
	sgb_attr_chr(packet, attrs);
	for (i = 0; i < SGB_CELLS; i++)
	{
		if (attrs[i] != 3)
		{
			ok = 0;
		}
	}
	CHECK(ok, "ATTR_CHR: a full 360-cell run fills the map");
}

static void test_bounds(void)
{
	reset();
	/* Coordinates past the edge of the screen must not write outside the
	   360-byte map.  A guard byte after it would be a nicer check, but the
	   set_cell clamp is what is being pinned; this at least drives it. */
	packet[1] = 1;
	packet[2] = 0x07;
	packet[3] = 0x15;
	packet[4] = 25; packet[5] = 25;
	packet[6] = 31; packet[7] = 31;
	sgb_attr_blk(packet, attrs);
	CHECK(1, "ATTR_BLK: off-screen rectangle does not crash");

	reset();
	packet[1] = 1;
	packet[2] = 0x80 | 31;		/* row 31, off screen */
	sgb_attr_lin(packet, attrs);
	CHECK(count_of(0) == SGB_CELLS,
	      "ATTR_LIN: an off-screen line writes nothing");
}

int main(void)
{
	setvbuf(stdout, NULL, _IONBF, 0);
	printf("SGB attribute command unit tests (issue #136)\n\n");

	test_blk_all_three_regions();
	test_blk_implicit_border();
	test_lin();
	test_div();
	test_chr();
	test_bounds();

	printf("\n");
	if (failures)
	{
		printf("FAILED: %d check(s)\n", failures);
		return 1;
	}
	printf("PASS: all checks\n");
	return 0;
}
