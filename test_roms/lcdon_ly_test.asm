; Map LY against time since the LCD was enabled (issue #145).
;
; mooneye's lcdon_timing-GS reports a single point -- "at cycle $82 LY should
; be $01 and reads $00" -- which says the first line is wrong but not how.
; This samples the whole curve instead: for every delay from 0 to 255 machine
; cycles after the FF40 write that enables the LCD, read LY once and record it.
;
; Comparing that array against mGBA's shows where the two diverge and by how
; much, which distinguishes the two candidate causes #145 leaves open -- a
; first line of the wrong length (the step moves) from LY being re-zeroed
; after it increments (the step is right but the value drops back).
;
; The delay is exact rather than approximate: each sample jumps into a sled of
; 256 NOPs at NopSledEnd - b, so exactly b NOPs run between the enable and the
; read, and one NOP is one machine cycle -- the same unit mooneye counts in.
;
; Results: LY[b] at $A000+b, $5A at $A100 when the sweep completes.

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

    ld b, 0
.each:
    ; LCD off, then a fixed settle so every sample starts from the same
    ; state.  Turning the LCD off resets the PPU and holds LY at 0, so the
    ; starting point does not depend on where the previous sample ended.
    xor a
    ldh [$FF40], a
    ld c, 0
.settle:
    dec c
    jr nz, .settle

    ; hl = NopSledEnd - b, so exactly b NOPs run before the LY read.
    ld hl, NopSledEnd
    ld a, l
    sub b
    ld l, a
    ld a, h
    sbc 0
    ld h, a

    ld a, $81              ; LCD on, BG on
    ldh [$FF40], a         ; <-- the enable instant
    jp hl

.after:
    ld h, $A0
    ld l, b
    ld [hl], a             ; LY sampled b machine cycles after the enable
    inc b
    jr nz, .each

    ld a, $5A
    ld [$A100], a
.done:
    jr .done

SECTION "Sled", ROM0[$0400]
NopSled:
    REPT 256
    nop
    ENDR
NopSledEnd:
    ldh a, [$FF44]         ; LY
    jp Main.after
