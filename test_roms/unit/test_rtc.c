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

static void test_boots_at_ten(void) {
    frametotal = 0;
    memset(mapperstate, 0xEE, sizeof(mapperstate));
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
        memset(mapperstate, 0, sizeof(mapperstate));
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
    memset(mapperstate, 0, sizeof(mapperstate));
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
    memset(mapperstate, 0, sizeof(mapperstate));
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
    memset(mapperstate, 0, sizeof(mapperstate));
    gettime_sw();

    CHECK(mapperstate[RTC_DAY_LO] == 20, "day 20 is stored as binary 20");
    CHECK(mapperstate[RTC_DAY_HI] == 0, "day 20 sets no high bit");
}

static void test_day_high_bit(void) {
    u32 target = 300u * 86400u - BASE_HOUR * 3600u;   /* past 255 days */
    u32 f = (u32)(((unsigned long long)target * 4194304ULL + 70223ULL) / 70224ULL);

    frametotal = f;
    memset(mapperstate, 0, sizeof(mapperstate));
    gettime_sw();

    CHECK(mapperstate[RTC_DAY_LO] == (300u & 0xFF), "day 300 low byte");
    CHECK(mapperstate[RTC_DAY_HI] == 1, "day 300 sets the high bit");
}

int main(void) {
    printf("=== Software RTC unit tests ===\n");

    test_boots_at_ten();
    test_tick_rate();
    test_no_overflow_past_seventeen_minutes();
    test_fields_are_bcd_and_days_binary();
    test_day_counter_is_binary_past_fifteen();
    test_day_high_bit();

    if (failures == 0) {
        printf("  All RTC conversions correct\n");
        return 0;
    }
    printf("  %d check(s) failed\n", failures);
    return 1;
}
