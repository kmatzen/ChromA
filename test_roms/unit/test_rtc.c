/* Host-side unit tests for the software MBC3 RTC (src/rtc.c).
 *
 * The clock is a pure function of frametotal, so it can be checked exactly on
 * the host without a GBA toolchain, an emulator, or a ROM.  That matters for
 * the tick rate in particular: the old code divided the frame count by a flat
 * 60, and the GB actually runs at 4194304/70224 = 59.7275Hz.  The drift is
 * 0.45%, so demonstrating it through the emulator would need roughly five
 * minutes of emulated time before the seconds field disagreed reliably --
 * here it is one subtraction.
 */

#include <stdio.h>
#include <string.h>

#include "gba.h"

u32 frametotal;
u8 mapperstate[32];

void gettime_sw(void);
void rtc_reset(void);

/* Put the clock back where a cart load leaves it: mapperdata cleared (cart.s
 * does that) and the derived clock -- offset, halt state, register shadow --
 * back at its boot values.  The clock is no longer a pure function of
 * frametotal: it has to remember a clock-set write across latches, so each
 * test has to start from a known state rather than just setting frametotal.
 */
static void reset_clock(void) {
    memset(mapperstate, 0, sizeof(mapperstate));
    rtc_reset();
}

/* The DH register: bit 0 = day counter bit 8, bit 6 = halt, bit 7 = carry. */
#define DH_DAY_BIT8 0x01
#define DH_HALT     0x40
#define DH_CARRY    0x80

/* Smallest frame count whose converted time is at least `seconds`. */
static u32 frames_for(u32 seconds) {
    return (u32)(((unsigned long long)seconds * 4194304ULL + 70223ULL)
                 / 70224ULL);
}

static int failures;

#define CHECK(cond, msg) do {                                               \
    if (!(cond)) {                                                          \
        printf("  FAIL: %s\n", msg);                                        \
        failures++;                                                         \
    }                                                                       \
} while (0)

/* mapperdata layout, as gettime_sw and the clk_* readers in mappers.s agree */
#define RTC_DAY_LO 26
#define RTC_DAY_HI 27
#define RTC_HOURS  28
#define RTC_MINS   29
#define RTC_SECS   30

#define BASE_HOUR 10          /* the clock boots at 10:00:00 */

static u32 from_bcd(u8 v) {
    return (v >> 4) * 10 + (v & 0x0F);
}

/* Seconds since the epoch that the clock should read at a given frame count,
 * computed independently of rtc.c: a GB frame is 70224 dots of a 4194304Hz
 * clock. */
static u32 expected_seconds(u32 frames) {
    return (u32)(((unsigned long long)frames * 70224ULL) / 4194304ULL);
}

static u32 clock_seconds(void) {
    return from_bcd(mapperstate[RTC_HOURS] & 0x3F) * 3600
         + from_bcd(mapperstate[RTC_MINS]) * 60
         + from_bcd(mapperstate[RTC_SECS]);
}

/* mapperdata starts cleared rather than filled with a poison value: a byte
 * that differs from what gettime_sw last wrote is now taken to be a clock-set
 * write by the game, so 0xEE would read as "the game set the clock to
 * 0xEE:0xEE:0xEE".  Cleared is what cart.s actually leaves behind, and the
 * boot time is 10:00:00, so the checks below still prove every field was
 * written. */
static void test_boots_at_ten(void) {
    frametotal = 0;
    reset_clock();
    gettime_sw();
    CHECK(clock_seconds() == BASE_HOUR * 3600, "clock boots at 10:00:00");
    CHECK(mapperstate[RTC_DAY_LO] == 0, "day counter starts at 0");
    CHECK(mapperstate[RTC_DAY_HI] == 0, "day counter high bit starts at 0");
}

/* The point of the exercise: at 59.7275Hz the clock is ahead of a flat-60
 * clock by 0.45%, which is a whole second after about 3670 frames and grows
 * from there.  Each of these frame counts is one where the two disagree. */
static void test_tick_rate(void) {
    static const u32 frames[] = {
        60u * 60u * 10u,        /* 10 minutes of flat-60 frames */
        60u * 60u * 60u,        /* an hour */
        60u * 60u * 60u * 6u,   /* six hours */
    };
    unsigned i;

    for (i = 0; i < sizeof(frames) / sizeof(frames[0]); i++) {
        u32 f = frames[i];
        u32 want = expected_seconds(f);
        u32 flat60 = f / 60;
        char msg[128];

        frametotal = f;
        reset_clock();
        gettime_sw();

        u32 got = clock_seconds() - BASE_HOUR * 3600;

        snprintf(msg, sizeof(msg),
                 "at %u frames the clock reads %u s, expected %u "
                 "(a flat-60 divisor would give %u)",
                 (unsigned)f, (unsigned)got, (unsigned)want, (unsigned)flat60);
        CHECK(got == want, msg);

        /* Guard against the test being satisfied by the old behaviour: these
         * frame counts were chosen so the two divisors genuinely differ. */
        snprintf(msg, sizeof(msg),
                 "test vector at %u frames does not distinguish 59.7275Hz "
                 "from 60Hz", (unsigned)f);
        CHECK(want != flat60, msg);
    }
}

/* The product overflows 32 bits once the frame count passes ~61k, which is
 * only 17 minutes in -- so this is the case a 32-bit intermediate gets wrong,
 * and it is well inside what a real play session reaches. */
static void test_no_overflow_past_seventeen_minutes(void) {
    u32 f = 61163;   /* first frame count where frames * 70224 exceeds 2^32 */
    frametotal = f;
    reset_clock();
    gettime_sw();
    CHECK(clock_seconds() - BASE_HOUR * 3600 == expected_seconds(f),
          "the frame count that overflows a 32-bit product still converts");
}

static void test_fields_are_bcd_and_days_binary(void) {
    /* 1 day, 23:45:56 past the epoch.  The epoch is 10:00:00, so pick a frame
     * count that lands on a known wall-clock time and check the encodings. */
    u32 target = 86400u + 23u * 3600u + 45u * 60u + 56u - BASE_HOUR * 3600u;
    /* smallest frame count whose converted seconds equals `target` */
    u32 f = (u32)(((unsigned long long)target * 4194304ULL + 70223ULL) / 70224ULL);

    frametotal = f;
    reset_clock();
    gettime_sw();

    CHECK(expected_seconds(f) == target, "frame count lands on the target time");
    CHECK(mapperstate[RTC_SECS] == 0x56, "seconds are BCD");
    CHECK(mapperstate[RTC_MINS] == 0x45, "minutes are BCD");
    CHECK(mapperstate[RTC_HOURS] == 0x23, "hours are BCD");
    /* The day counter is a plain 9-bit binary count, not BCD -- clk_dayL in
     * mappers.s returns it unconverted, so 20 must read as 20, not 0x20. */
    CHECK(mapperstate[RTC_DAY_LO] == 1, "day counter is binary");
}

static void test_day_counter_is_binary_past_fifteen(void) {
    /* Day 20 is the case issue #49 called out: BCD-decoding a binary 20 gives
     * 14, so day-based events drift once the count passes 15. */
    u32 target = 20u * 86400u - BASE_HOUR * 3600u;
    u32 f = (u32)(((unsigned long long)target * 4194304ULL + 70223ULL) / 70224ULL);

    frametotal = f;
    reset_clock();
    gettime_sw();

    CHECK(mapperstate[RTC_DAY_LO] == 20, "day 20 is stored as binary 20");
    CHECK(mapperstate[RTC_DAY_HI] == 0, "day 20 sets no high bit");
}

static void test_day_high_bit(void) {
    u32 target = 300u * 86400u - BASE_HOUR * 3600u;   /* past 255 days */
    u32 f = (u32)(((unsigned long long)target * 4194304ULL + 70223ULL) / 70224ULL);

    frametotal = f;
    reset_clock();
    gettime_sw();

    CHECK(mapperstate[RTC_DAY_LO] == (300u & 0xFF), "day 300 low byte");
    CHECK(mapperstate[RTC_DAY_HI] == 1, "day 300 sets the high bit");
}

/* The register bytes as mbc3rtc_W leaves them after a clock-set: sec/min/hrs
 * BCD (the clk_* readers decode them with calctime), the day counter binary.
 */
static void write_clock(u8 day, u8 hours, u8 minutes, u8 seconds, u8 dh_extra) {
    mapperstate[RTC_DAY_LO] = day;
    mapperstate[RTC_DAY_HI] = dh_extra;
    mapperstate[RTC_HOURS] = ((hours / 10) << 4) | (hours % 10);
    mapperstate[RTC_MINS] = ((minutes / 10) << 4) | (minutes % 10);
    mapperstate[RTC_SECS] = ((seconds / 10) << 4) | (seconds % 10);
}

/* Issue #49 item 1's other half.  Making the registers writable was not enough
 * on its own: mbc3rtc_W stores the value into mapperdata, and the very next
 * latch used to recompute the whole clock from frametotal and throw the write
 * away.  A game that sets its clock saw the value snap back one latch later,
 * which is the symptom the issue actually describes.
 */
static void test_clock_set_survives_a_latch(void) {
    frametotal = 60u * 60u * 60u;          /* an hour into the session */
    reset_clock();
    gettime_sw();
    CHECK(clock_seconds() != 12 * 3600 + 30 * 60,
          "the clock does not already read the value the test is about to set");

    /* halt, write, unhalt, latch -- the order a real clock-set flow uses */
    write_clock(20, 12, 30, 0, DH_HALT);
    gettime_sw();
    CHECK(clock_seconds() == 12 * 3600 + 30 * 60,
          "a clock-set write survives the next latch");
    CHECK(mapperstate[RTC_DAY_LO] == 20, "the written day survives the latch");

    /* and the clock keeps running from where it was set */
    mapperstate[RTC_DAY_HI] &= (u8)~DH_HALT;
    gettime_sw();
    frametotal += frames_for(600);          /* ten minutes later */
    gettime_sw();
    CHECK(clock_seconds() == 12 * 3600 + 40 * 60,
          "the clock runs on from the value it was set to");
    CHECK(mapperstate[RTC_DAY_LO] == 20, "ten minutes does not move the day");
}

/* DH bit 6 halts the counters.  Before the halt bit was honoured the clock was
 * a pure function of frametotal, so it ticked straight through a halt. */
static void test_halt_freezes_the_clock(void) {
    u32 halted_at;

    frametotal = 60u * 60u * 60u;
    reset_clock();
    gettime_sw();

    mapperstate[RTC_DAY_HI] |= DH_HALT;
    gettime_sw();
    halted_at = clock_seconds();
    CHECK((mapperstate[RTC_DAY_HI] & DH_HALT) != 0, "the halt bit reads back");

    frametotal += frames_for(3600);         /* an hour of frames */
    gettime_sw();
    CHECK(clock_seconds() == halted_at, "a halted clock does not advance");

    mapperstate[RTC_DAY_HI] &= (u8)~DH_HALT;
    gettime_sw();
    CHECK(clock_seconds() == halted_at, "clearing halt does not jump the clock");
    CHECK((mapperstate[RTC_DAY_HI] & DH_HALT) == 0,
          "the halt bit reads back clear");

    frametotal += frames_for(60);
    gettime_sw();
    CHECK(clock_seconds() == halted_at + 60,
          "the clock advances again once halt is cleared");
}

/* DH bit 7 latches when the 9-bit day counter wraps and stays set until the
 * game clears it.  It used to read a flat 0, so a 512-day wrap was invisible.
 */
static void test_day_carry(void) {
    frametotal = frames_for(512u * 86400u - BASE_HOUR * 3600u);
    reset_clock();
    gettime_sw();

    CHECK((mapperstate[RTC_DAY_HI] & DH_CARRY) != 0,
          "day 512 latches the carry");
    CHECK(mapperstate[RTC_DAY_LO] == 0, "the day counter wraps to 0");
    CHECK((mapperstate[RTC_DAY_HI] & DH_DAY_BIT8) == 0,
          "the wrapped day counter clears bit 8");

    /* The carry is sticky, so it must survive latches that change nothing. */
    frametotal += frames_for(60);
    gettime_sw();
    CHECK((mapperstate[RTC_DAY_HI] & DH_CARRY) != 0, "the carry is sticky");

    /* ...but the game clears it by writing DH, and it must then stay clear
     * rather than being re-derived from "the day count is past 512". */
    mapperstate[RTC_DAY_HI] &= (u8)~DH_CARRY;
    gettime_sw();
    CHECK((mapperstate[RTC_DAY_HI] & DH_CARRY) == 0,
          "the game can clear the carry");
    frametotal += frames_for(60);
    gettime_sw();
    CHECK((mapperstate[RTC_DAY_HI] & DH_CARRY) == 0,
          "the cleared carry stays clear");
}

/* Issue #49 item 4's companion: a savestate load restores mapperdata behind
 * this file's back, and the clock has to resume from the state's time rather
 * than snapping to wherever frametotal happens to point. */
static void test_savestate_restore_resumes_from_the_state(void) {
    frametotal = 60u * 60u * 60u;
    reset_clock();
    gettime_sw();

    /* LoadMapper drops a saved register file straight into mapperdata. */
    write_clock(5, 3, 4, 5, 0);
    gettime_sw();
    CHECK(clock_seconds() == 3 * 3600 + 4 * 60 + 5,
          "a restored register file becomes the current time");
    CHECK(mapperstate[RTC_DAY_LO] == 5, "the restored day survives");
}

/* A cart load clears mapperdata, but the derived clock lives in file statics
 * that outlive it -- so without rtc_reset the next game would inherit the last
 * game's clock-set. */
static void test_cart_load_resets_the_clock(void) {
    frametotal = 60u * 60u * 60u;
    reset_clock();
    gettime_sw();
    write_clock(20, 12, 30, 0, DH_HALT);
    gettime_sw();
    CHECK(clock_seconds() == 12 * 3600 + 30 * 60, "clock set for the first cart");

    frametotal = 0;
    reset_clock();                  /* as cart.s does on the next cart load */
    gettime_sw();
    CHECK(clock_seconds() == BASE_HOUR * 3600,
          "a new cart boots at 10:00:00 rather than inheriting the last clock");
    CHECK(mapperstate[RTC_DAY_LO] == 0, "a new cart starts at day 0");
    CHECK((mapperstate[RTC_DAY_HI] & DH_HALT) == 0,
          "a new cart is not left halted");
}

int main(void) {
    printf("=== Software RTC unit tests ===\n");

    test_boots_at_ten();
    test_tick_rate();
    test_no_overflow_past_seventeen_minutes();
    test_fields_are_bcd_and_days_binary();
    test_day_counter_is_binary_past_fifteen();
    test_day_high_bit();
    test_clock_set_survives_a_latch();
    test_halt_freezes_the_clock();
    test_day_carry();
    test_savestate_restore_resumes_from_the_state();
    test_cart_load_resets_the_clock();

    if (failures == 0) {
        printf("  All RTC conversions correct\n");
        return 0;
    }
    printf("  %d check(s) failed\n", failures);
    return 1;
}
