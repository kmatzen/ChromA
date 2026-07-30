/* Host-side unit tests for the savestate record-chain walkers in src/sram.c.
 *
 * The heap in cart SRAM is a run of variable-length records starting at
 * sram_copy+4, each `size` bytes long, terminated by a zero size.  Two things
 * about it were wrong (issue #57):
 *
 *   item 2  FindStateByIndex() selected records with `sh->type == type`.  The
 *           delete menu asks for "any deletable record" by passing type = -1,
 *           but sh->type is a u16, so the comparison promotes the field to
 *           0..65535 and -1 can never match.  The delete menu drew a list,
 *           took a selection, and erased nothing -- silently.
 *
 *   item 4  None of the four walkers bounded the chain against save_start.
 *           This heap is battery-backed cart SRAM: it survives power loss
 *           mid-write, and its STATEID magic is shared with other
 *           Goomba-family forks that lay records out differently.  A size
 *           below a header length walks the chain a byte at a time, and a
 *           size that steps over the terminator runs until it happens to land
 *           on a zero halfword -- both well outside sram_copy.
 *
 * These are checked on the host rather than through the emulator because
 * neither is visible on screen: the first is an absence of an effect, and the
 * second is a read off the end of a buffer that a GBA maps to more RAM.  Here
 * the arena is followed by a decoy region full of well-formed records, so a
 * walker that escapes the heap reports a count that a correct one cannot.
 */

#include <stdio.h>
#include <string.h>

#include "gba.h"
#include "sram.h"

/* --- the layout constants sram.c keeps private ------------------------- */
#define STATEID    0x57a731d8
#define STATESAVE  0
#define SRAMSAVE   1
#define CONFIGSAVE 2
#define ANYSAVE    (-1)

#define LOADMENU   0
#define SAVEMENU   1
#define SRAMMENU   2
#define DELETEMENU 3

#define HDR ((int)sizeof(stateheader))

/* --- globals and helpers the rest of the build owns.  Only the ones the
   chain walkers actually reach need real behaviour. --------------------- */
/* Both of these are defined by sram.c -- declare them only.  Defining them
   here as well links on mach-o, which merges tentative definitions, but not
   against GNU ld, which rejects the duplicate. */
extern u8 *sram_copy;
extern u32 save_start;

int FindStateByIndex(int index, int type, stateheader **stateptr);

u8 *ewram_start;
u8 *textstart;
u8 *romstart;
u8 XGB_SRAM[0x8000];
u8 *INSTANT_PAGES[256];
u8 TEXTMEM[21][30];
u8 RECENT_TILENUM[0x80];
u8 DIRTY_TILE_BITS[0x30];
u8 dirty_map_words[0x40];
u8 vram_packets_dirty[0xC4];
u8 vram_packets_incoming[0xC0];
u8 vram_packets_registered_bank0[0xC0];
u8 vram_packets_registered_bank1[0xC0];
u32 ewram_canary_1, ewram_canary_2;
u32 frametotal, g_emuflags, g_rammask, romnum, paltxt_count, palettebank;
u8 g_cartflags, g_sramsize, gammavalue, request_gb_type, autostate, stime;
u8 auto_border;
int ui_x, ui_y, selected;
char str[48];

int SaveState(u8 *d) { (void)d; return 0; }
int LoadState(u8 *s, int n) { (void)s; (void)n; return 0; }
int rle_compress(u8 *s, int n, u8 *d) { (void)s; (void)n; (void)d; return 0; }
int rle_decompress(u8 *s, int n, u8 *d, int m)
{ (void)s; (void)n; (void)d; (void)m; return 0; }
void bytecopy(u8 *d, u8 *s, int n) { memcpy(d, s, (size_t)n); }
void memcpy32(void *d, const void *s, u32 n) { memcpy(d, s, n); }
void memset32(void *d, u32 v, u32 n) { (void)d; (void)v; (void)n; }
void memset8(void *d, u8 v, u32 n) { memset(d, v, n); }
void findrom(void) {}
void loadcart(int a, int b) { (void)a; (void)b; }
u8 *make_instant_pages(u8 *b) { return b; }
void make_ui_visible(void) {}
void move_ui(void) {}
void waitframe(void) {}
void drawui1(void) {}
void cls(int n) { (void)n; }
void scrolll(int n) { (void)n; }
void scrollr(int n) { (void)n; }
int getmenuinput(int n) { (void)n; return 0; }
void drawtext_secondary(int r, const char *s, int h) { (void)r; (void)s; (void)h; }

/* drawstates() renders the "size, free N" line through drawtext(); capture it
   so the freespace formatting can be asserted on. */
static char last_info_line[256];
void drawtext(int row, const char *s, int hilite)
{
	(void)hilite;
	if (row == 32 + 18)
		snprintf(last_info_line, sizeof(last_info_line), "%s", s);
}

/* --- the arena ---------------------------------------------------------
   `heap` is what save_start covers.  `decoy` follows it immediately and is
   filled with well-formed STATESAVE records, so any walker that runs past the
   end of the heap keeps finding matches instead of crashing -- which turns an
   out-of-bounds walk into a wrong count rather than a flaky segfault. */
#define HEAP_SIZE  2048
#define DECOY_SIZE 2048
static u8 arena[HEAP_SIZE + DECOY_SIZE];

static int failures;

#define CHECK(cond, msg) do {                                               \
    if (!(cond)) {                                                          \
        printf("  FAIL: %s\n", msg);                                        \
        failures++;                                                         \
    }                                                                       \
} while (0)

/* Write a record at byte `off` in the arena.  Returns the offset just past it. */
static int put_record(int off, u16 size, u16 type, u32 checksum)
{
	stateheader *sh = (stateheader *)(arena + off);
	memset(sh, 0, sizeof(*sh));
	sh->size = size;
	sh->type = type;
	sh->checksum = checksum;
	strcpy(sh->title, "REC");
	return off + size;
}

static void arena_reset(void)
{
	int off;

	memset(arena, 0, sizeof(arena));
	sram_copy = arena;
	save_start = HEAP_SIZE;
	*(u32 *)arena = STATEID;

	/* Fill the region past save_start with records that look perfectly
	   valid, so escaping the heap is detectable rather than fatal. */
	for (off = HEAP_SIZE; off + HDR <= (int)sizeof(arena); off += HDR)
		put_record(off, (u16)HDR, STATESAVE, 0xDEC0DEC0);
}

/* Pack the heap edge to edge, so the last record ends exactly at save_start
   and there is no zero size anywhere in it.  This is the case only the bound
   can stop: a walker that trusts sh->size steps straight from the last record
   into the decoy region.  (Leaving any slack at the end would leave zeroed
   bytes there, and an unbounded walk would halt on those by luck.)
   Returns the number of records written. */
static int fill_heap_exactly(u16 type, u32 checksum)
{
	int off = 4;
	int records = 0;
	int remaining;

	while ((remaining = HEAP_SIZE - off) >= 2 * HDR) {
		off = put_record(off, (u16)HDR, type, checksum);
		records++;
	}
	if (remaining >= HDR) {
		put_record(off, (u16)remaining, type, checksum);
		records++;
	}
	return records;
}

/* Count how many records of `type` FindStateByIndex() can reach, by asking for
   increasing indices until one misses.  Bounded well past the heap so an
   escaped walk terminates the test instead of hanging it. */
static int count_by_index(int type)
{
	stateheader *sh;
	int n = 0;
	while (n < 4096 && FindStateByIndex(n, type, &sh))
		n++;
	return n;
}

static void test_wellformed_chain(void)
{
	stateheader *sh = NULL;
	int off = 4;

	printf("well-formed chain\n");
	arena_reset();
	off = put_record(off, 64, STATESAVE,  0xAAAA);
	off = put_record(off, 80, SRAMSAVE,   0xBBBB);
	off = put_record(off, 64, STATESAVE,  0xCCCC);
	off = put_record(off, 48, CONFIGSAVE, 0xDDDD);
	put_record(off, 0, 0, 0);	/* terminator */

	CHECK(count_by_index(STATESAVE) == 2, "two STATESAVE records");
	CHECK(count_by_index(SRAMSAVE) == 1, "one SRAMSAVE record");
	CHECK(count_by_index(CONFIGSAVE) == 1, "one CONFIGSAVE record");

	CHECK(FindStateByIndex(1, STATESAVE, &sh) && sh->checksum == 0xCCCC,
	      "STATESAVE index 1 is the second STATESAVE, not the second record");

	/* The regression: the delete menu's "any deletable record" query.  Before
	   the fix this matched nothing at all, so the count was 0. */
	CHECK(count_by_index(ANYSAVE) == 3,
	      "ANYSAVE reaches all three non-config records");
	CHECK(FindStateByIndex(0, ANYSAVE, &sh) && sh->checksum == 0xAAAA,
	      "ANYSAVE index 0");
	CHECK(FindStateByIndex(1, ANYSAVE, &sh) && sh->checksum == 0xBBBB,
	      "ANYSAVE index 1 crosses record types");
	CHECK(FindStateByIndex(2, ANYSAVE, &sh) && sh->checksum == 0xCCCC,
	      "ANYSAVE index 2");
	CHECK(!FindStateByIndex(3, ANYSAVE, &sh),
	      "ANYSAVE stops before the config record");

	CHECK(totalstatesize == 64 + 80 + 64 + 48, "totalstatesize sums the chain");
}

/* The delete menu draws every non-config record and then erases by the index
   the user landed on, so drawstates(DELETEMENU) and FindStateByIndex(ANYSAVE)
   have to agree on both the count and the order -- otherwise the wrong record
   is destroyed. */
static void test_delete_index_matches_drawn_list(void)
{
	stateheader *sh = NULL;
	int menuitems = 0, offset = 0;
	int off = 4;
	int i;
	static const u32 expect[] = { 0xAAAA, 0xBBBB, 0xCCCC };

	printf("delete-menu index agrees with the drawn list\n");
	arena_reset();
	off = put_record(off, 64, CONFIGSAVE, 0x9999);	/* config first */
	off = put_record(off, 64, STATESAVE,  0xAAAA);
	off = put_record(off, 80, SRAMSAVE,   0xBBBB);
	off = put_record(off, 64, STATESAVE,  0xCCCC);
	put_record(off, 0, 0, 0);

	selected = 0;
	drawstates(DELETEMENU, &menuitems, &offset, 0);
	CHECK(menuitems == 3, "delete menu lists three records");

	for (i = 0; i < 3; i++) {
		CHECK(FindStateByIndex(i, ANYSAVE, &sh) && sh->checksum == expect[i],
		      "delete index selects the record drawn at that row");
	}
}

static void test_size_below_header(void)
{
	printf("record smaller than a header\n");
	arena_reset();
	put_record(4, 64, STATESAVE, 0xAAAA);
	/* A record claiming 1 byte: the old walk advanced by 1 and re-read the
	   chain from a misaligned offset, drifting off the end of the heap. */
	put_record(4 + 64, 1, STATESAVE, 0xBBBB);

	CHECK(count_by_index(STATESAVE) == 1,
	      "walk stops at the undersized record");
	CHECK(totalstatesize == 64, "totalstatesize counts only the valid record");
}

static void test_size_past_heap_end(void)
{
	printf("record running past the end of the heap\n");
	arena_reset();
	put_record(4, 64, STATESAVE, 0xAAAA);
	put_record(4 + 64, 0xFFFF, STATESAVE, 0xBBBB);

	CHECK(count_by_index(STATESAVE) == 1,
	      "walk stops at the over-long record");
	CHECK(totalstatesize == 64, "over-long record is not counted");
}

static void test_unterminated_chain(void)
{
	int records;

	printf("chain with no terminator\n");
	arena_reset();
	records = fill_heap_exactly(STATESAVE, 0xAAAA);

	CHECK(count_by_index(STATESAVE) == records,
	      "walk stops at save_start instead of running into the decoys");
	CHECK(totalstatesize == HEAP_SIZE - 4,
	      "totalstatesize stays inside the heap");
}

static void test_findstate_bounded(void)
{
	stateheader *sh = NULL;

	printf("findstate() is bounded too\n");
	arena_reset();
	fill_heap_exactly(STATESAVE, 0xAAAA);

	CHECK(findstate(0xAAAA, STATESAVE, &sh) >= 0 && sh->checksum == 0xAAAA,
	      "findstate finds a record inside the heap");
	/* The decoy records all carry 0xDEC0DEC0; reaching one means the walk
	   left the heap. */
	CHECK(findstate(0xDEC0DEC0, STATESAVE, &sh) < 0,
	      "findstate cannot reach a record past save_start");
}

/* drawstates() renders freespace through number_at(), which formats a u32.
   A negative freespace printed as ten digits, and the whole line is built in
   str[48] (issue #57 item 4). */
static void test_freespace_never_negative(void)
{
	int menuitems = 0, offset = 0;

	printf("freespace rendering on a full heap\n");
	arena_reset();
	/* Exactly full: the walk sums to save_start-4, and drawstates() adds 8
	   for the header and terminator, so freespace lands a few bytes negative
	   even with the bound in place -- which is what the clamp is for. */
	fill_heap_exactly(STATESAVE, 0xAAAA);

	selected = 0;
	last_info_line[0] = 0;
	drawstates(LOADMENU, &menuitems, &offset, 0);

	CHECK(last_info_line[0] != 0, "info line was drawn");
	CHECK(strstr(last_info_line, ", free ") != NULL, "info line has a freespace field");
	CHECK(strlen(last_info_line) < sizeof(str),
	      "info line fits in str[48]");
	{
		const char *f = strstr(last_info_line, ", free ");
		/* 4294967290-style output is what a negative freespace produced. */
		CHECK(f && strlen(f + 7) <= 5,
		      "freespace is a plausible byte count, not a wrapped negative");
	}
}

int main(void)
{
	printf("SRAM record-chain unit tests (issue #57 items 2 and 4)\n\n");

	test_wellformed_chain();
	test_delete_index_matches_drawn_list();
	test_size_below_header();
	test_size_past_heap_end();
	test_unterminated_chain();
	test_findstate_bounded();
	test_freespace_never_negative();

	printf("\n");
	if (failures) {
		printf("FAILED: %d check(s)\n", failures);
		return 1;
	}
	printf("PASS: all checks\n");
	return 0;
}
