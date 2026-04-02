/* 10 sprites per scanline limit.
 *
 * Real GB/GBC hardware only renders the first 10 sprites that overlap
 * each scanline.  sprite_limit_save() saves the original Y values and
 * hides excess sprites in-place.  sprite_limit_restore() puts them back.
 */

#include "gba.h"

static u8 saved_y[40];

void sprite_limit_save(u32 *oam, int sprite_height) {
    u8 line_count[144];
    int i, line;

    /* Save original Y values */
    for (i = 0; i < 40; i++)
        saved_y[i] = oam[i] & 0xFF;

    /* Quick pre-scan: bail if no scanline exceeds 10 */
    for (i = 0; i < 144; i++)
        line_count[i] = 0;

    for (i = 0; i < 40; i++) {
        int y = saved_y[i];
        if (y == 0 || y > 159)
            continue;
        int top = y - 16;
        int bottom = top + sprite_height;
        if (top < 0) top = 0;
        if (bottom > 144) bottom = 144;
        for (line = top; line < bottom; line++)
            line_count[line]++;
    }
    {
        int any_over = 0;
        for (line = 0; line < 144; line++) {
            if (line_count[line] > 10) { any_over = 1; break; }
        }
        if (!any_over) return;
    }

    /* Rebuild counts in OAM priority order.  Hide sprites that exceed
     * the limit on ALL scanlines they cover. */
    for (i = 0; i < 144; i++)
        line_count[i] = 0;

    for (i = 0; i < 40; i++) {
        int y = saved_y[i];
        if (y == 0 || y > 159)
            continue;

        int top = y - 16;
        int bottom = top + sprite_height;
        if (top < 0) top = 0;
        if (bottom > 144) bottom = 144;

        int visible = 0;
        for (line = top; line < bottom; line++) {
            if (line_count[line] < 10) {
                visible = 1;
                break;
            }
        }

        if (!visible) {
            oam[i] &= ~0xFFu;  /* set Y=0 → OAMfinish skips it */
        } else {
            for (line = top; line < bottom; line++)
                line_count[line]++;
        }
    }
}

void sprite_limit_restore(u32 *oam) {
    int i;
    for (i = 0; i < 40; i++)
        oam[i] = (oam[i] & ~0xFFu) | saved_y[i];
}
