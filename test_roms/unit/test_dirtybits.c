/* Host-side unit tests for SetBits()/SetDirtyTiles() in src/dma.c.
 *
 * SetBits marks a half-open bit range [firstBit, lastBit) in the VRAM
 * dirty-tile bitmap.  When lastBit is a multiple of 32 the final word holds
 * none of the range and lastMask comes out 0, but the original code still did
 *
 *     base[lastWord] |= lastMask;
 *
 * unconditionally -- a read-modify-write one word past the end of the bitmap.
 * DIRTY_TILE_BITS is 48 bytes split into two 24-byte banks (src/equates.h:133),
 * and lcd.s rebases _dirty_tile_bits to DIRTY_TILE_BITS+24 for VRAM bank 1
 * (`addne addy,addy,#24`, src/lcd.s:4977-4979), so for bank 1 that word is
 * ewram_canary_2 -- the very thing sram.c:1217 checks to decide whether EWRAM
 * has been corrupted.  Issue #57 item 7.
 *
 * The catch, and the reason this test is shaped the way it is: the mask is 0, so
 * `|= 0` leaves the canary's *value* alone.  Reading the canary back therefore
 * proves nothing.  What is wrong is the access, not the result, so the range is
 * placed at the very end of a mapped page with an unmapped guard page directly
 * behind it and the call is made in a forked child.  Pre-fix the child dies of
 * SIGSEGV/SIGBUS; post-fix it exits cleanly.
 *
 * The value-level tests below pin down which bits SetBits is supposed to set,
 * so that skipping the final word cannot quietly drop real work.
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/wait.h>

/* dma.c is compiled into this translation unit: SetBits and SetDirtyTiles are
   static, so there is no other way to reach them, and duplicating them here
   would test a copy instead of the shipping code. */
#include "dma.c"

/* --- everything dma.c needs from the assembly half of the build.  None of it
   is reached by SetBits/SetDirtyTiles. --- */

u8 *_dirty_tile_bits;
u16 _dma_src;
u16 _dma_dest;
u8 _dmamode;
u8 _vrambank;
u8 *g_memmap_tbl[16];
u8 dirty_map_words[64];
u32 _vram_packet_dest;
u8 *_vram_packet_source;
VramPacketData2 vram_packets_incoming[64];
VramPacketData2 vram_packets_registered_bank0[64];
VramPacketData2 vram_packets_registered_bank1[64];
VramPacketData3 vram_packets_dirty[64];

void copy_map_and_compare(u8 *d, u8 *s, int n, u8 *p) {
    (void)d; (void)s; (void)n; (void)p;
}
void memcpy32(void *dst, const void *src, int n) { memcpy(dst, src, (size_t)n); }

static int failures;

#define CHECK(cond, msg) do {                                               \
    if (!(cond)) {                                                          \
        printf("  FAIL: %s\n", msg);                                        \
        failures++;                                                         \
    }                                                                       \
} while (0)

/* One VRAM bank's worth of dirty-tile bits: 24 bytes = 6 words = 192 bits. */
#define BANK_WORDS 6
#define BANK_BITS  (BANK_WORDS * 32)

/* The whole point of the bitmap is its exact word layout, so a host build whose
   u32 is not 32 bits would test something other than the shipping behaviour. */
static void test_word_width(void) {
    printf("u32 is 32 bits in this build\n");
    CHECK(sizeof(u32) == 4, "u32 must be 4 bytes for the bitmap layout to match");
}

/* ------------------------------------------------------------------ */
/* Value-level: which bits does the range actually set?               */
/* ------------------------------------------------------------------ */

static u32 bits[BANK_WORDS + 2];

static void run_setbits(int firstBit, int lastBit) {
    memset(bits, 0, sizeof(bits));
    SetBits(bits, firstBit, lastBit);
}

/* Independent reference: set exactly the bits in [first, last). */
static void reference(u32 *out, int first, int last) {
    int b;
    memset(out, 0, sizeof(u32) * (BANK_WORDS + 2));
    for (b = first; b < last; b++) {
        out[b / 32] |= (u32)1 << (b & 31);
    }
}

static void expect_range(int first, int last, const char *label) {
    u32 want[BANK_WORDS + 2];
    run_setbits(first, last);
    reference(want, first, last);
    if (memcmp(bits, want, sizeof(u32) * BANK_WORDS) != 0) {
        int i;
        printf("  FAIL: %s: wrong bits for [%d,%d)\n", label, first, last);
        for (i = 0; i < BANK_WORDS; i++) {
            printf("    word %d: got %08lx want %08lx\n",
                   i, (unsigned long)bits[i], (unsigned long)want[i]);
        }
        failures++;
    }
}

static void test_bit_ranges(void) {
    printf("SetBits marks exactly the half-open range\n");

    expect_range(0, 32, "one whole word");
    expect_range(0, 64, "two whole words");
    expect_range(0, BANK_BITS, "the whole bank");
    expect_range(5, 7, "a couple of bits inside one word");
    expect_range(31, 33, "straddling a word boundary");
    expect_range(64, 96, "a middle word");
    expect_range(96, BANK_BITS, "up to the end of the bank");
    expect_range(1, 191, "almost everything");

    /* An empty range must set nothing at all. */
    run_setbits(64, 64);
    {
        int i, set = 0;
        for (i = 0; i < BANK_WORDS; i++) if (bits[i]) set++;
        CHECK(set == 0, "an empty range must set no bits");
    }
}

/* The full-bank range is the one that produced the overrun: lastBit == 192 is
   a multiple of 32, so lastWord == 6 -- one past the bank. */
static void test_full_bank_touches_no_extra_word(void) {
    printf("A full-bank range leaves the word after the bank alone\n");

    memset(bits, 0, sizeof(bits));
    bits[BANK_WORDS] = 0xDEADBEEF;      /* stands in for ewram_canary_2 */
    SetBits(bits, 0, BANK_BITS);

    CHECK(bits[BANK_WORDS] == 0xDEADBEEF, "the canary word must keep its value");
    {
        int i, missing = 0;
        for (i = 0; i < BANK_WORDS; i++) {
            if (bits[i] != 0xFFFFFFFF) missing++;
        }
        CHECK(missing == 0, "every bit of the bank must still be marked");
    }
}

/* ------------------------------------------------------------------ */
/* Access-level: the out-of-bounds write, caught with a guard page.    */
/* ------------------------------------------------------------------ */

/* Place a 24-byte bank at the very end of a writable page, with the next page
   unmapped, and return a pointer to it.  A write to word 6 lands in the guard
   page and faults. */
static u8 *bank_against_guard_page(void) {
    long pagesize = sysconf(_SC_PAGESIZE);
    u8 *region = mmap(NULL, (size_t)pagesize * 2, PROT_READ | PROT_WRITE,
                      MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (region == MAP_FAILED) return NULL;
    if (mprotect(region + pagesize, (size_t)pagesize, PROT_NONE) != 0) return NULL;
    return region + pagesize - (BANK_WORDS * sizeof(u32));
}

/* Run one SetDirtyTiles call in a child process; return 1 if it survived. */
static int child_survives_setdirtytiles(int dest, int byteCount) {
    pid_t pid = fork();
    if (pid < 0) {
        printf("  FAIL: fork() failed\n");
        failures++;
        return 1;
    }
    if (pid == 0) {
        u8 *bank = bank_against_guard_page();
        if (!bank) _exit(3);
        memset(bank, 0, BANK_WORDS * sizeof(u32));
        _dirty_tile_bits = bank;
        SetDirtyTiles(dest, byteCount);
        _exit(0);
    }
    {
        int status = 0;
        if (waitpid(pid, &status, 0) < 0) return 1;
        if (WIFSIGNALED(status)) {
            printf("    child died of signal %d\n", WTERMSIG(status));
            return 0;
        }
        if (WIFEXITED(status) && WEXITSTATUS(status) == 3) {
            printf("    (could not set up the guard page; skipping)\n");
            return 1;
        }
        return 1;
    }
}

static void test_no_write_past_the_bank(void) {
    printf("SetDirtyTiles never writes past the end of the bank\n");

    /* dest 0x8000 + 0x1800 bytes covers all 384 tiles of VRAM, which is
       firstBit 0 .. lastBit 192 -- exactly the multiple-of-32 case. */
    CHECK(child_survives_setdirtytiles(0x8000, 0x1800),
          "a full-VRAM range must not touch the word after the bank");

    /* A range that ends mid-word must still work, and must still stay inside. */
    CHECK(child_survives_setdirtytiles(0x8000, 0x100),
          "a small range must not fault either");
}

int main(void) {
    printf("SetBits() / SetDirtyTiles() dirty-tile bitmap tests\n");
    printf("==================================================\n");

    test_word_width();
    test_bit_ranges();
    test_full_bank_touches_no_extra_word();
    test_no_write_past_the_bank();

    printf("\n");
    if (failures) {
        printf("FAILED: %d check(s)\n", failures);
        return 1;
    }
    printf("PASS: all checks\n");
    return 0;
}
