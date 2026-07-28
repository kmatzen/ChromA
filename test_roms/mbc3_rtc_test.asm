; MBC3 RTC register test (issue #49, items 1-3)
;
;   1. The RTC registers were read-only: selecting one installed empty_W, so
;      the clock-set flows real games use had every write dropped and the
;      value snapped straight back.
;   2. The day counter is a plain 9-bit binary count, but the reader ran it
;      through calctime, which decodes BCD -- day 20 read back as 14, so
;      day-based events drifted once the count passed 15.
;   3. The DH register was hardwired to 0: no day bit 8, no halt bit, no
;      512-day carry.  gettime_sw was already maintaining bit 8 with nothing
;      reading it.
;
; Each register is written, then read straight back with no latch in
; between, so nothing here depends on the clock advancing.  Between steps
; the cart switches back to RAM bank 0 to store the result, because while an
; RTC register is selected A000-BFFF *is* the register, not RAM.
;
; Results in cart RAM:
;   A000  $5A control: plain SRAM round-trip, works on both builds
;   A001  seconds  written 42   -- 42 fixed, running clock (not 42) broken
;   A002  minutes  written 37   -- 37 fixed
;   A003  hours    written 21   -- 21 fixed
;   A004  day low  written 200  -- 200 ($C8) fixed, 0 broken
;   A005  day high written $81  -- $81 fixed, 0 broken (hardwired)
;   A00F  $5A when every step has run
;
; Build:
;   rgbasm -o rtc.o test_roms/mbc3_rtc_test.asm
;   rgblink -o test_roms/mbc3_rtc_test.gb rtc.o
;   rgbfix -v -p 0 -t "MBC3RTC" -m 0x10 -r 2 test_roms/mbc3_rtc_test.gb

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Main", ROM0[$0150]
Main:
    di
    ld sp, $FFFE

    ld a, $0A
    ld [$0000], a          ; enable RAM / RTC access
    xor a
    ld [$4000], a          ; select RAM bank 0

    ld hl, $A000
    ld b, 16
    xor a
.clear:
    ld [hl+], a
    dec b
    jr nz, .clear

    ; ---- control: ordinary SRAM still works -----------------------------
    ld a, $5A
    ld [$A000], a
    ld a, [$A000]
    ld c, a
    xor a
    ld [$4000], a
    ld a, c
    ld [$A000], a

    ; ---- each RTC register: write, read back, stash ---------------------
    ld b, $08              ; RTC register
    ld c, 42               ; value to write
    ld d, $01              ; result slot (A001)
    call RtcRoundTrip

    ld b, $09
    ld c, 37
    ld d, $02
    call RtcRoundTrip

    ld b, $0A
    ld c, 21
    ld d, $03
    call RtcRoundTrip

    ld b, $0B
    ld c, 200              ; day low: binary, well past the BCD-decode limit
    ld d, $04
    call RtcRoundTrip

    ld b, $0C
    ld c, $81              ; day bit 8 + carry
    ld d, $05
    call RtcRoundTrip

    xor a
    ld [$4000], a
    ld a, $5A
    ld [$A00F], a
.done:
    jr .done

; b = RTC register to select, c = value to write, d = result offset in RAM.
; Leaves RAM bank 0 selected.
RtcRoundTrip:
    ld a, b
    ld [$4000], a          ; select the RTC register
    ld a, c
    ld [$A000], a          ; write it
    ld a, [$A000]          ; read it straight back, no latch
    ld e, a

    xor a
    ld [$4000], a          ; back to RAM bank 0 so the store lands in RAM
    ld h, $A0
    ld l, d
    ld [hl], e
    ret
