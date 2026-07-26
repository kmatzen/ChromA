; SRAM cross-game ownership regression test -- game "B" (issue #48)
;
; The counterpart to sram_owner_test_a.asm; see that file for what the pair
; proves and how test_sram_ownership.py drives them.  Identical except for
; the ID tag at $0180 and the signature byte ($B2 instead of $A1).
;
; Build:
;   rgbasm -o b.o test_roms/sram_owner_test_b.asm
;   rgblink -o test_roms/sram_owner_test_b.gb b.o
;   rgbfix -v -p 0 -t "SRAMOWNB" -m 0x1B -r 2 test_roms/sram_owner_test_b.gb

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "IdTag", ROM0[$0180]
    ; Must differ from A within these 4 bytes -- checksum_this() only reads
    ; 4 bytes at each 128-byte boundary.
    db $B2,$B2,$B2,$B2

SECTION "Main", ROM0[$0200]
Main:
    di
    ld sp, $FFFE
    ld a, $0A
    ld [$0000], a          ; MBC5: enable cart RAM
    xor a
    ld [$4000], a          ; MBC5: select RAM bank 0

    ; Echo what we inherited at A000 into A100, before overwriting it.
    ld hl, $A000
    ld de, $A100
    ld b, 16
.echo:
    ld a, [hl+]
    ld [de], a
    inc de
    dec b
    jr nz, .echo

    ; Stamp our own signature over A000.
    ld hl, $A000
    ld b, 16
.fill:
    ld a, $B2
    ld [hl+], a
    dec b
    jr nz, .fill

.done:
    jr .done
