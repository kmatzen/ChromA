; The window latches on for the frame once LY reaches WY (issue #53 item 1).
;
; Hardware compares WY against LY once per line.  Once that coincidence has
; happened the window stays on for the rest of the frame, and raising WY
; afterwards does not retract it.  ChromA recomputed visibility as
; `scanline >= WY` whenever a register changed, so a mid-frame raise turned
; the window off from that line down.
;
; Each frame the probe arms WY=64 during VBlank, lets the window trigger, then
; raises WY to 200 at LY=100 -- after the trigger, and well before the bottom
; of the screen.
;
;   correct: rows 64..143 all show window (the latch holds)
;   broken : rows 64..99 show window, rows 100..143 fall back to background
;
; The window map is solid colour 3 and the background solid colour 0, so the
; two outcomes differ as dark against light.  The test samples a band well
; below the raise and compares it against a band just below WY, within the
; same frame, which keeps the reading independent of how an emulator colours
; DMG output.
;
; Build:
;   rgbasm -o w.o test_roms/wy_latch_test.asm
;   rgblink -o test_roms/wy_latch_test.gb w.o
;   rgbfix -v -p 0 -t "WYLATCH" -m 0x00 test_roms/wy_latch_test.gb

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Main", ROM0[$0150]
Main:
    di
    ld sp, $FFFE

    xor a
    ldh [$FF40], a          ; LCD off so VRAM can be written freely

    ; tile 0 = colour 0 (both planes clear), tile 1 = colour 3 (both set)
    ld hl, $8000
    ld b, 16
    xor a
.tile0:
    ld [hl+], a
    dec b
    jr nz, .tile0
    ld b, 16
    ld a, $FF
.tile1:
    ld [hl+], a
    dec b
    jr nz, .tile1

    ; BG map ($9800) all tile 0; window map ($9C00) all tile 1
    ld hl, $9800
    ld de, 32 * 32
.bgmap:
    xor a
    ld [hl+], a
    dec de
    ld a, d
    or e
    jr nz, .bgmap

    ld hl, $9C00
    ld de, 32 * 32
.winmap:
    ld a, 1
    ld [hl+], a
    dec de
    ld a, d
    or e
    jr nz, .winmap

    ld a, %11100100         ; BGP: colour 0 light, colour 3 dark
    ldh [$FF47], a
    ld a, 7                 ; WX=7 puts the window at screen x 0
    ldh [$FF4B], a
    ld a, 64
    ldh [$FF4A], a          ; WY=64

    ; LCD on, window on using the $9C00 map, BG on, tile data at $8000
    ld a, $F1
    ldh [$FF40], a

.loop:
    ; arm WY during VBlank, so it is in place before LY reaches it
    call WaitVBlank
    ld a, 64
    ldh [$FF4A], a
    ; ...then raise it mid-frame, after the window has already triggered
    call WaitLine100
    ld a, 200
    ldh [$FF4A], a
    jr .loop

WaitVBlank:
.w1:
    ldh a, [$FF44]
    cp 144
    jr nz, .w1
    ret

WaitLine100:
.w2:
    ldh a, [$FF44]
    cp 100
    jr nz, .w2
    ret
