/* Software RTC for MBC3 games (e.g., Pokemon Gold/Silver/Crystal).
 *
 * Replaces the GBA cartridge hardware RTC bit-banging with a simple
 * frame-counter-based clock.  The clock starts at 10:00:00 on boot
 * and advances in real time during gameplay (59.7275 frames per second).
 * The epoch is not persisted, so it restarts at 10:00:00 on every boot --
 * see issue #49 item 5.
 *
 * The time is stored in BCD format in mapperdata[24..31], matching the
 * layout the MBC3 mapper reads expect.
 */

#include "gba.h"

extern u32 frametotal;    /* from gbz80.s: total GB frames rendered */
extern u8 mapperstate[];  /* from cart.s: 32-byte mapper data buffer */

/* The GB does not run at 60fps: a frame is 70224 dots of a 4194304Hz clock,
 * i.e. 59.7275Hz.  Dividing the frame count by a flat 60 made the clock lose
 * ~0.45%, about 6.5 minutes per emulated day.
 *
 * seconds = frames / (4194304 / 70224) = frames * 70224 / 4194304, and
 * 4194304 is 2^22, so the division is a shift and the result is exact.  The
 * product needs more than 32 bits once the frame count passes ~61k (about 17
 * minutes), hence the 64-bit intermediate.
 */
#define GB_DOTS_PER_FRAME 70224u
#define GB_DOT_CLOCK_SHIFT 22      /* 4194304 == 1 << 22 */
#define BASE_SECONDS (10 * 3600)  /* start at 10:00:00 */

static u8 to_bcd(u8 val) {
    return ((val / 10) << 4) | (val % 10);
}

/* Software fallback, called from gettime (io.s) when no hardware RTC. */
void gettime_sw(void) {
    u32 total_seconds = (u32)(((unsigned long long)frametotal *
                               GB_DOTS_PER_FRAME) >> GB_DOT_CLOCK_SHIFT)
                        + BASE_SECONDS;

    u32 days = total_seconds / 86400;
    u32 remaining = total_seconds % 86400;
    u8 hours = remaining / 3600;
    remaining %= 3600;
    u8 minutes = remaining / 60;
    u8 seconds = remaining % 60;

    /* mapperdata layout (offsets from mapperstate):
     *   [26] = day counter low
     *   [27] = day counter high
     *   [28] = hours   (BCD)
     *   [29] = minutes (BCD)
     *   [30] = seconds (BCD)
     */
    mapperstate[26] = days & 0xFF;
    mapperstate[27] = (days >> 8) & 0x01;
    mapperstate[28] = to_bcd(hours);
    mapperstate[29] = to_bcd(minutes);
    mapperstate[30] = to_bcd(seconds);
}
