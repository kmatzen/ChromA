; When does the mode-0 STAT interrupt actually arrive? (issue #144)
;
; ChromA raised the HBlank STAT interrupt from the scanline hook, which runs
; at the *next* line boundary with LY already incremented -- roughly 204
; cycles after HBlank entry.  test_stat_ly.py counts STAT interrupts and so
; cannot see this: a late interrupt is still exactly one interrupt.
;
; What distinguishes them is where the PPU is when the handler runs.  On
; hardware the handler for line N's HBlank runs *during* that HBlank, so the
; first thing it reads out of FF41 is mode 0.  An interrupt delivered at the
; line boundary instead runs at the start of line N+1, which is OAM scan --
; mode 2.  So the mode field read inside the handler is a direct, one-byte
; answer, with no reference screen and no pixel comparison involved.
;
; The probe records the first 16 interrupts:
;
;   A000..A00F   FF41 & 3 read inside the handler   0 = HBlank, 2 = OAM scan
;   A010..A01F   LY read inside the handler
;   A0FF         $5A once 16 samples are in
;
; LY is recorded alongside because it is the other half of the same defect:
; a handler that runs a line late reads the wrong LY, which is what a raster
; effect keyed to LY actually depends on.
;
; Build:
;   rgbasm -o statmode0.o test_roms/stat_mode0_timing_test.asm
;   rgblink -o test_roms/stat_mode0_timing_test.gb statmode0.o
;   rgbfix -v -p 0 -t "STATMODE0" -m 0x1B -r 2 test_roms/stat_mode0_timing_test.gb

DEF COUNT EQU $FF80

SECTION "Stat", ROM0[$0048]
    jp StatHandler

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
    ld [$4000], a          ; RAM bank 0
    ldh [COUNT], a

    ld hl, $A000           ; clear the result page
    ld b, 0
.clear:
    xor a
    ld [hl+], a
    dec b
    jr nz, .clear

    ld a, $91              ; LCD on, BG on -- STAT interrupts need the PPU
    ldh [$FF40], a

    ld a, $08              ; STAT: mode 0 (HBlank) interrupt enable
    ldh [$FF41], a
    xor a
    ldh [$FF0F], a         ; clear anything already pending
    ld a, $02              ; IE: LCD STAT only
    ldh [$FFFF], a
    ei

.wait:
    ldh a, [COUNT]
    cp 16
    jr c, .wait
    di
    ld a, $5A
    ld [$A0FF], a
.done:
    jr .done

StatHandler:
    push af
    push hl
    ldh a, [COUNT]
    cp 16
    jr nc, .out            ; already have the samples we want

    ld h, $A0
    ld l, a                ; hl = A000 + count

    ldh a, [$FF41]         ; where is the PPU right now?
    and $03
    ld [hl], a

    ld a, l
    add $10
    ld l, a                ; hl = A010 + count
    ldh a, [$FF44]
    ld [hl], a

    ldh a, [COUNT]
    inc a
    ldh [COUNT], a
.out:
    pop hl
    pop af
    reti
