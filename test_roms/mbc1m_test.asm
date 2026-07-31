; MBC1M (MBC1 multicart) banking probe (issue #50).
;
; An MBC1 multicart wires BANK1 as 4 bits instead of 5, so BANK2 shifts by 4
; and selects one of four 256KB "games" rather than one of four 512KB halves:
;
;   plain MBC1   bank = (BANK2 << 5) | (BANK1 & 0x1F)
;   MBC1M        bank = (BANK2 << 4) | (BANK1 & 0x0F)
;
; Every byte at $4010 in this ROM holds the number of the bank it lives in, so
; reading $4010 after a bank select reports which bank the mapper actually
; mapped.  Two selects tell the two models apart unambiguously:
;
;   BANK2=1 BANK1=$01  ->  MBC1M 17 ($11)   plain MBC1 33 ($21)
;   BANK2=1 BANK1=$11  ->  MBC1M 17 ($11)   plain MBC1 49 ($31)
;
; The second is the one that pins the 4-bit mask specifically: BANK1 bit 4 must
; be ignored, so it must land on the same bank as the first.
;
; Multicart detection is by content, not by header: emulators look for a valid
; cartridge header at the start of each 256KB game.  build_mbc1m.py copies this
; ROM's own header to $40100 and $80100 for that reason.
;
; Results in cart RAM (bank 0):
;   A000  bank seen with BANK2=0 BANK1=$01   1 under both models
;   A001  bank seen with BANK2=1 BANK1=$01   17 MBC1M / 33 plain
;   A002  bank seen with BANK2=1 BANK1=$11   17 MBC1M / 49 plain
;   A003  bank seen back at BANK2=0 BANK1=$01  1 again (mapper still sane)
;   A00F  $5A when the probe ran to completion

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
    ld [$6000], a          ; mode 0: $4000 writes are ROM-high bits

    ; --- BANK2 = 0, BANK1 = 1 -------------------------------------------
    xor a
    ld [$4000], a
    ld a, $01
    ld [$2000], a
    ld a, [$4010]
    ld b, a

    ; --- BANK2 = 1, BANK1 = 1 -------------------------------------------
    ld a, $01
    ld [$4000], a
    ld a, $01
    ld [$2000], a
    ld a, [$4010]
    ld c, a

    ; --- BANK2 = 1, BANK1 = $11 (bit 4 set) -----------------------------
    ; A 4-bit BANK1 ignores bit 4, so this must map the same bank as above.
    ld a, $11
    ld [$2000], a
    ld a, [$4010]
    ld d, a

    ; --- back to BANK2 = 0, BANK1 = 1 -----------------------------------
    xor a
    ld [$4000], a
    ld a, $01
    ld [$2000], a
    ld a, [$4010]
    ld e, a

    ld a, b
    ld [$A000], a
    ld a, c
    ld [$A001], a
    ld a, d
    ld [$A002], a
    ld a, e
    ld [$A003], a
    ld a, $5A
    ld [$A00F], a
.done:
    jr .done
