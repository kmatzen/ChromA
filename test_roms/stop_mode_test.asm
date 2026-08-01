; STOP with no armed speed switch enters stop mode and wakes on the joypad
; (issue #152).
;
; This is the other half of stop_div_test.asm.  That probe deliberately arms
; the CGB speed switch first, because that is the STOP that *resumes* on its
; own; it therefore says nothing about what a plain STOP does.  ChromA used to
; treat a plain STOP as a NOP that skips a byte, so the CPU ran straight on.
;
; Hardware parks the CPU until a joypad line selected in FF00 is driven low,
; with no dependence on IE, IF or IME -- so this probe runs with interrupts
; disabled on purpose.  A joypad *interrupt* waking a HALT is a different
; mechanism and is covered by joypad_irq_test.asm.
;
; The probe is read twice by test_stop_mode.py: once with no input at all,
; where it must NOT finish, and once with a button held, where it must.  A
; build that ignores STOP finishes both times; a build that parks but never
; wakes finishes neither.  Only a correct one splits them, which is why the
; "did not finish" arm is an assertion here rather than a timeout.
;
; FF00 is left with both select lines driven low ($00), so any button at all
; pulls one of the four input lines low.  That is the widest possible wake
; condition and keeps the probe independent of the D-pad/button mapping.
;
; Results in cart RAM (bank 0):
;   A000  $11 once the STOP has been reached (always set)
;   A001  $22 once execution has passed the STOP (only if it woke)
;   A00F  $5A when the probe ran to completion
;
; Build:
;   rgbasm -o stopmode.o test_roms/stop_mode_test.asm
;   rgblink -o test_roms/stop_mode_test.gb stopmode.o
;   rgbfix -v -p 0 -t "STOPMODE" -c -m 0x1B -r 2 test_roms/stop_mode_test.gb

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
    ld [$A00F], a

    ; Select both the direction and the button line.  Bits 4 and 5 are the
    ; select lines and are active low, so $00 selects both at once and any
    ; press shows up on one of bits 0-3.
    xor a
    ldh [$FF00], a

    ; Give the frame loop a little room before parking, so the runner's
    ; joypad state has been sampled at least once with nothing held.  A
    ; build that never parks would otherwise be indistinguishable from one
    ; that parked and was woken by a stale press.
    ld bc, 2000
.spin:
    dec bc
    ld a, b
    or c
    jr nz, .spin

    ld a, $11
    ld [$A000], a          ; reached the STOP

    stop

    ld a, $22
    ld [$A001], a          ; execution resumed past the STOP
    ld a, $5A
    ld [$A00F], a
.done:
    jr .done
