; Mid-frame BGP raster on DMG (issue #148).
;
; FF47 had no split machinery at all: the CGB side records a palette snapshot
; against the current scanline on every 64th FF69 write, but a DMG BGP write
; went straight into the palette with nothing recording *when* it happened, so
; the whole frame rendered with one palette.  That is what makes DMG fades and
; HUD splits look wrong -- they are raster effects by construction.
;
; The probe drives the simplest possible split, every frame, so the screen is
; stable and can be captured at any point:
;
;   during VBlank   BGP = $0C   colour 1 -> black
;   at LY = 72      BGP = $00   colour 1 -> white
;
; Every background tile is colour 1, so BGP alone decides the shade and the
; split is directly readable off the screen:
;
;   lines   0.. 71   black
;   lines  72..143   white
;
; Without split support both halves come out the same shade -- whichever write
; the frame happened to end on -- which is what test_bgp_raster.py measures.
; It compares the two halves against each other within one frame, which is
; band-relative and so says nothing about how either emulator colourises DMG.
;
; Build:
;   rgbasm -o bgpraster.o test_roms/bgp_raster_test.asm
;   rgblink -o test_roms/bgp_raster_test.gb bgpraster.o
;   rgbfix -v -p 0 -t "BGPRASTER" -m 0x1B -r 2 test_roms/bgp_raster_test.gb

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Main", ROM0[$0150]
Main:
    di
    ld sp, $FFFE

    xor a
    ldh [$FF40], a         ; LCD off so VRAM can be written freely

    ; Tile 0: every pixel colour 1 (low bitplane set, high bitplane clear).
    ld hl, $8000
    ld b, 8
.tile:
    ld a, $FF
    ld [hl+], a            ; bitplane 0
    xor a
    ld [hl+], a            ; bitplane 1
    dec b
    jr nz, .tile

    ; Background map: all tile 0.
    ld hl, $9800
    ld de, 32*32
.map:
    xor a
    ld [hl+], a
    dec de
    ld a, d
    or e
    jr nz, .map

    xor a
    ldh [$FF42], a         ; SCY
    ldh [$FF43], a         ; SCX
    ld a, $0C
    ldh [$FF47], a         ; BGP: colour 1 -> black

    ld a, $91              ; LCD on, BG on, tile data $8000, map $9800
    ldh [$FF40], a

.frame:
.wait144:
    ldh a, [$FF44]
    cp 144
    jr nz, .wait144
    ld a, $0C
    ldh [$FF47], a         ; re-arm: top of the frame is black

.wait72:
    ldh a, [$FF44]
    cp 72
    jr nz, .wait72
    ld a, $00
    ldh [$FF47], a         ; mid-frame: bottom of the frame is white

    jr .frame
