/* Host-side unit tests for drawtextl()'s off-screen (TEXTMEM) branch.
 *
 * The ChromA menu is two half-screens: whichever half is currently scrolled
 * off-view lives in the TEXTMEM shadow buffer, and swap_column() copies it a
 * column at a time into VRAM as the menu slides across.  drawtextl() writes to
 * VRAM or to TEXTMEM depending on which half `row` lands in, and the two
 * branches are supposed to produce the same 30-byte row.
 *
 * They did not (issue #57 item 5).  In the TEXTMEM branch the space-padding
 * loop never advanced `dest`, so it wrote one byte 29-i times instead of
 * clearing the tail of the row; whatever a previous, longer line had left there
 * stayed, and then scrolled into view.  The `len` argument was ignored as well,
 * so a caller asking for a truncated field got the whole string.
 *
 * These are checked on the host rather than through the emulator because the
 * bug is invisible in a single screenshot -- it needs a long line, then a short
 * line, then a scroll, and it corrupts a buffer that no test ROM can read back.
 * Here it is a direct memcmp.
 *
 * Only the TEXTMEM branch is exercised: the VRAM branch writes through
 * SCREENBASE (0x06000000), which is a real address on a GBA and a segfault on
 * the host.  `ui_x` and `row` are chosen to stay out of it.
 */

#include <stdio.h>
#include <string.h>

#include "gba.h"

/* --- the globals and helpers pocketnes_text.c expects from the rest of the
   build.  None of them are reached by the TEXTMEM branch of drawtextl(). --- */

u8 TEXTMEM[21][30];
int ui_x;
int ui_y_real;
int darkness;
int ui_border_visible;
u32 font_lz77;
u32 fontpal_bin;

void LZ77UnCompVram(const u32 *src, void *dst) { (void)src; (void)dst; }
void memcpy32(void *dst, const void *src, u32 n) { (void)dst; (void)src; (void)n; }
void memset32(void *dst, u32 val, u32 n) { (void)dst; (void)val; (void)n; }
void move_ui_asm(void) {}
void waitframe(void) {}

void drawtextl(int row, const char *str, int hilite, int len);

static int failures;

#define CHECK(cond, msg) do {                                               \
    if (!(cond)) {                                                          \
        printf("  FAIL: %s\n", msg);                                        \
        failures++;                                                         \
    }                                                                       \
} while (0)

/* A row index in the lower half plus ui_x bit 8 set sends drawtextl() to the
   TEXTMEM branch: the guard is (row>=32 && ui_x&256) || (row<32 && !(ui_x&256))
   for the VRAM branch, so row<32 with bit 8 set falls through to the else. */
#define ROW 5

static void fill_row_with(int row, u8 byte) {
    memset(TEXTMEM[row], byte, 30);
}

/* Every byte of the row, so an off-the-end write into the next row is visible */
static int row_all(int row, u8 byte) {
    int i;
    for (i = 0; i < 30; i++) {
        if (TEXTMEM[row][i] != byte) return 0;
    }
    return 1;
}

static void report_row(const char *label, int row) {
    int i;
    printf("    %s: [", label);
    for (i = 0; i < 30; i++) {
        u8 c = TEXTMEM[row][i] & 0x7F;
        putchar(c >= ' ' && c < 127 ? c : '?');
    }
    printf("]\n");
}

/* 1. The regression itself: a short line after a long one must not leave the
      long line's tail behind. */
static void test_short_after_long(void) {
    printf("Short line after long line clears the tail\n");

    memset(TEXTMEM, 0, sizeof(TEXTMEM));
    ui_x = 256;

    drawtextl(ROW, "ABCDEFGHIJKLMNOPQRSTUVWXYZ123", 0, 29);
    report_row("long ", ROW);

    drawtextl(ROW, "ab", 0, 29);
    report_row("short", ROW);

    CHECK(TEXTMEM[ROW][0] == ' ', "col 0 should be the (unhighlighted) space");
    CHECK(TEXTMEM[ROW][1] == 'a', "col 1 should be 'a'");
    CHECK(TEXTMEM[ROW][2] == 'b', "col 2 should be 'b'");

    {
        int i, stale = 0;
        for (i = 3; i < 30; i++) {
            if (TEXTMEM[ROW][i] != ' ') stale++;
        }
        CHECK(stale == 0, "columns 3..29 must all be spaces, not the old line");
        if (stale) printf("    %d stale byte(s) left from the long line\n", stale);
    }
}

/* 2. Padding must not run off the end of the 30-byte row. */
static void test_no_overrun(void) {
    printf("Padding stays inside the 30-byte row\n");

    memset(TEXTMEM, 0, sizeof(TEXTMEM));
    fill_row_with(ROW + 1, 0xAA);
    ui_x = 256;

    drawtextl(ROW, "hi", 0, 29);

    CHECK(row_all(ROW + 1, 0xAA), "the following row must be untouched");
}

/* 3. `len` truncates, exactly as it does in the VRAM branch. */
static void test_len_is_honored(void) {
    printf("len truncates the copied string\n");

    memset(TEXTMEM, 0, sizeof(TEXTMEM));
    ui_x = 256;

    drawtextl(ROW, "ABCDEFGH", 0, 3);
    report_row("len=3", ROW);

    CHECK(TEXTMEM[ROW][1] == 'A', "col 1 should be 'A'");
    CHECK(TEXTMEM[ROW][2] == 'B', "col 2 should be 'B'");
    CHECK(TEXTMEM[ROW][3] == 'C', "col 3 should be 'C'");
    CHECK(TEXTMEM[ROW][4] == ' ', "col 4 must be padded, not 'D'");

    {
        int i, extra = 0;
        for (i = 4; i < 30; i++) {
            if (TEXTMEM[ROW][i] != ' ') extra++;
        }
        CHECK(extra == 0, "everything past len must be spaces");
    }
}

/* 4. The highlight column and the +0x80 inverse-video bias still work. */
static void test_hilite(void) {
    printf("Highlighted rows get the asterisk and the 0x80 bias\n");

    memset(TEXTMEM, 0, sizeof(TEXTMEM));
    ui_x = 256;

    drawtextl(ROW, "ab", 1, 29);

    CHECK(TEXTMEM[ROW][0] == (u8)('*' + 0x80), "col 0 should be an inverse '*'");
    CHECK(TEXTMEM[ROW][1] == (u8)('a' + 0x80), "col 1 should be inverse 'a'");
    CHECK(TEXTMEM[ROW][2] == (u8)('b' + 0x80), "col 2 should be inverse 'b'");
    CHECK(TEXTMEM[ROW][3] == ' ', "padding is plain spaces, not inverse");
}

/* 5. A full-width line fills the row and still terminates. */
static void test_full_width(void) {
    printf("A 29-character line fills the row exactly\n");

    memset(TEXTMEM, 0, sizeof(TEXTMEM));
    fill_row_with(ROW + 1, 0xAA);
    ui_x = 256;

    drawtextl(ROW, "ABCDEFGHIJKLMNOPQRSTUVWXYZ123", 0, 29);

    CHECK(TEXTMEM[ROW][0] == ' ', "col 0 is the highlight column");
    CHECK(TEXTMEM[ROW][29] == '3', "col 29 should be the 29th character");
    CHECK(row_all(ROW + 1, 0xAA), "the following row must be untouched");
}

int main(void) {
    printf("drawtextl() TEXTMEM branch tests\n");
    printf("================================\n");

    test_short_after_long();
    test_no_overrun();
    test_len_is_honored();
    test_hilite();
    test_full_width();

    printf("\n");
    if (failures) {
        printf("FAILED: %d check(s)\n", failures);
        return 1;
    }
    printf("PASS: all checks\n");
    return 0;
}
