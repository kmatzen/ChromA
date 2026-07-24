/* Host-side unit tests for the savestate RLE codec (src/rle.c).
 *
 * These compile and run natively (no GBA toolchain / mGBA required), so
 * they exercise the compression/decompression logic directly instead of
 * only indirectly through full savestate ROM runs.
 *
 * Build & run:
 *   cc -O2 -I../../src test_rle.c ../../src/rle.c -o test_rle && ./test_rle
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "rle.h"

static int g_failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { \
        fprintf(stderr, "FAIL: %s (%s:%d)\n", (msg), __FILE__, __LINE__); \
        g_failures++; \
    } \
} while (0)

/* Round-trips src through compress -> decompress and checks the result
 * matches exactly. */
static void check_roundtrip(const char *name, const uint8_t *src, int src_len) {
    uint8_t *compressed = malloc(src_len * 2 + 16);
    uint8_t *restored = malloc(src_len + 16);

    int comp_len = rle_compress(src, src_len, compressed);
    CHECK(comp_len > 0 || src_len == 0, name);

    int rest_len = rle_decompress(compressed, comp_len, restored, src_len);
    CHECK(rest_len == src_len, name);
    CHECK(rest_len <= 0 || memcmp(restored, src, src_len) == 0, name);

    free(compressed);
    free(restored);
}

static void test_empty(void) {
    uint8_t dummy = 0;
    check_roundtrip("empty input", &dummy, 0);
}

static void test_single_byte(void) {
    uint8_t src[] = {0x42};
    check_roundtrip("single byte", src, sizeof(src));
}

static void test_literal_run(void) {
    uint8_t src[64];
    for (int i = 0; i < 64; i++) src[i] = (uint8_t)(i * 7 + 1);
    check_roundtrip("non-repeating literal run", src, sizeof(src));
}

static void test_literal_run_exactly_128(void) {
    /* Literal runs are capped at 128 bytes per chunk (control byte 0-127
     * encodes length-1); a 128-byte literal run should compile to exactly
     * one chunk boundary without corruption. */
    uint8_t src[128];
    for (int i = 0; i < 128; i++) src[i] = (uint8_t)((i * 31 + 3) & 0xFF);
    check_roundtrip("literal run at 128-byte boundary", src, sizeof(src));
}

static void test_literal_run_over_128(void) {
    uint8_t src[300];
    for (int i = 0; i < 300; i++) src[i] = (uint8_t)((i * 17 + 5) & 0xFF);
    check_roundtrip("literal run spanning multiple chunks", src, sizeof(src));
}

static void test_short_repeat_not_compressed(void) {
    /* Two identical bytes don't meet the minimum run length of 3 and
     * should be treated as literals. */
    uint8_t src[] = {0xAA, 0xAA, 0x01, 0x02};
    check_roundtrip("run below minimum length (2)", src, sizeof(src));
}

static void test_minimum_repeat_run(void) {
    uint8_t src[] = {0x55, 0x55, 0x55};
    check_roundtrip("minimum repeat run (3)", src, sizeof(src));
}

static void test_repeat_run_exactly_130(void) {
    /* Repeat runs are capped at 130 bytes (control byte 0x80-0xFF encodes
     * count-3, max count 130). Exercise the exact boundary. */
    uint8_t src[130];
    memset(src, 0x99, sizeof(src));
    check_roundtrip("repeat run at 130-byte boundary", src, sizeof(src));
}

static void test_repeat_run_over_130(void) {
    uint8_t src[400];
    memset(src, 0x77, sizeof(src));
    check_roundtrip("repeat run spanning multiple chunks", src, sizeof(src));
}

static void test_mixed_data(void) {
    uint8_t src[512];
    int i = 0;
    while (i < 512) {
        if ((i / 37) % 2 == 0) {
            src[i] = (uint8_t)(i & 0xFF);
            i++;
        } else {
            uint8_t val = (uint8_t)((i * 3) & 0xFF);
            int run = 3 + (i % 20);
            for (int j = 0; j < run && i < 512; j++, i++) src[i] = val;
        }
    }
    check_roundtrip("mixed literal/repeat data", src, sizeof(src));
}

static void test_all_zeros(void) {
    uint8_t src[256];
    memset(src, 0, sizeof(src));
    check_roundtrip("all zeros (typical WRAM padding)", src, sizeof(src));
}

static void test_decompress_respects_max_out(void) {
    /* A malformed/oversized stream must not overflow the destination
     * buffer; decompression should stop cleanly at max_out. */
    uint8_t src[64];
    memset(src, 0xAA, sizeof(src)); /* run of 0xAA (0x80+0xAA... treat as ctrl bytes) */
    uint8_t small_dst[8];
    int out_len = rle_decompress(src, sizeof(src), small_dst, sizeof(small_dst));
    CHECK(out_len <= (int)sizeof(small_dst), "decompress does not exceed max_out");
}

static void test_decompress_truncated_repeat_header(void) {
    /* A repeat control byte with no following value byte must not read
     * past the end of the source buffer. */
    uint8_t src[] = {0x80}; /* repeat control, but no value byte follows */
    uint8_t dst[16];
    int out_len = rle_decompress(src, sizeof(src), dst, sizeof(dst));
    CHECK(out_len == 0, "truncated repeat header produces no output");
}

int main(void) {
    test_empty();
    test_single_byte();
    test_literal_run();
    test_literal_run_exactly_128();
    test_literal_run_over_128();
    test_short_repeat_not_compressed();
    test_minimum_repeat_run();
    test_repeat_run_exactly_130();
    test_repeat_run_over_130();
    test_mixed_data();
    test_all_zeros();
    test_decompress_respects_max_out();
    test_decompress_truncated_repeat_header();

    if (g_failures == 0) {
        printf("All RLE unit tests passed.\n");
        return 0;
    }
    fprintf(stderr, "%d RLE unit test(s) failed.\n", g_failures);
    return 1;
}
