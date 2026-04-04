/* Simple RLE compression for savestates.
 * Public domain — no license restrictions.
 *
 * Format: stream of chunks. Each chunk starts with a control byte:
 *   0x00-0x7F: literal run of (control+1) bytes follows
 *   0x80-0xFF: repeat next byte (control-0x80+3) times (3..130 repeats)
 *
 * No hash tables, no workspace, no malloc. ~100 lines of code.
 */

#include "rle.h"

int rle_compress(const uint8_t *src, int src_len, uint8_t *dst) {
    const uint8_t *sp = src;
    const uint8_t *end = src + src_len;
    uint8_t *dp = dst;

    while (sp < end) {
        /* Check for a run of identical bytes (min 3) */
        if (sp + 2 < end && sp[0] == sp[1] && sp[1] == sp[2]) {
            uint8_t val = sp[0];
            int run = 3;
            sp += 3;
            while (sp < end && *sp == val && run < 130)
                run++, sp++;
            *dp++ = (uint8_t)(0x80 + run - 3);
            *dp++ = val;
        } else {
            /* Literal run: find how many non-repeating bytes */
            const uint8_t *lit_start = sp;
            sp++;
            while (sp < end && (sp + 2 >= end ||
                   !(sp[0] == sp[1] && sp[1] == sp[2]))) {
                sp++;
                if (sp - lit_start >= 128) break;
            }
            int lit_len = sp - lit_start;
            *dp++ = (uint8_t)(lit_len - 1);
            for (int i = 0; i < lit_len; i++)
                *dp++ = lit_start[i];
        }
    }
    return dp - dst;
}

int rle_decompress(const uint8_t *src, int src_len, uint8_t *dst, int max_out) {
    const uint8_t *sp = src;
    const uint8_t *send = src + src_len;
    uint8_t *dp = dst;
    uint8_t *dend = dst + max_out;

    while (sp < send && dp < dend) {
        uint8_t ctrl = *sp++;
        if (ctrl & 0x80) {
            /* Repeat run */
            int count = (ctrl - 0x80) + 3;
            if (sp >= send) break;
            uint8_t val = *sp++;
            while (count-- > 0 && dp < dend)
                *dp++ = val;
        } else {
            /* Literal run */
            int count = ctrl + 1;
            while (count-- > 0 && sp < send && dp < dend)
                *dp++ = *sp++;
        }
    }
    return dp - dst;
}
