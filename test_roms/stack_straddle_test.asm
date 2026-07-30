; Stack straddling a 4K page boundary (issue #98)
;
; push16/pop16/popAF resolved the host page ONCE, from the first byte's
; address, and reused that base for the second byte.  Guest pages either side
; of a 4K boundary are not contiguous in host memory, so whenever the stack
; straddled one the second byte went to the wrong place entirely:
;
;   SP=$DFFF   $E000 is echo RAM -> WRAM $C000, but the base resolved from
;              $DFFF lands XGB_RAM+$2000, which is XGB_HRAM -- i.e. $FF80.
;   SP=$CFFF   with SVBK>=2, $D000 is a GBC_EXRAM bank, but the base resolved
;              from $CFFF lands in XGB_RAM -- i.e. WRAM bank 1.
;   SP=$9FFF   $A000 is cart RAM, but the base resolved from $9FFF lands
;              XGB_VRAM+$2000 -- i.e. VRAM bank 1.
;   SP=$FFFF   the second byte wraps to $0000 (ROM), but the base resolved
;              from $FFFF lands far outside any buffer.
;
; Each subtest plants a different value at the correct target and at the wrong
; one, so the .sav says which the emulator actually reached.
;
; CGB-only (-C) is required: SVBK does not exist on DMG, and without the CGB
; flag the $CFFF/$D000 subtests would be measuring a flat 8K WRAM where the
; two pages ARE contiguous and the bug is invisible.
;
; The LCD is turned off up front so VRAM and cart RAM can be touched freely
; and the screen stays blank -- this ROM asserts on memory, not pixels.
;
; Results in cart RAM (the runner dumps it as the .sav):
;   A100  B after POP BC, SP=$DFFF        want $11 from $C000; $22 = hit $FF80
;   A101  [$C000] after PUSH BC=$3344, SP=$E001   want $33
;   A102  [$FF80] after that push         want $22 untouched; $33 = hit HRAM
;   A103  A after POP AF, SP=$DFFF        want $11 from $C000; $22 = hit $FF80
;   A104  B after POP BC, SP=$CFFF, SVBK=2   want $66 (bank 2); $55 = bank 1
;   A105  bank 2 [$D000] after PUSH BC=$7788, SP=$D001, SVBK=2   want $77
;   A106  bank 1 [$D000] after that push  want $55 untouched; $77 = hit bank 1
;   A107  B after POP BC, SP=$FFFF        want $A7, the byte at ROM $0000
;   A108  C after POP BC, SP=$9FFF        want $99, from VRAM $9FFF
;   A109  B after POP BC, SP=$9FFF        want $88 from cart RAM $A000;
;                                         $77 = hit VRAM bank 1
;   A10A  B after POP BC, SP=$C200        control: an aligned pop, want $BB
;   A10F  $5A once every subtest has run
;
; Build:
;   rgbasm -o straddle.o test_roms/stack_straddle_test.asm
;   rgblink -o test_roms/stack_straddle_test.gb straddle.o
;   rgbfix -v -p 0 -t "STRADDLE" -m 0x1B -r 2 -C test_roms/stack_straddle_test.gb

; The second byte of a pop at SP=$FFFF wraps to $0000.  Put a distinctive byte
; there so "did it wrap correctly" is not indistinguishable from reading zero.
SECTION "WrapTarget", ROM0[$0000]
    db $A7

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Main", ROM0[$0150]
Main:
    di
    ld sp, $FFFE

    xor a
    ldh [$FF40], a         ; LCD off: VRAM and OAM are free to touch

    ld a, $0A
    ld [$0000], a          ; MBC5: enable cart RAM
    xor a
    ld [$4000], a          ; MBC5: select RAM bank 0

    ; Clear the result area.
    ld hl, $A100
    ld b, 16
.clear_results:
    xor a
    ld [hl+], a
    dec b
    jr nz, .clear_results

    ; ---- 1. POP with SP=$DFFF: WRAM into echo RAM ------------------------
    ; The second byte is at $E000, which mirrors WRAM $C000.  The old base,
    ; resolved from $DFFF, reached XGB_HRAM instead -- guest $FF80.
    ld a, $11
    ld [$C000], a          ; the correct target
    ld a, $22
    ldh [$FF80], a         ; where the bug used to land
    ld a, $EE
    ld [$DFFF], a          ; first byte, so C is deterministic

    ld sp, $DFFF
    pop bc
    ld sp, $FFFE
    ld a, b
    ld [$A100], a

    ; ---- 2. PUSH with SP=$E001: same boundary, writing -------------------
    ; Stores C at $DFFF and B at $E000, so B must appear in WRAM $C000 and
    ; $FF80 must still hold the $22 from subtest 1.
    xor a
    ld [$C000], a
    ld bc, $3344
    ld sp, $E001
    push bc
    ld sp, $FFFE

    ld a, [$C000]
    ld [$A101], a
    ldh a, [$FF80]
    ld [$A102], a

    ; ---- 3. POP AF across the same boundary ------------------------------
    ; popAF is its own macro, so it needs its own witness.  A comes from the
    ; second byte, at $E000.
    ld a, $11
    ld [$C000], a
    ld a, $22
    ldh [$FF80], a
    xor a
    ld [$DFFF], a          ; F: all flags clear

    ld sp, $DFFF
    pop af
    ld sp, $FFFE
    ld [$A103], a

    ; ---- 4. POP with SP=$CFFF and SVBK=2 --------------------------------
    ; $D000 is the switchable WRAM bank.  Plant a different byte in bank 1
    ; and bank 2, then read across the boundary with bank 2 selected: the old
    ; base, resolved from $CFFF, always reached bank 1.
    ld a, 1
    ldh [$FF70], a         ; SVBK = 1
    ld a, $55
    ld [$D000], a          ; bank 1
    ld a, 2
    ldh [$FF70], a         ; SVBK = 2
    ld a, $66
    ld [$D000], a          ; bank 2
    ld a, $DD
    ld [$CFFF], a          ; first byte

    ld sp, $CFFF
    pop bc
    ld sp, $FFFE
    ld a, b
    ld [$A104], a

    ; ---- 5. PUSH with SP=$D001 and SVBK=2 -------------------------------
    ; Stores B at $D000, which must be bank 2.  Bank 1 must keep its $55.
    ld bc, $7788
    ld sp, $D001
    push bc
    ld sp, $FFFE

    ld a, [$D000]          ; still SVBK=2
    ld [$A105], a
    ld a, 1
    ldh [$FF70], a
    ld a, [$D000]          ; bank 1
    ld [$A106], a

    ; ---- 6. POP with SP=$FFFF: the second byte wraps to $0000 -----------
    ld sp, $FFFF
    pop bc
    ld sp, $FFFE
    ld a, b
    ld [$A107], a

    ; ---- 7. POP with SP=$9FFF: VRAM into cart RAM -----------------------
    ; The second byte is at $A000, in cart RAM.  The old base, resolved from
    ; $9FFF, reached XGB_VRAM+$2000 -- the start of VRAM bank 1.
    xor a
    ldh [$FF4F], a         ; VBK = 0
    ld a, $99
    ld [$9FFF], a          ; first byte, in VRAM
    ld a, 1
    ldh [$FF4F], a         ; VBK = 1
    ld a, $77
    ld [$8000], a          ; where the bug used to land
    xor a
    ldh [$FF4F], a         ; VBK = 0
    ld a, $88
    ld [$A000], a          ; the correct target, in cart RAM

    ld sp, $9FFF
    pop bc
    ld sp, $FFFE
    ld a, c
    ld [$A108], a
    ld a, b
    ld [$A109], a

    ; ---- 8. Control: an aligned pop, nowhere near a boundary ------------
    ld a, $AA
    ld [$C200], a
    ld a, $BB
    ld [$C201], a
    ld sp, $C200
    pop bc
    ld sp, $FFFE
    ld a, b
    ld [$A10A], a

    ; Everything ran.
    ld a, $5A
    ld [$A10F], a
.done:
    jr .done
