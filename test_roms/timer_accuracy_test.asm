; Timer Accuracy Test ROM
;
; Tests sub-scanline DIV register accuracy.
; Reads DIV, executes exactly 256 T-cycles of NOPs (64 NOPs × 4 cycles),
; reads DIV again.  The delta should be exactly 1 (DIV increments every
; 256 T-cycles).
;
; Result at C000: DIV before
; Result at C001: DIV after
; Result at C002: delta (should be 1)
; Sentinel at C010: 0xFF when complete

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Main", ROM0[$0150]
Main:
    di
    ld sp, $FFFE

    ; Clear results
    xor a
    ld [$C000], a
    ld [$C001], a
    ld [$C002], a
    ld [$C010], a

    ; Reset DIV by writing to it
    xor a
    ldh [$04], a

    ; Small delay to let DIV start from a known state
    nop
    nop
    nop
    nop

    ; Read DIV (before)
    ldh a, [$04]        ; 12 cycles
    ld [$C000], a       ; 16 cycles
    ld b, a             ; 4 cycles — save for delta

    ; Execute exactly 256 T-cycles of NOPs = 64 NOPs
    ; (minus overhead: the ldh+ld+ld above = 32 cycles,
    ;  and the ldh below = 12 cycles.  Total overhead = 44 cycles.
    ;  We want 256 cycles between the two DIV reads.
    ;  256 - 44 = 212 cycles = 53 NOPs)
    REPT 53
    nop                 ; 4 cycles each = 212 cycles
    ENDR

    ; Read DIV (after)
    ldh a, [$04]        ; 12 cycles
    ld [$C001], a       ; store

    ; Compute delta
    sub a, b            ; a = after - before
    ld [$C002], a       ; store delta

    ; Sentinel
    ld a, $FF
    ld [$C010], a

.loop:
    halt
    nop
    jr .loop
