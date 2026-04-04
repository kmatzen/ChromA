/* Simple RLE compression for savestates.
 * Public domain — no license restrictions. */

#ifndef RLE_H
#define RLE_H

#include <stdint.h>

/* Compress src[0..src_len-1] into dst. Returns compressed size.
 * Worst case output size: src_len * 2 (no runs found). */
int rle_compress(const uint8_t *src, int src_len, uint8_t *dst);

/* Decompress src[0..src_len-1] into dst. Returns decompressed size.
 * max_out is the maximum output size (safety limit). */
int rle_decompress(const uint8_t *src, int src_len, uint8_t *dst, int max_out);

#endif
