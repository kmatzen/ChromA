; Echo RAM regression test (issue #46)
;
; 0xE000-0xFDFF is a mirror of WRAM 0xC000-0xDDFF.  readmem/writemem fold the
; echo correctly, but the *direct memmap* paths -- push16/pop16/popAF (PUSH,
; POP, CALL, RET, RST) and encodePC (executing code) -- index memmap_tbl by
; the top address nibble, and entries 14/15 (0xE000/0xF000) were pointed at
; XGB_HRAM-0xFF80.  Since XGB_HRAM sits immediately after XGB_RAM's 0x2000
; bytes, that resolves 0xE000 to XGB_RAM+0x80 and 0xF000 to XGB_RAM+0x1080:
; every access through those paths landed 0x80 bytes too high in WRAM.
;
; Entry 14 is a plain echo mapping.  Entry 15 is not, because 0xF000-0xFFFF
; also holds OAM, IO and HRAM, and SP=0xFFFE and HRAM-resident code are
; universal -- so the direct paths range-check 0xF000-0xFDFF and take the echo
; base from `echomap` instead, leaving entry 15 to serve 0xFE00-0xFFFF.  That
; makes the 0xFE00 boundary and the HRAM cases part of this test: getting the
; range test wrong breaks the stack of every game ever made.
;
; Each subtest deliberately plants a different value at the correct target and
; at the +0x80 target, so the .sav says which one the emulator actually hit.
;
; Results are written to cart RAM (the runner dumps it as the .sav):
;   A000/A001  bytes at C000/C001 after PUSH BC (BC=$1234) with SP=$E002
;   A002/A003  bytes at C080/C081 -- the +0x80 aliases
;   A004/A005  C,B after POP BC with SP=$E100   (C100/C101 vs C180/C181)
;   A006       written by a stub CALLed at $E200 ($5A from C200, $A5 from C280)
;   A007       LD A,($E300) -- the readmem path, correct before and after
;   A008/A009  bytes at D000/D001 after PUSH BC (BC=$5678) with SP=$F002
;   A00A/A00B  bytes at D080/D081 -- the +0x80 aliases
;   A00C/A00D  C,B after POP BC with SP=$F100   (D100/D101 vs D180/D181)
;   A00E       written by a stub CALLed at $F200 ($5A from D200, $A5 from D280)
;   A00F       $5A once every subtest has run
;   A010       LD A,($F300) -- the readmem control for the F page
;   A011/A012  bytes at DDFE/DDFF after PUSH BC (BC=$9ABC) with SP=$FE00,
;              the top end of the echo: one off in the range test loses it
;   A013/A014  bytes at DE7E/DE7F -- the +0x80 aliases for that case
;   A015       A after POP AF with SP=$F400 ($3C from D401, $A5 from D481)
;   A016/A017  bytes at FFFC/FFFD after PUSH BC (BC=$4321) with SP=$FFFE --
;              the universal stack, which must still land in HRAM
;   A018/A019  C,B after POP BC with SP=$FFFC -- HRAM, read back
;   A01A       written by a stub CALLed at $FF90 -- executing out of HRAM
;
; Build:
;   rgbasm -o echo.o test_roms/echo_ram_test.asm
;   rgblink -o test_roms/echo_ram_test.gb echo.o
;   rgbfix -v -p 0 -t "ECHORAM" -m 0x1B -r 2 test_roms/echo_ram_test.gb

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Main", ROM0[$0150]
Main:
    di
    ld sp, $FFFE
    ld a, $0A
    ld [$0000], a          ; MBC5: enable cart RAM
    xor a
    ld [$4000], a          ; MBC5: select RAM bank 0

    ; Clear the result area.
    ld hl, $A000
    ld b, 32
.clear_results:
    xor a
    ld [hl+], a
    dec b
    jr nz, .clear_results

    ; Clear all of WRAM, so a byte that shows up in any window a subtest
    ; looks at was put there by that subtest and nothing else.
    ld hl, $C000
    ld bc, $2000           ; C000-DFFF
.clear_wram:
    xor a
    ld [hl+], a
    dec bc
    ld a, b
    or c
    jr nz, .clear_wram

    ; ---- 1. PUSH with SP in echo RAM -------------------------------------
    ; PUSH BC at SP=$E002 stores C at $E000 and B at $E001, which is WRAM
    ; $C000/$C001.  The bug puts them at $C080/$C081 instead.
    ld bc, $1234
    ld sp, $E002
    push bc
    ld sp, $FFFE

    ld a, [$C000]
    ld [$A000], a
    ld a, [$C001]
    ld [$A001], a
    ld a, [$C080]
    ld [$A002], a
    ld a, [$C081]
    ld [$A003], a

    ; ---- 2. POP with SP in echo RAM --------------------------------------
    ; $C100/$C101 is what $E100 must read; $C180/$C181 is where the bug looks.
    ld a, $AA
    ld [$C100], a
    ld a, $BB
    ld [$C101], a
    ld a, $CC
    ld [$C180], a
    ld a, $DD
    ld [$C181], a

    ld sp, $E100
    pop bc
    ld sp, $FFFE
    ld a, c
    ld [$A004], a
    ld a, b
    ld [$A005], a

    ; ---- 3. Executing code from echo RAM ---------------------------------
    ; Two stubs that differ only in the byte they report.  CALL $E200 must
    ; reach the one at $C200.
    ld hl, $C200
    ld de, StubGood
    call CopyStub
    ld hl, $C280
    ld de, StubBad
    call CopyStub
    call $E200

    ; ---- 4. Control: reading through echo RAM ----------------------------
    ; readmem folds the echo properly, so this reads $77 either way.  If it
    ; ever fails, the ROM itself is wrong rather than the memmap entry.
    ld a, $77
    ld [$C300], a
    ld a, [$E300]
    ld [$A007], a

    ; ---- 5. PUSH with SP in the F000 echo --------------------------------
    ; $F000-$FDFF mirrors $D000-$DDFF.  PUSH BC at SP=$F002 stores C at
    ; $F000 and B at $F001, which is WRAM $D000/$D001.
    ld bc, $5678
    ld sp, $F002
    push bc
    ld sp, $FFFE

    ld a, [$D000]
    ld [$A008], a
    ld a, [$D001]
    ld [$A009], a
    ld a, [$D080]
    ld [$A00A], a
    ld a, [$D081]
    ld [$A00B], a

    ; ---- 6. POP with SP in the F000 echo ---------------------------------
    ld a, $AA
    ld [$D100], a
    ld a, $BB
    ld [$D101], a
    ld a, $CC
    ld [$D180], a
    ld a, $DD
    ld [$D181], a

    ld sp, $F100
    pop bc
    ld sp, $FFFE
    ld a, c
    ld [$A00C], a
    ld a, b
    ld [$A00D], a

    ; ---- 7. Executing code from the F000 echo ----------------------------
    ld hl, $D200
    ld de, StubF000Good
    call CopyStub
    ld hl, $D280
    ld de, StubF000Bad
    call CopyStub
    call $F200

    ; ---- 8. Control: reading through the F000 echo -----------------------
    ld a, $88
    ld [$D300], a
    ld a, [$F300]
    ld [$A010], a

    ; ---- 9. The top of the echo, $FDFF -----------------------------------
    ; PUSH BC at SP=$FE00 stores C at $FDFE and B at $FDFF: the last two
    ; bytes that are still echo rather than OAM.  A range test that stops one
    ; page early sends these to the +0x80 alias in $DE7E/$DE7F.
    ld bc, $9ABC
    ld sp, $FE00
    push bc
    ld sp, $FFFE

    ld a, [$DDFE]
    ld [$A011], a
    ld a, [$DDFF]
    ld [$A012], a
    ld a, [$DE7E]
    ld [$A013], a
    ld a, [$DE7F]
    ld [$A014], a

    ; ---- 10. POP AF in the echo ------------------------------------------
    ; popAF is its own macro, so it needs its own witness.  POP AF at
    ; SP=$F400 takes F from $D400 and A from $D401.
    xor a
    ld [$D400], a          ; F: all flags clear
    ld a, $3C
    ld [$D401], a
    xor a
    ld [$D480], a
    ld a, $A5
    ld [$D481], a

    ld sp, $F400
    pop af
    ld sp, $FFFE
    ld [$A015], a

    ; ---- 11. HRAM must still work ----------------------------------------
    ; $FE00-$FFFF is not echo, and the stack lives at $FFFE in essentially
    ; every commercial game.  PUSH BC at SP=$FFFE stores C at $FFFC and B at
    ; $FFFD, in HRAM -- if the echo range test is too wide, this lands in
    ; WRAM instead and every game's stack is corrupt.
    ld bc, $4321
    ld sp, $FFFE
    push bc
    ldh a, [$FFFC]
    ld [$A016], a
    ldh a, [$FFFD]
    ld [$A017], a

    ; And read them back through pop16, which is still pointing at $FFFC.
    pop bc
    ld sp, $FFFE
    ld a, c
    ld [$A018], a
    ld a, b
    ld [$A019], a

    ; ---- 12. Executing code out of HRAM ----------------------------------
    ; encodePC has the same range test, and HRAM routines are a standard
    ; trick (the OAM DMA wait loop lives there).
    ld hl, $FF90
    ld de, StubHram
    call CopyStub
    call $FF90

    ; Everything ran.
    ld a, $5A
    ld [$A00F], a
.done:
    jr .done

; Copy 6 bytes from DE to HL.
CopyStub:
    ld b, 6
.loop:
    ld a, [de]
    inc de
    ld [hl+], a
    dec b
    jr nz, .loop
    ret

; ld a,$5A / ld [$A006],a / ret
StubGood:
    db $3E, $5A, $EA, $06, $A0, $C9
; ld a,$A5 / ld [$A006],a / ret
StubBad:
    db $3E, $A5, $EA, $06, $A0, $C9

; ld a,$5A / ld [$A00E],a / ret
StubF000Good:
    db $3E, $5A, $EA, $0E, $A0, $C9
; ld a,$A5 / ld [$A00E],a / ret
StubF000Bad:
    db $3E, $A5, $EA, $0E, $A0, $C9

; ld a,$5A / ld [$A01A],a / ret
StubHram:
    db $3E, $5A, $EA, $1A, $A0, $C9
