; The window's WY coincidence latches for the rest of the frame (issue #146).
;
; Hardware turns the window on when LY reaches WY and keeps it on until the
; end of the frame.  Raising WY afterwards does not retract it.  ChromA
; recomputed window visibility as `scanline >= windowY` on every register
; write, so a mid-frame raise dropped a window hardware had already latched.
;
; The probe drives that exact sequence every frame, so the screen is stable
; and can be screenshotted at any point:
;
;   during VBlank   WY = 64    (arms the coincidence for the coming frame)
;   at LY = 100     WY = 200   (a raise well past the current line)
;
; The whole background is colour 0 and the whole window is colour 3, so the
; window's extent is directly readable off the screen:
;
;   lines   0.. 63   background   (above WY, window not yet latched)
;   lines  64..143   window       (latched at 64; the raise must not undo it)
;
; A build without the latch shows window from 64 to 99 and background from
; 100 down, because the raise retracts it at the moment it lands.  That is
; what test_wy_latch.py measures: it compares a band below the raise against
; one above it *within the same frame*, which is band-relative and so does
; not care how either emulator colourises a DMG game.
;
; Build:
;   rgbasm -o wylatch.o test_roms/wy_latch_test.asm
;   rgblink -o test_roms/wy_latch_test.gb wylatch.o
;   rgbfix -v -p 0 -t "WYLATCH" -c -m 0x1B -r 2 test_roms/wy_latch_test.gb

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Main", ROM0[$0150]
Main:
    di
    ld sp, $FFFE

    ; LCD off so VRAM can be written without contention.
    xor a
    ldh [$FF40], a

    ; Tile 0 = colour 0 everywhere, tile 1 = colour 3 everywhere.
    ld hl, $8000
    ld b, 16
.tile0:
    xor a
    ld [hl+], a
    dec b
    jr nz, .tile0
    ld b, 16
.tile1:
    ld a, $FF
    ld [hl+], a
    dec b
    jr nz, .tile1

    ; BG map at 9800 -> tile 0.  Window map at 9C00 -> tile 1.
    ld hl, $9800
    ld de, 32*32
.bgmap:
    xor a
    ld [hl+], a
    dec de
    ld a, d
    or e
    jr nz, .bgmap

    ld hl, $9C00
    ld de, 32*32
.winmap:
    ld a, 1
    ld [hl+], a
    dec de
    ld a, d
    or e
    jr nz, .winmap

    ; Identity-ish palette: colour 0 lightest, colour 3 darkest.
    ld a, $E4
    ldh [$FF47], a

    xor a
    ldh [$FF42], a         ; SCY
    ldh [$FF43], a         ; SCX
    ld a, 7
    ldh [$FF4B], a         ; WX = 7 -> window starts at screen x 0
    ld a, 64
    ldh [$FF4A], a         ; WY = 64

    ; LCD on, BG on, tile data 8000, BG map 9800, window on, window map 9C00.
    ld a, $F1
    ldh [$FF40], a

.frame:
    ; Re-arm WY during VBlank, so every frame is identical and the capture
    ; frame does not matter.
.wait144:
    ldh a, [$FF44]
    cp 144
    jr nz, .wait144
    ld a, 64
    ldh [$FF4A], a

    ; Raise WY well below the bottom of the screen, mid-frame, once the
    ; window has been showing for ~36 lines.
.wait100:
    ldh a, [$FF44]
    cp 100
    jr nz, .wait100
    ld a, 200
    ldh [$FF4A], a

    jr .frame
