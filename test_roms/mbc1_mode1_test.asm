; MBC1 mode-1 banking test (issue #50, MBC1 half)
;
; Real MBC1 always applies BANK2<<5 to the 4000-7FFF bank, in BOTH banking
; modes.  chroma zeroed the high bits whenever mode 1 was selected, so on a
; >=1MB cart every bank select in mode 1 lost bits 5-6 and fetched from the
; wrong 512KB half.  Mode 1 additionally maps bank BANK2<<5 at 0000-3FFF;
; chroma never called map0123_ from the mapper at all, so the low half stayed
; pinned to bank 0.
;
; Reading 0000-3FFF in mode 1 means the code doing the reading cannot live
; there -- the whole point is that the region is swapped out.  So the mode-1
; steps run from a stub copied into WRAM, which stores its findings in WRAM
; and restores mode 0 before returning; only then does the ROM copy the
; results into cart RAM.  Cart RAM is written in mode 0 with BANK2 applying
; to ROM only, so the results always land in RAM bank 0 where the .sav
; can see them.
;
; Results in cart RAM:
;   A000  [$4000] in mode 0, BANK1=1 BANK2=1  -- $21 on both (control)
;   A001  [$4000] in mode 1, BANK1=1 BANK2=1  -- $21 fixed, $01 broken
;   A002  [$0000] in mode 1, BANK2=1          -- $20 fixed, $00 broken
;   A003  [$4000] after restoring mode 0      -- $21 (sanity)
;   A004  [$4000] with BANK2=0 BANK1=5        -- $05 on both (control)
;   A00F  $5A when every step has run
;
; Build:
;   rgbasm -o mbc1.o test_roms/mbc1_mode1_test.asm
;   rgblink -o test_roms/mbc1_mode1_test.gb mbc1.o
;   rgbfix -v -p 0 -t "MBC1MODE" -m 0x03 -r 2 test_roms/mbc1_mode1_test.gb

DEF STUB_DST   EQU $C000
DEF STUB_LOW   EQU $C0F0   ; byte read from $0000 in mode 1
DEF STUB_HIGH  EQU $C0F1   ; byte read from $4000 in mode 1

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
    ld [$6000], a          ; mode 0

    ld hl, $A000
    ld b, 16
    xor a
.clear:
    ld [hl+], a
    dec b
    jr nz, .clear

    ; ---- control: mode 0 with BANK2 set ---------------------------------
    ; BANK2 has always worked in mode 0, so this passes on both builds and
    ; proves the cart really is >=1MB and high banking works at all.
    ld a, 1
    ld [$2000], a          ; BANK1 = 1
    ld a, 1
    ld [$4000], a          ; BANK2 = 1  -> bank $21
    ld a, [$4000]
    ld [$A000], a

    ; ---- copy the mode-1 stub into WRAM ---------------------------------
    ld hl, Stub
    ld de, STUB_DST
    ld b, StubEnd - Stub
.copy:
    ld a, [hl+]
    ld [de], a
    inc de
    dec b
    jr nz, .copy

    call STUB_DST          ; runs in WRAM; returns with mode 0 restored

    ld a, [STUB_HIGH]
    ld [$A001], a
    ld a, [STUB_LOW]
    ld [$A002], a

    ; ---- back in mode 0, the 4000 bank must be $21 again -----------------
    ld a, [$4000]
    ld [$A003], a

    ; ---- control: plain low banking with BANK2 cleared -------------------
    xor a
    ld [$4000], a          ; BANK2 = 0
    ld a, 5
    ld [$2000], a          ; BANK1 = 5
    ld a, [$4000]
    ld [$A004], a

    ld a, $5A
    ld [$A00F], a
.done:
    jr .done

; Runs from WRAM: while mode 1 is active 0000-3FFF is banked away, so this
; code must not be in it.  BANK1/BANK2 are already set by the caller.
Stub:
    ld a, 1
    ld [$6000], a          ; mode 1
    ld a, [$0000]          ; must now be bank BANK2<<5 = $20
    ld [STUB_LOW], a
    ld a, [$4000]          ; must still be bank $21
    ld [STUB_HIGH], a
    xor a
    ld [$6000], a          ; mode 0 -- restores bank 0 under the return address
    ret
StubEnd:

; One signature byte at the start of each bank the test touches.
SECTION "b1",  ROMX[$4000], BANK[1]
    db $01
SECTION "b5",  ROMX[$4000], BANK[5]
    db $05
SECTION "b32", ROMX[$4000], BANK[32]
    db $20
SECTION "b33", ROMX[$4000], BANK[33]
    db $21
; Force the cart out to a full 1MB so banks $20/$21 actually exist.
SECTION "b63", ROMX[$4000], BANK[63]
    db $3F
