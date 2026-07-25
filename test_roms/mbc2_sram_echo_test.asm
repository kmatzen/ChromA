; MBC2 SRAM echo-write regression test (issue #47 / PR #69)
;
; MBC2 has 512 half-bytes of RAM; on hardware the whole A000-BFFF window
; echoes it.  ChromA's sram_W2 write-through handler computes the GBA
; cart-SRAM address from (addy & 0x1FFF) -- if that offset is not clamped
; to rammask, every write past A1FF lands beyond the write-through region
; and mirrors into the low GBA-SRAM area holding the config/savestate
; heap, silently corrupting saves.
;
; This ROM enables MBC2 RAM and fills the entire A000-BFFF window with
; 0xAA.  test_mbc2_sram.py then inspects the .sav:
;   - the 512-byte MBC2 write-through window must contain the pattern
;   - the heap area below it must NOT (unclamped builds spray ~7.5KB
;     of 0xAA across it)
;
; Cart type is 0x06 (MBC2+BATTERY), RAM-size header byte 0 (correct for
; MBC2 -- its RAM is internal).
SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Main", ROM0[$0150]
Main:
    di
    ld sp, $FFFE
    ld a, $0A
    ld [$0000], a          ; MBC2 RAM enable (address bit 8 clear)
    ld hl, $A000
    ld bc, $2000
.fill:
    ld a, $AA
    ld [hl+], a
    dec bc
    ld a, b
    or c
    jr nz, .fill
.done:
    jr .done
