; LCDC (FF40) write must not disturb the guest F register -- issue #95
;
; FF40W_entry used r3 as a scratch register in two places, but r3 is gb_flg --
; the guest's F register -- and IO write handlers are entered by a direct jump
; from the dispatcher with nothing saved.  Any LCDC write that reached either
; path silently wiped all four guest flags.  All four live in bits 28-31 of
; gb_flg, so overwriting r3 with a scanline byte or an IWRAM pointer left every
; flag decoding as 0: F read back $00, deterministically, always clearing.
;
; Writing an IO register cannot change F on real hardware, so every slot below
; must read back exactly the value the phase preset.  test_lcdc_flags.py
; asserts that, and also runs this same ROM directly in mGBA's own GB core so
; the expectation is backed by an independent implementation and not just by
; this comment.
;
; F is preset with `ld bc,$00xx` / `push bc` / `pop af` rather than by
; arithmetic, so the probe can name an exact F value instead of whatever a
; `xor a` / `scf` pair happens to leave.  Neither `ld a,imm` nor `ldh [n],a`
; touches F, so nothing between the preset and the capture can perturb it.
;
; The main cases preset F=$F0 -- Z, N, H and C all set -- because the bug
; cleared all four at once; that is the strictest single value.  Two further
; cases preset F=$00 as the inverse control: they catch a regression that
; spuriously *sets* flags, which an all-set-only probe would pass.
;
; Phases:
;   bit1      LCDC bit 1 (sprite enable) 0->1.  Reaches the `ldrb_ r3,scanline`
;             path, which tracks mid-frame sprite enable/disable.
;   bit2      LCDC bit 2 (sprite size) 0->1.  Same path.
;   lcdon     LCD turned back on, bit 7 0->1.  Reaches the separate
;             `ldr_ r3,nexttimeout` path that rewrites the scanline timeout.
;   bit4      A real LCDC value change to an untracked bit.  Positive control:
;             this is a genuine change that never reaches either r3 site, so it
;             was preserved even with the bug.  It isolates the cause to those
;             two paths and rules out the probe or the `push af` capture being
;             at fault.
;   none      No IO write at all between the preset and the capture.  Proves
;             the capture sequence itself does not disturb F.
;   line0     A bit 1 change performed at the top of the frame, so the scanline
;             byte the handler loads is ~0 rather than mid-screen.  The
;             corruption did not depend on that value -- all four flags live
;             above bit 27, and a scanline byte only ever sets bits 0-7 -- and
;             this phase pins that down.
;   inverse   bit1 and lcdon repeated with F=$00 preset.
;
; Results in cart RAM (dumped as the .sav):
;   A000  F after an LCDC bit 1 change,   preset $F0  -- must be $F0
;   A001  F after an LCDC bit 2 change,   preset $F0  -- must be $F0
;   A002  F after the LCD is turned on,   preset $F0  -- must be $F0
;   A003  F after an untracked bit 4 change, preset $F0 -- must be $F0 (control)
;   A004  F with no IO write at all,      preset $F0  -- must be $F0 (control)
;   A005  F after a bit 1 change on line 0, preset $F0 -- must be $F0
;   A006  F after an LCDC bit 1 change,   preset $00  -- must be $00 (inverse)
;   A007  F after the LCD is turned on,   preset $00  -- must be $00 (inverse)
;   A010  last phase reached (for diagnosing a hang)
;   A01F  $5A once every phase has run
;
; Build:
;   rgbasm -o lcdc.o test_roms/lcdc_flags_test.asm
;   rgblink -o test_roms/lcdc_flags_test.gb lcdc.o
;   rgbfix -v -p 0 -t "LCDCF" -m 0x1B -r 2 test_roms/lcdc_flags_test.gb

DEF LCDC_BASE   EQU $91     ; LCD on, BG on, BG tile data $8000; sprite bits clear
DEF LCDC_BIT1   EQU $93     ; + sprite enable
DEF LCDC_BIT2   EQU $95     ; + sprite size (8x16)
DEF LCDC_OFF    EQU $11     ; LCD off; bits 1 and 2 untouched
DEF LCDC_BIT4   EQU $81     ; BG tile data cleared; no sprite bits, no LCD toggle

DEF F_ALL       EQU $F0     ; Z N H C all set
DEF F_NONE      EQU $00     ; all clear

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Main", ROM0[$0150]

; Preset F to \1 without disturbing it afterwards.  Clobbers A, B and C.
; \1 is < $100, so B lands at 0 and C at the wanted F; the pop puts B in A and
; C in F.  F's low nibble is not writable and always reads back 0.
MACRO set_f
    ld bc, \1               ; B -> A, C -> F on the pop
    push bc
    pop af
ENDM

; Capture F into cart RAM at \1.  Clobbers A, B and C.
MACRO capture_f
    push af
    pop bc
    ld a, c
    ld [\1], a
ENDM

MACRO phase
    ld a, \1
    ld [$A010], a
ENDM

Main:
    di
    ld sp, $FFFE

    ; MBC5: enable cart RAM, select bank 0
    ld a, $0A
    ld [$0000], a
    xor a
    ld [$4000], a

    ; ---- none: no IO write between the preset and the capture --------------
    ; First, so that a failure here indicts the capture sequence rather than
    ; any LCDC write.
    phase 1
    set_f F_ALL
    capture_f $A004

    ; ---- bit1: sprite enable 0 -> 1 ---------------------------------------
    phase 2
    ld a, LCDC_BASE
    ldh [$FF40], a
    set_f F_ALL
    ld a, LCDC_BIT1
    ldh [$FF40], a
    capture_f $A000

    ; ---- bit2: sprite size 0 -> 1 -----------------------------------------
    phase 3
    ld a, LCDC_BASE
    ldh [$FF40], a
    set_f F_ALL
    ld a, LCDC_BIT2
    ldh [$FF40], a
    capture_f $A001

    ; ---- lcdon: bit 7 0 -> 1 ----------------------------------------------
    ; The LCD-off write drives bit 7 1->0, which is a different path; only the
    ; 0->1 edge reaches the nexttimeout code.
    phase 4
    ld a, LCDC_BASE
    ldh [$FF40], a
    ld a, LCDC_OFF
    ldh [$FF40], a
    set_f F_ALL
    ld a, LCDC_BASE
    ldh [$FF40], a
    capture_f $A002

    ; ---- bit4: a real change that reaches neither r3 site ------------------
    phase 5
    ld a, LCDC_BASE
    ldh [$FF40], a
    set_f F_ALL
    ld a, LCDC_BIT4
    ldh [$FF40], a
    capture_f $A003

    ; ---- line0: a bit 1 change with the scanline byte near 0 ---------------
    ; The LY poll trashes F, so F is preset after it.  LY may have advanced a
    ; line or two by the time the write lands; the phase only needs the handler
    ; to load a small scanline value, not exactly zero.
    phase 6
    ld a, LCDC_BASE
    ldh [$FF40], a
.wait_line0:
    ldh a, [$FF44]
    and a
    jr nz, .wait_line0
    set_f F_ALL
    ld a, LCDC_BIT1
    ldh [$FF40], a
    capture_f $A005

    ; ---- inverse controls: F=$00 must stay $00 ----------------------------
    phase 7
    ld a, LCDC_BASE
    ldh [$FF40], a
    set_f F_NONE
    ld a, LCDC_BIT1
    ldh [$FF40], a
    capture_f $A006

    phase 8
    ld a, LCDC_BASE
    ldh [$FF40], a
    ld a, LCDC_OFF
    ldh [$FF40], a
    set_f F_NONE
    ld a, LCDC_BASE
    ldh [$FF40], a
    capture_f $A007

    ; ---- leave the LCD in a sane state and mark completion -----------------
    ld a, LCDC_BASE
    ldh [$FF40], a
    ld a, $5A
    ld [$A01F], a
.hang:
    jr .hang
