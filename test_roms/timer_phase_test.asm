; Timer phase-coherence regression test (issue #44 item 1)
;
; checkTimerIRQ used to store a flat TMA<<24 on overflow, throwing away the
; sub-period remainder.  The timer therefore restarted from phase zero at
; every scanline boundary that happened to contain an overflow.
;
; This needs no cycle-exact code to detect.  The timer is a free-running
; counter with a fixed period, and the sampling loop below is a fixed number
; of T-cycles, so the sequence of TIMA readings MUST be periodic -- that is a
; property of any free-running counter sampled at a regular interval, not an
; assumption about a particular emulator's timing.  An implementation that
; resets the sub-period phase at scanline boundaries cannot produce a
; periodic sequence, because a scanline (456 T-cycles) is not a whole number
; of timer periods.
;
; TAC=01 selects a 16 T-cycle period and TMA=$FE leaves TIMA a two-step
; cycle, so 456 cycles is 28.5 periods: the true phase alternates from one
; scanline to the next, which is exactly what a flat reload destroys.
;
; Measured: mGBA's Game Boy core gives minimal period 4.  ChromA gave 19
; (44 of 60 period-4 comparisons mismatched) before the fix and 4 after.
;
; Note this deliberately checks the *shape* of the sequence, not the values.
; Matching mGBA sample-for-sample additionally needs the 4-cycle TIMA==0
; reload window (issue #44 item 3), which is still open -- mGBA reports $00
; during it and ChromA never does.
;
; Results in cart RAM (dumped as the .sav):
;   A000..A03F  64 TIMA samples at a fixed interval
;   A040        $5A once the run has completed
;
; Build:
;   rgbasm -o timer_phase.o test_roms/timer_phase_test.asm
;   rgblink -o test_roms/timer_phase_test.gb timer_phase.o
;   rgbfix -v -p 0 -t "TIMERPHASE" -m 0x1B -r 2 test_roms/timer_phase_test.gb

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Main", ROM0[$0150]
Main:
    di
    ld sp, $FFFE

    ld a, $0A
    ld [$0000], a          ; MBC5: enable cart RAM
    xor a
    ld [$4000], a          ; MBC5: RAM bank 0

    ; clear the 64 sample slots and the completion marker
    ld hl, $A000
    ld bc, 65
.clear:
    xor a
    ld [hl+], a
    dec bc
    ld a, b
    or c
    jr nz, .clear

    ; ---- program the timer ----------------------------------------------
    xor a
    ldh [$FF04], a         ; reset DIV, and with it the internal counter
    ld a, $FE
    ldh [$FF06], a         ; TMA = $FE
    ldh [$FF05], a         ; TIMA = $FE
    ld a, $05
    ldh [$FF07], a         ; TAC = enabled, 16 T-cycle period

    ; ---- sample TIMA at a fixed interval --------------------------------
    ; Every iteration is the same number of T-cycles, so the readings are a
    ; regular sampling of the counter.  The interval is not a divisor of a
    ; scanline, which is what makes a lost per-scanline phase visible.
    ld hl, $A000
    ld b, 64
.sample:
    ldh a, [$FF05]         ; 12
    ld [hl+], a            ; 8

    ld c, 8                ; 8    fixed delay
.delay:
    dec c                  ; 4
    jr nz, .delay          ; 12 taken / 8 fallthrough

    dec b                  ; 4
    jr nz, .sample         ; 12 / 8

    ld a, $5A
    ld [$A040], a          ; completion marker
.done:
    jr .done
