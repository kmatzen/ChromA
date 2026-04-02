; Sprite Limit Test ROM
;
; Places 12 sprites on the same scanline (Y=80).
; Real GB hardware shows only the first 10 (by OAM order).
; The 11th and 12th sprites should be hidden.
;
; Sprite layout: 12 sprites at X=8,16,24,...,96 all at Y=80
; Tile 0 is set to a solid block pattern.
; After DMA, sprites 0-9 should be visible, 10-11 should be missing.
;
; Test verification: dump GBA OAM and check that sprites 10-11 have Y=160
; (hidden) while sprites 0-9 have valid Y positions.

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Main", ROM0[$0150]
Main:
    di
    ld sp, $FFFE

    ; Wait for VBlank before writing to VRAM
    call WaitVBlank

    ; Turn off LCD for safe VRAM access
    xor a
    ldh [$40], a        ; LCDC = 0 (LCD off)

    ; Write a solid tile to tile 0 (at $8000)
    ld hl, $8000
    ld a, $FF           ; all pixels set
    ld b, 16            ; 16 bytes per tile
.fillTile:
    ld [hl+], a
    dec b
    jr nz, .fillTile

    ; Set up OAM in WRAM at $C100 (will DMA to OAM)
    ld hl, $C100

    ; Sprites 0-11: all at Y=96 (screen line 80), X increments by 8
    ; Y=96 means top of sprite at scanline 96-16=80
    ld b, 12            ; 12 sprites
    ld c, 8             ; starting X position
    ld d, 96            ; Y position (scanline 80)
.setupSprites:
    ld a, d
    ld [hl+], a         ; Y
    ld a, c
    ld [hl+], a         ; X
    xor a
    ld [hl+], a         ; tile 0
    ld [hl+], a         ; attributes (no flip, palette 0)
    ld a, c
    add a, 8
    ld c, a             ; X += 8
    dec b
    jr nz, .setupSprites

    ; Fill remaining 28 OAM entries with Y=0 (hidden)
    ld b, 28 * 4        ; 28 entries × 4 bytes
    xor a
.clearRest:
    ld [hl+], a
    dec b
    jr nz, .clearRest

    ; Set BG palette (DMG: all white so sprites stand out)
    ld a, $00           ; BG = all white
    ldh [$47], a        ; BGP
    ld a, $E4           ; OBJ = normal (00=transparent, 01=light, 10=dark, 11=black)
    ldh [$48], a        ; OBP0

    ; Turn on LCD with sprites enabled
    ld a, $83           ; LCD on, BG on, sprites on, 8x8
    ldh [$40], a        ; LCDC

    ; DMA OAM from $C100
    call WaitVBlank
    ld a, $C1           ; source = $C100
    ldh [$46], a        ; trigger OAM DMA
    ld a, 40            ; wait loop (DMA takes ~160 cycles)
.dmaWait:
    dec a
    jr nz, .dmaWait

    ; Write sentinel
    ld a, $FF
    ld [$C000], a

    ; Idle
.loop:
    halt
    nop
    jr .loop

WaitVBlank:
    ldh a, [$44]        ; LY
    cp 144
    jr nz, WaitVBlank
    ret
