; Sweep TIMA against elapsed time from a known origin (issue #44 item 1).
;
; mooneye's timer/tim00 is XFAIL for ChromA but not "unusable", i.e. mGBA
; passes it -- so mGBA is a valid reference for TIMA behaviour, and the
; disagreement can be localised instead of guessed at.
;
; For each index i in 0..255 the probe re-establishes a known origin (timer
; off, TMA/TIMA zeroed, DIV reset), enables the timer at TAC=$04 (period 1024
; cycles), spins for i iterations of a fixed 20-cycle loop, reads TIMA, and
; stores it.  The result is a 256-point staircase of TIMA against elapsed
; cycles; comparing it byte-for-byte against mGBA's shows exactly which step
; is misplaced, rather than only that some sample is one too high.
;
; Results in cart RAM: A000..A0FF = TIMA at each delay, A1FF = $5A when done.

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Main", ROM0[$0150]
Main:
    di
    ld sp, $FFFE
    ld a, $0A
    ld [$0000], a
    xor a
    ld [$4000], a

    ld hl, $A000
    ld c, 0                 ; c = delay index
.sample:
    ; --- re-establish a known origin -------------------------------------
    xor a
    ldh [$FF07], a          ; TAC: timer off
    ldh [$FF06], a          ; TMA = 0
    ldh [$FF05], a          ; TIMA = 0
    ldh [$FF04], a          ; DIV reset -- the divider phase starts here
    ld a, $04
    ldh [$FF07], a          ; TAC: enabled, select 00 (1024-cycle period)

    ; --- spin for c iterations of a 20-cycle loop ------------------------
    ld b, c
    inc b                   ; b is at least 1; index 0 spins once
.delay:
    nop
    dec b
    jr nz, .delay

    ldh a, [$FF05]          ; TIMA after the delay
    ld [hl+], a

    inc c
    jr nz, .sample

    xor a
    ldh [$FF07], a          ; leave the timer off
    ld a, $5A
    ld [$A1FF], a
.done:
    jr .done
