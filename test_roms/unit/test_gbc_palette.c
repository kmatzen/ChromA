/* Host-side unit tests for the CGB boot-palette licensee gate (issue #154).
 *
 * GetGbcPaletteNumber() (src/gbcgamedetect.c) consulted the title-hash table
 * for every cart.  The table is keyed on a one-byte checksum of the 16-byte
 * title, so third-party titles collide with Nintendo ones -- Mega Man - Dr.
 * Wily's Revenge was picking up palette 88 that way.  Hardware never hits
 * those collisions because the CGB boot ROM checks the licensee before it
 * looks anything up:
 *
 *	old licensee ($014B) == $33	->  new licensee ($0144-45) must be "01"
 *	otherwise			->  old licensee must be $01
 *
 * Anything else takes the boot ROM's .useDefaultIndex path, which is palette
 * 0.  These tests pin both halves of that condition, and pin that the gate is
 * the *only* thing that changed: a cart that passes it still resolves to
 * exactly the palette the ungated lookup produced.
 *
 * No GBA toolchain, mGBA build or ROM needed -- it compiles
 * src/gbcgamedetect.c with the host compiler and calls the function directly.
 */

#include <stdio.h>
#include <string.h>

#include "gba.h"

int GetGbcPaletteNumber(u8 *rom);

static int failures;

#define CHECK(cond, msg) do {                                               \
    if (!(cond)) {                                                          \
        printf("  FAIL: %s\n", msg);                                        \
        failures++;                                                         \
    }                                                                       \
} while (0)

/* Only the header matters, but the function indexes up to 0x014B. */
static u8 rom[0x0200];

static void reset_header(void)
{
	memset(rom, 0, sizeof(rom));
}

/* The 16 title bytes at 0x0134 are what the hash is computed over. */
static void set_title(const char *title)
{
	size_t i;

	for (i = 0; i < 16; i++)
	{
		rom[0x0134 + i] = (u8)(i < strlen(title) ? title[i] : 0);
	}
}

static void set_old_licensee(u8 code)
{
	rom[0x014B] = code;
}

static void set_new_licensee(char a, char b)
{
	rom[0x0144] = (u8)a;
	rom[0x0145] = (u8)b;
}

/* A title whose checksum hits the table, so the gate is observable: with the
   gate open it returns non-zero, with the gate shut it returns 0.  Rather than
   hand-picking a title, search for one -- a single byte swept over the first
   title character is enough to find a hashing entry, and this stays valid if
   the table is ever regenerated. */
static int find_hashing_title(char *out)
{
	int c;

	for (c = 'A'; c <= 'Z'; c++)
	{
		reset_header();
		set_old_licensee(0x01);
		out[0] = (char)c;
		out[1] = '\0';
		set_title(out);
		if (GetGbcPaletteNumber(rom) != 0)
		{
			return 1;
		}
	}
	return 0;
}

int main(void)
{
	char title[2];
	int ungated;

	setvbuf(stdout, NULL, _IONBF, 0);
	printf("CGB boot-palette licensee gate unit tests (issue #154)\n\n");

	if (!find_hashing_title(title))
	{
		printf("  FAIL: no single-letter title hits the hash table\n");
		printf("\nFAILED: 1 check(s)\n");
		return 1;
	}
	printf("  using title \"%s\" (hits the hash table)\n", title);

	/* Old licensee $01 is Nintendo directly. */
	reset_header();
	set_title(title);
	set_old_licensee(0x01);
	ungated = GetGbcPaletteNumber(rom);
	CHECK(ungated != 0, "old licensee $01 should keep its palette");

	/* $33 defers to the new licensee, which must be ASCII "01". */
	reset_header();
	set_title(title);
	set_old_licensee(0x33);
	set_new_licensee('0', '1');
	CHECK(GetGbcPaletteNumber(rom) == ungated,
	      "old $33 + new \"01\" should resolve to the same palette");

	/* $33 with any other new licensee is not Nintendo. */
	reset_header();
	set_title(title);
	set_old_licensee(0x33);
	set_new_licensee('0', '8');
	CHECK(GetGbcPaletteNumber(rom) == 0,
	      "old $33 + new \"08\" (Capcom) should get palette 0");

	reset_header();
	set_title(title);
	set_old_licensee(0x33);
	set_new_licensee('1', '1');
	CHECK(GetGbcPaletteNumber(rom) == 0,
	      "old $33 + new \"11\" should get palette 0");

	/* The new licensee is only consulted when the old one is $33: a cart
	   with old licensee $08 does not get in by carrying "01" as well. */
	reset_header();
	set_title(title);
	set_old_licensee(0x08);
	set_new_licensee('0', '1');
	CHECK(GetGbcPaletteNumber(rom) == 0,
	      "old $08 should get palette 0 even with new licensee \"01\"");

	/* Mega Man - Dr. Wily's Revenge: old licensee $08, Capcom.  The bug. */
	reset_header();
	set_title(title);
	set_old_licensee(0x08);
	CHECK(GetGbcPaletteNumber(rom) == 0,
	      "old licensee $08 (Capcom) should get palette 0");

	/* $00 is what every synthetic probe ROM in test_roms/ carries. */
	reset_header();
	set_title(title);
	set_old_licensee(0x00);
	CHECK(GetGbcPaletteNumber(rom) == 0,
	      "old licensee $00 should get palette 0");

	/* A Nintendo cart whose title misses the table still gets 0 -- the gate
	   opening is not the same as the lookup succeeding. */
	reset_header();
	set_old_licensee(0x01);
	set_title("ZZZZZZZZZZZZZZZZ");
	CHECK(GetGbcPaletteNumber(rom) == 0,
	      "Nintendo cart with a non-hashing title should get palette 0");

	printf("\n");
	if (failures)
	{
		printf("FAILED: %d check(s)\n", failures);
		return 1;
	}
	printf("PASS: all checks\n");
	return 0;
}
