; Timer overflow / DIV-write glitch regression test (issue #44)
;
; Two independent subtests, neither of which needs cycle-exact code.
;
; A. TIMA must stay inside [TMA, 255].
;    Once TIMA has overflowed it reloads from TMA, so with TMA=$F6 every
;    subsequent reading is in $F6..$FF -- a hardware invariant, no timing
;    assumptions.  checkTimerIRQ used to detect a single carry per scanline
;    and then store TMA<<24 flat, and _FF05R projected the sub-scanline
;    value modulo 256; a scanline is ~28 periods wide at TAC=01, so both
;    produced readings far below TMA.
;
; B. Writing DIV while the selected counter bit is 1 clocks TIMA.
;    Two runs of the SAME length: 64 back-to-back DIV writes, versus 64x3
;    NOPs (`ldh [$FF04],a` and 3 NOPs are both 12 T-cycles).  Everything
;    else about the two runs is identical, so the difference is exactly the
;    number of glitch increments.  The old code tested dividereg bits
;    9/15/13/11, which are always zero at that scaling, so the difference
;    was zero.
;
; Results in cart RAM (dumped as the .sav):
;   A000  lowest TIMA seen in A   -- must be $F6
;   A001  highest TIMA seen in A  -- must be $FF
;   A002  TIMA after 64 DIV writes            (B1)
;   A003  TIMA after the same span of NOPs    (B2)
;   A00F  $5A when both subtests have run
;
; Build:
;   rgbasm -o timer.o test_roms/timer_overflow_test.asm
;   rgblink -o test_roms/timer_overflow_test.gb timer.o
;   rgbfix -v -p 0 -t "TIMEROVF" -m 0x1B -r 2 test_roms/timer_overflow_test.gb

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Vars", WRAM0[$C000]
MinVal: db
MaxVal: db

SECTION "Main", ROM0[$0150]
Main:
    di
    ld sp, $FFFE
    ld a, $0A
    ld [$0000], a          ; MBC5: enable cart RAM
    xor a
    ld [$4000], a          ; MBC5: select RAM bank 0

    ld hl, $A000
    ld b, 16
.clear_results:
    xor a
    ld [hl+], a
    dec b
    jr nz, .clear_results

    ; ---- A: TIMA must never read below TMA ------------------------------
    xor a
    ldh [$FF07], a         ; TAC: timer off while we set up
    ld a, $F6
    ldh [$FF06], a         ; TMA = $F6  -> a 10-tick reload period
    ldh [$FF05], a         ; TIMA = $F6 -> already inside the period
    xor a
    ldh [$FF04], a         ; DIV = 0
    ld a, $05
    ldh [$FF07], a         ; TAC = enabled, 16 T-cycles per tick

    ld a, $FF
    ld [MinVal], a
    xor a
    ld [MaxVal], a

    ld bc, $2000
.sample:
    ldh a, [$FF05]
    ld hl, MinVal
    cp [hl]
    jr nc, .not_min
    ld [hl], a
.not_min:
    ld hl, MaxVal
    cp [hl]
    jr c, .not_max
    ld [hl], a
.not_max:
    dec bc
    ld a, b
    or c
    jr nz, .sample

    ld a, [MinVal]
    ld [$A000], a
    ld a, [MaxVal]
    ld [$A001], a

    ; ---- B1: 64 DIV writes ----------------------------------------------
    xor a
    ldh [$FF07], a         ; timer off
    ldh [$FF06], a         ; TMA = 0, so nothing wraps during the run
    ldh [$FF05], a         ; TIMA = 0
    ldh [$FF04], a         ; DIV = 0
    ld a, $05
    ldh [$FF07], a         ; TAC = enabled, 16 T-cycles per tick
    xor a
    REPT 64
    ldh [$FF04], a         ; 12 T-cycles; resets DIV before it can tick
    ENDR
    ldh a, [$FF05]
    ld [$A002], a

    ; ---- B2: the same span with no DIV writes ---------------------------
    xor a
    ldh [$FF07], a         ; timer off
    ldh [$FF06], a         ; TMA = 0
    ldh [$FF05], a         ; TIMA = 0
    ldh [$FF04], a         ; DIV = 0
    ld a, $05
    ldh [$FF07], a
    xor a
    REPT 192
    nop                    ; 192 x 4 = 768 T-cycles = 64 x 12
    ENDR
    ldh a, [$FF05]
    ld [$A003], a

    xor a
    ldh [$FF07], a         ; timer off again

    ld a, $5A
    ld [$A00F], a
.done:
    jr .done
