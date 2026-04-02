; EI Delay Test ROM
DEF rIE  EQU $FFFF
DEF rIF  EQU $FF0F

SECTION "VBlank Vector", ROM0[$0040]
    jp VBlankHandler

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Main", ROM0[$0150]
Main:
    di
    ld sp, $FFFE
    xor a
    ldh [rIF], a
    ldh [rIE], a

    ld hl, $C000
    xor a
    ld [hl+], a
    ld [hl+], a
    ld [hl+], a
    ld [hl+], a

    ld hl, $C000
    ld a, $01
    ldh [rIE], a
    ld a, $01
    ldh [rIF], a

    ; Test: EI then absolute write (no HL involvement)
    ; ISR uses HL so it won't interfere with the absolute write
    ld a, $01
    ei
    ld [$C000], a       ; Absolute write 0x01 to C000.
                        ; With delay: this completes before ISR
                        ; Without delay: ISR fires first

    ; After ISR, write 0x03
    ld a, $03
    ld [$C001], a       ; absolute write

    di
    ld a, $FF
    ld [$C010], a

.loop:
    halt
    nop
    jr .loop

SECTION "VBlank Handler", ROM0[$0200]
VBlankHandler:
    push af
    ; Write 0x02 to C000 — if delay works, this overwrites 0x01 with 0x02
    ; If no delay, this writes 0x02 first, then main writes 0x01
    ld a, $02
    ld [$C000], a
    pop af
    reti
