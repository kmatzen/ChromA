; STOP resets the divider (issue #56 item 4).
;
; Executing STOP clears the internal DIV counter, so FF04 reads 0 straight
; afterwards.  ChromA's _10 handler only performs the speed switch and skips
; the operand byte; nothing touches dividereg, so DIV carries straight on
; across the STOP.
;
; The probe runs in CGB mode with a speed switch armed (KEY1 bit 0), because
; that is the STOP that *resumes*: a STOP with no armed switch puts the CPU in
; stop mode until a joypad interrupt, which would hang the probe under any
; emulator that implements it properly.
;
; DIV is deliberately allowed to run up to a large value first, so "reset"
; and "kept running" are far apart and a couple of cycles of slop between
; emulators cannot be mistaken for either.
;
; Results in cart RAM (bank 0):
;   A000  DIV before the STOP    (large, non-zero)
;   A001  DIV after the STOP     0 on hardware; ~unchanged if STOP ignores it
;   A002  KEY1 after the STOP    bit 7 set once running double speed
;   A00F  $5A when the probe ran to completion
;
; Build:
;   rgbasm -o stopdiv.o test_roms/stop_div_test.asm
;   rgblink -o test_roms/stop_div_test.gb stopdiv.o
;   rgbfix -v -p 0 -t "STOPDIV" -c -m 0x1B -r 2 test_roms/stop_div_test.gb

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Main", ROM0[$0150]
Main:
    di
    ld sp, $FFFE

    ld a, $0A
    ld [$0000], a          ; enable cart RAM
    xor a
    ld [$4000], a          ; RAM bank 0
    ld [$A000], a
    ld [$A001], a
    ld [$A002], a
    ld [$A00F], a

    ; Let DIV climb well away from zero.  DIV ticks every 256 T-cycles, so
    ; this loop is sized to leave it in the middle of its range rather than
    ; near a wrap, where "reset" and "not reset" could look alike.
    ld bc, 3000
.spin:
    dec bc
    ld a, b
    or c
    jr nz, .spin

    ldh a, [$FF04]         ; DIV before
    ld d, a

    ; Arm the speed switch and STOP.  In CGB mode this switches speed and
    ; execution continues at the instruction after the operand byte.
    ld a, $01
    ldh [$FF4D], a
    stop

    ldh a, [$FF04]         ; DIV after
    ld e, a
    ldh a, [$FF4D]         ; KEY1: bit 7 reflects the current speed
    ld h, a

    ld a, d
    ld [$A000], a
    ld a, e
    ld [$A001], a
    ld a, h
    ld [$A002], a
    ld a, $5A
    ld [$A00F], a
.done:
    jr .done
