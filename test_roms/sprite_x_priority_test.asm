; DMG sprite-vs-sprite priority is by X coordinate (issue #53 item 3).
;
; On DMG, when two sprites overlap the one with the smaller X draws on top,
; regardless of OAM order; ties are broken by the lower OAM index.  On CGB the
; OAM index alone decides.  ChromA used the CGB rule in both modes.
;
; Two 8x8 sprites are placed so that they overlap by 4 pixels, with the
; *later* OAM entry given the *smaller* X:
;
;   OAM[0]: X=60, tile 1 (solid colour 3)   -> screen x 52..59
;   OAM[1]: X=56, tile 2 (solid colour 1)   -> screen x 48..55
;
; so the overlap is screen x 52..55, and the three bands are:
;
;   48..51  only OAM[1]  (colour 1)
;   52..55  overlap      <- the measurement
;   56..59  only OAM[0]  (colour 3)
;
; If the overlap matches the left band the X rule won (correct for DMG); if it
; matches the right band the OAM order won.  Comparing bands *within* one
; frame keeps this independent of how any given emulator colours DMG output.
;
; Build:
;   rgbasm -o s.o test_roms/sprite_x_priority_test.asm
;   rgblink -o test_roms/sprite_x_priority_test.gb s.o
;   rgbfix -v -p 0 -t "SPRITEX" -m 0x00 test_roms/sprite_x_priority_test.gb

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Main", ROM0[$0150]
Main:
    di
    ld sp, $FFFE

    ; LCD off so VRAM/OAM can be written freely
    xor a
    ldh [$FF40], a

    ; Tile 1 = solid colour 3, tile 2 = solid colour 1.  Each tile is 16
    ; bytes: two bitplanes per row.  Colour 3 = both planes set, colour 1 =
    ; low plane only.
    ld hl, $8010            ; tile 1
    ld b, 8
.tile1:
    ld a, $FF
    ld [hl+], a             ; low plane
    ld a, $FF
    ld [hl+], a             ; high plane
    dec b
    jr nz, .tile1

    ld hl, $8020            ; tile 2
    ld b, 8
.tile2:
    ld a, $FF
    ld [hl+], a             ; low plane
    xor a
    ld [hl+], a             ; high plane = 0 -> colour 1
    dec b
    jr nz, .tile2

    ; Clear OAM, then place the two sprites.
    ld hl, $FE00
    ld b, 160
    xor a
.clroam:
    ld [hl+], a
    dec b
    jr nz, .clroam

    ld hl, $FE00
    ld a, 80                ; OAM[0]: Y
    ld [hl+], a
    ld a, 60                ; X = 60
    ld [hl+], a
    ld a, 1                 ; tile 1 (colour 3)
    ld [hl+], a
    xor a
    ld [hl+], a             ; attrs

    ld a, 80                ; OAM[1]: Y
    ld [hl+], a
    ld a, 56                ; X = 56, smaller than OAM[0]
    ld [hl+], a
    ld a, 2                 ; tile 2 (colour 1)
    ld [hl+], a
    xor a
    ld [hl+], a             ; attrs

    ; Palettes: BGP all colour 0 so the background stays uniform behind the
    ; sprites; OBP0 identity so colours 1 and 3 stay distinct.
    xor a
    ldh [$FF47], a
    ld a, %11100100
    ldh [$FF48], a

    ; LCD on, sprites on, 8x8, BG on
    ld a, $93
    ldh [$FF40], a
.done:
    jr .done
