; Echo RAM regression test (issue #46)
;
; 0xE000-0xFDFF is a mirror of WRAM 0xC000-0xDDFF.  readmem/writemem fold the
; echo correctly, but the *direct memmap* paths -- push16/pop16/popAF (PUSH,
; POP, CALL, RET, RST) and encodePC (executing code) -- index memmap_tbl by
; the top address nibble, and entry 14 (0xE000) was pointed at
; XGB_HRAM-0xFF80.  Since XGB_HRAM sits immediately after XGB_RAM's 0x2000
; bytes, that resolves 0xE000 to XGB_RAM+0x80: every access through those
; paths landed 0x80 bytes too high in WRAM.
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
;   A00F       $5A once every subtest has run
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
    ld b, 16
.clear_results:
    xor a
    ld [hl+], a
    dec b
    jr nz, .clear_results

    ; Clear every WRAM window a subtest looks at, so a byte that shows up
    ; there was put there by that subtest and nothing else.
    ld hl, $C000
    ld bc, $0400           ; C000-C3FF
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
