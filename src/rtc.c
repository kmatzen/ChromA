/* Software RTC for MBC3 games (e.g., Pokemon Gold/Silver/Crystal).
 *
 * Replaces the GBA cartridge hardware RTC bit-banging with a simple
 * frame-counter-based clock.  The clock starts at 10:00:00 on boot
 * and advances in real time during gameplay (~60 frames per second).
 *
 * The time is stored in BCD format in mapperdata[24..31], matching the
 * layout the MBC3 mapper reads expect.
 */

#include "gba.h"

extern u32 frametotal;    /* from gbz80.s: total GB frames rendered */
extern u8 mapperstate[];  /* from cart.s: 32-byte mapper data buffer */

#define FRAMES_PER_SECOND 60
#define BASE_SECONDS (10 * 3600)  /* start at 10:00:00 */

static u8 to_bcd(u8 val) {
    return ((val / 10) << 4) | (val % 10);
}

/* Software fallback, called from gettime (io.s) when no hardware RTC. */
void gettime_sw(void) {
    u32 total_seconds = frametotal / FRAMES_PER_SECOND + BASE_SECONDS;

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
