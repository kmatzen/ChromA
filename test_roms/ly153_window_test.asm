; Measure how long LY reads 153 (issue #52 item 6).
;
; Line 153 is special: LY reads 153 for only ~4 T-cycles and then reads 0 for
; the rest of the line, still inside VBlank.  A tight polling loop therefore
; catches the value 153 in a fixed fraction of frames, and that fraction is
; proportional to the width of the window -- so counting hits over a fixed,
; deterministic number of iterations distinguishes a 4-cycle window from an
; 8-cycle one without needing sub-instruction timing.
;
; The loop is padded so its period is 68 T-cycles; gcd(68, 70224) = 4, which
; makes the sampling phase visit every 4-cycle offset within a frame.  A
; 4-cycle window is then hit once per sweep and an 8-cycle window twice, so
; the counts differ by 2x.
;
; Result: 16-bit hit count at $A000 (little endian), $5A at $A002 when done.
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
    ld [$4000], a
    ld [$A000], a
    ld [$A001], a
    ld [$A002], a

    ld hl, 0               ; hit counter
    ld b, 24               ; outer iterations
.outer:
    ld de, 0               ; inner counter (65536 iterations)
.loop:
    ldh a, [$FF44]           ; LY
    cp 153
    jr nz, .skip
    inc hl
.skip:
    nop                    ; pad the loop to 68 cycles on the miss path:
    nop                    ; gcd(68, 70224) = 4, so the sample phase sweeps
                           ; every 4-cycle offset in the frame instead of
                           ; stepping in 12s and straddling the window
    dec de
    ld a, d
    or e
    jr nz, .loop
    dec b
    jr nz, .outer

    ld a, l
    ld [$A000], a
    ld a, h
    ld [$A001], a
    ld a, $5A
    ld [$A002], a
.done:
    jr .done
