/* Software RTC for MBC3 games (e.g., Pokemon Gold/Silver/Crystal).
 *
 * Replaces the GBA cartridge hardware RTC bit-banging with a simple
 * frame-counter-based clock.  The clock starts at 10:00:00 on boot
 * and advances in real time during gameplay (59.7275 frames per second).
 *
 * The time is stored in mapperdata[24..31], matching the layout the MBC3
 * mapper reads expect: seconds, minutes and hours BCD (the readers decode
 * them with calctime), the day counter binary.
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

#define SECONDS_PER_DAY 86400u
#define DAY_COUNTER_SPAN 512u     /* the day counter is 9 bits wide */

/* mapperdata layout (offsets from mapperstate):
 *   [26] = day counter low 8 bits
 *   [27] = DH: bit 0 = day bit 8, bit 6 = halt, bit 7 = 512-day carry
 *   [28] = hours   (BCD)
 *   [29] = minutes (BCD)
 *   [30] = seconds (BCD)
 */
#define RTC_DAYL 26
#define RTC_DH   27
#define RTC_HRS  28
#define RTC_MIN  29
#define RTC_SEC  30

#define DH_DAY_BIT8 0x01
#define DH_HALT     0x40
#define DH_CARRY    0x80

/* Time carried by the emulated clock, as a count of seconds since day 0 of
 * the day counter.  When the clock runs, the current time is
 * `elapsed() + rtc_offset`; when it is halted, it is frozen at rtc_frozen.
 * A clock-set write moves whichever of the two applies, so the written value
 * is what the game reads back on the next latch.
 */
static u32 rtc_offset = BASE_SECONDS;
static u32 rtc_frozen;
static u8 rtc_halted;
static u8 rtc_carry;

/* How many complete 512-day spans the clock had run through at the last
 * latch.  The carry latches on each new span rather than on `days >= 512`:
 * the game clears the bit by writing DH, and a plain threshold would set it
 * straight back on the next latch and make it impossible to clear.
 */
static u32 rtc_span;

/* The five register bytes as this file last wrote them.
 *
 * The mapper's write handler (mbc3rtc_W) stores a clock-set write straight
 * into mapperdata and returns; it has no way to reach into the derived clock
 * here, so before this shadow existed the very next latch recomputed the time
 * from frametotal and threw the write away.  Games that set the clock -- the
 * whole point of #49 item 1 -- saw their values snap back one latch later.
 *
 * Rather than hook the write path (mbc3rtc_W runs off the memory-write table
 * with the gb_* registers live, so calling C from it means an ABI dance for
 * every RTC write), notice the write here: any byte that differs from what
 * this function last stored was written by the game, so adopt the register
 * file as the new time.  Registers the game did not touch still hold the
 * values from the previous latch, which is exactly what should be preserved.
 *
 * This also does the right thing across a savestate load: LoadMapper restores
 * mapperdata, the bytes no longer match the shadow, and the clock resumes
 * from the state's time instead of jumping to wherever frametotal points.
 *
 * The shadow starts all-zero to match mapperdata, which cart.s clears when the
 * cart is loaded, so a write that lands before the first latch is still seen.
 * The one case this cannot catch is a game that writes all five registers to
 * zero before ever latching: that is indistinguishable from the cleared boot
 * state.  Catching it would mean calling into this file from mbc3rtc_W, which
 * runs off the memory-write table with the gb_* registers live.
 */
static u8 rtc_shadow[5];

/* Called from cart.s when a cart is loaded, just after mapperdata is cleared.
 * The derived clock is file-static and would otherwise outlive the cart, so
 * the next game would start from the previous game's clock-set instead of the
 * boot epoch.
 */
void rtc_reset(void) {
    rtc_offset = BASE_SECONDS;
    rtc_frozen = 0;
    rtc_halted = 0;
    rtc_carry = 0;
    rtc_span = 0;
    rtc_shadow[0] = 0;
    rtc_shadow[1] = 0;
    rtc_shadow[2] = 0;
    rtc_shadow[3] = 0;
    rtc_shadow[4] = 0;
}

static u8 to_bcd(u8 val) {
    return ((val / 10) << 4) | (val % 10);
}

static u8 from_bcd(u8 val) {
    return ((val >> 4) & 0x0F) * 10 + (val & 0x0F);
}

static u32 elapsed_seconds(void) {
    return (u32)(((unsigned long long)frametotal *
                  GB_DOTS_PER_FRAME) >> GB_DOT_CLOCK_SHIFT);
}

static u32 rtc_now(void) {
    return rtc_halted ? rtc_frozen : elapsed_seconds() + rtc_offset;
}

static void rtc_set(u32 seconds) {
    if (rtc_halted) {
        rtc_frozen = seconds;
    } else {
        rtc_offset = seconds - elapsed_seconds();
    }
}

/* Rebuild the clock from register bytes the game wrote.  Hours, minutes and
 * seconds are BCD; hardware masks them to 5/6/6 bits and this does the same,
 * so a nonsense write cannot push the derived time somewhere it could not
 * otherwise reach.
 */
static void adopt_registers(void) {
    u32 days = mapperstate[RTC_DAYL] |
               ((mapperstate[RTC_DH] & DH_DAY_BIT8) << 8);
    u8 hours = from_bcd(mapperstate[RTC_HRS] & 0x3F) % 24;
    u8 minutes = from_bcd(mapperstate[RTC_MIN] & 0x7F) % 60;
    u8 seconds = from_bcd(mapperstate[RTC_SEC] & 0x7F) % 60;

    rtc_set(days * SECONDS_PER_DAY + hours * 3600u + minutes * 60u + seconds);
    /* `days` came out of a 9-bit register, so the clock is back inside its
     * first span; the next wrap is a fresh carry.
     */
    rtc_span = 0;
}

/* Software fallback, called from gettime (io.s) when no hardware RTC. */
void gettime_sw(void) {
    u32 total_seconds;
    u32 days;
    u32 remaining;
    u8 hours, minutes, seconds;
    u8 dh;
    u8 halt_now = (mapperstate[RTC_DH] & DH_HALT) != 0;

    /* The halt bit is a register the game owns, so read it back before
     * anything else: starting or stopping the clock changes which of
     * rtc_offset and rtc_frozen the time lives in, and adopt_registers has to
     * write into the right one.
     */
    if (halt_now != rtc_halted) {
        if (halt_now) {
            rtc_frozen = rtc_now();   /* stop where the clock stands */
            rtc_halted = 1;
        } else {
            rtc_halted = 0;
            rtc_offset = rtc_frozen - elapsed_seconds();  /* resume from it */
        }
    }

    /* The carry bit is sticky and the game clears it by writing DH, so track
     * the game's copy rather than deriving it fresh each latch.
     */
    if (mapperstate[RTC_DH] != rtc_shadow[1]) {
        rtc_carry = (mapperstate[RTC_DH] & DH_CARRY) != 0;
    }

    if (mapperstate[RTC_DAYL] != rtc_shadow[0] ||
        mapperstate[RTC_DH] != rtc_shadow[1] ||
        mapperstate[RTC_HRS] != rtc_shadow[2] ||
        mapperstate[RTC_MIN] != rtc_shadow[3] ||
        mapperstate[RTC_SEC] != rtc_shadow[4]) {
        adopt_registers();
    }

    total_seconds = rtc_now();

    days = total_seconds / SECONDS_PER_DAY;
    remaining = total_seconds % SECONDS_PER_DAY;
    hours = remaining / 3600;
    remaining %= 3600;
    minutes = remaining / 60;
    seconds = remaining % 60;

    /* Past day 511 the counter wraps and the carry latches, staying set until
     * the game clears it -- hardware behaviour, and the reason the counter is
     * masked below rather than allowed to run on into the halt bit.
     */
    if (days / DAY_COUNTER_SPAN > rtc_span) {
        rtc_carry = 1;
    }
    rtc_span = days / DAY_COUNTER_SPAN;

    dh = (u8)((days >> 8) & DH_DAY_BIT8);
    if (rtc_halted) dh |= DH_HALT;
    if (rtc_carry) dh |= DH_CARRY;

    mapperstate[RTC_DAYL] = days & 0xFF;
    mapperstate[RTC_DH] = dh;
    mapperstate[RTC_HRS] = to_bcd(hours);
    mapperstate[RTC_MIN] = to_bcd(minutes);
    mapperstate[RTC_SEC] = to_bcd(seconds);

    rtc_shadow[0] = mapperstate[RTC_DAYL];
    rtc_shadow[1] = mapperstate[RTC_DH];
    rtc_shadow[2] = mapperstate[RTC_HRS];
    rtc_shadow[3] = mapperstate[RTC_MIN];
    rtc_shadow[4] = mapperstate[RTC_SEC];
}
