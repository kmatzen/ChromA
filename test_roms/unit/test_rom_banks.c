/* Host-side unit tests for make_instant_pages() (src/cache.c).
 *
 * INSTANT_PAGES is the 256-entry table the ARM banking code indexes to find
 * the host address of a 16KB GB ROM bank.  make_instant_pages() filled all 256
 * entries as rom_base + 16384*i unconditionally (the masking was commented
 * out), so for anything smaller than a 4MB cart every entry past the end of
 * the ROM pointed outside it -- at whatever the linker had placed after the
 * ROM image, or past __rom_end__ entirely (issue #57 item 6).
 *
 * cart.s masks bank numbers with rommask>>14, derived from the same header
 * byte 0x148, and clamps the cart to 4MB because this table only holds 256
 * entries.  The two have to agree, so these tests check the table against that
 * same rule: an out-of-range bank aliases back into the cart, exactly as the
 * real MBCs wrap, and no entry ever addresses a byte outside the ROM.
 *
 * INSTANT_PAGES[0] is excluded: make_instant_pages() deliberately repoints it
 * at a VRAM shadow copy of bank 0, which is not a host address.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gba.h"
#include "cache.h"

#define BANK_SIZE 16384

u8 *INSTANT_PAGES[256];

/* make_instant_pages() shadows bank 0 into VRAM at 0x06010000-512 and repoints
   INSTANT_PAGES[0] there.  That is a real address on a GBA and unmapped here
   -- and it cannot simply be mapped, because 64-bit macOS reserves the whole
   low 4GB as __PAGEZERO -- so the build renames memcpy to this stub.  It needs
   <string.h>'s exact signature, and the build also has to switch off
   _FORTIFY_SOURCE, whose own memcpy macro would otherwise win.

   Only INSTANT_PAGES[0] depends on that copy, and these tests skip entry 0. */
void *test_memcpy(void *dst, const void *src, size_t n)
{
	(void)src; (void)n;
	return dst;
}

static int failures;

#define CHECK(cond, msg) do {                                               \
    if (!(cond)) {                                                          \
        printf("  FAIL: %s\n", msg);                                        \
        failures++;                                                         \
    }                                                                       \
} while (0)

/* The table entries are compared as offsets and never dereferenced, so the
   image only has to be large enough to satisfy the bank-0 shadow copy, which
   reads one bank plus the 512-byte overscan cache.c copies with it. */
static u8 rom[BANK_SIZE + 1024];

/* Header byte 0x148 holds the size as 32KB << n, i.e. 2<<n banks of 16KB.
   cart.s clamps the result to 4MB, so the table tops out at 256 banks. */
static void check_size(u8 sizebyte, int expect_banks, const char *label)
{
	int i;
	int bad_alias = 0, out_of_rom = 0;
	long rom_bytes = (long)expect_banks * BANK_SIZE;

	memset(rom, 0, sizeof(rom));
	rom[0x148] = sizebyte;
	memset(INSTANT_PAGES, 0, sizeof(INSTANT_PAGES));

	make_instant_pages(rom);

	for (i = 1; i < 256; i++) {
		long off = INSTANT_PAGES[i] - rom;
		if (off != (long)(i % expect_banks) * BANK_SIZE)
			bad_alias++;
		if (off < 0 || off >= rom_bytes)
			out_of_rom++;
	}

	printf("  0x148=0x%02X -> %d banks (%s)\n", sizebyte, expect_banks, label);
	CHECK(bad_alias == 0, "every bank aliases into the cart the way the MBCs wrap");
	CHECK(out_of_rom == 0, "no table entry addresses memory outside the ROM");
}

int main(void)
{
	setvbuf(stdout, NULL, _IONBF, 0);
	printf("ROM bank table unit tests (issue #57 item 6)\n\n");

	/* 2<<n banks, up to the 4MB / 256-entry clamp cart.s applies. */
	check_size(0x00, 2,   "32KB, no MBC");
	check_size(0x01, 4,   "64KB");
	check_size(0x02, 8,   "128KB");
	check_size(0x04, 32,  "512KB");
	check_size(0x06, 128, "2MB");
	check_size(0x07, 256, "4MB - fills the table exactly");

	/* Bytes at or above 8 would ask for more than 256 banks; cart.s clamps
	   them to 4MB, so the table has to as well or the two disagree about how
	   big the cart is.  0x52/0x53/0x54 are the unofficial size codes, and
	   0xFF is what a blank or corrupt header byte looks like. */
	check_size(0x08, 256, "8MB, clamped");
	check_size(0x52, 256, "unofficial 1.1MB code, clamped");
	check_size(0xFF, 256, "garbage header byte, clamped");

	printf("\n");
	if (failures) {
		printf("FAILED: %d check(s)\n", failures);
		return 1;
	}
	printf("PASS: all checks\n");
	return 0;
}
