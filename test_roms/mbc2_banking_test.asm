; MBC2 register-decode and RAM-model test (issue #50, MBC2 half)
;
; Two separate bugs, both reachable from ordinary MBC2 game code:
;
;   1. Register decode.  On MBC2 it is address bit 8 ALONE that selects the
;      register, anywhere in 0000-3FFF: A8 set = ROM bank, A8 clear = RAM
;      enable.  chroma wired one handler per 8KB block instead, so a RAM
;      enable written to 2000-3FFF and a bank select written to 0000-1FFF
;      were both silently dropped.
;   2. RAM model.  MBC2 has 512 half-bytes, not 8KB.  A000-BFFF echoes every
;      512 bytes, and only the low nibble is connected -- the upper nibble
;      reads back as 1.  chroma read and wrote a flat 8KB buffer, so the
;      echo was absent and reads returned the raw stored byte.
;
; Results in cart RAM.  NOTE the emulator writes the full byte through to
; GBA SRAM, so the .sav shows raw stored bytes; values the ROM itself read
; back through the cart come out nibble-masked (0xFn) once the fix is in.
;
;   A010  read of A000 after writing $5A there   -- $FA fixed, $5A broken
;   A011  read of A200 (echo of A000)            -- $FA fixed, $00 broken
;   A012  read of A000 after writing $B7 to A200 -- $F7 fixed, $5A broken
;   A013  scratch for the RAM-enable test
;   A016  read of A013 after enabling RAM via 2000 -- $F3 fixed, $00 broken
;   A014  bank signature after selecting bank 2 via 0100 -- $02 fixed, $01 broken
;   A015  bank signature after selecting bank 3 via 2100 -- $03 on both (control)
;   A01F  $5A when every step has run
;
; Build:
;   rgbasm -o mbc2b.o test_roms/mbc2_banking_test.asm
;   rgblink -o test_roms/mbc2_banking_test.gb mbc2b.o
;   rgbfix -v -p 0 -t "MBC2BANK" -m 0x06 -r 0 test_roms/mbc2_banking_test.gb

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Main", ROM0[$0150]
Main:
    di
    ld sp, $FFFE

    ; Enable RAM the ordinary way (A8 clear, low block) -- this path works
    ; on both builds, so the ROM can always record its results.
    ld a, $0A
    ld [$0000], a

    ld hl, $A000
    ld b, 32
    xor a
.clear:
    ld [hl+], a
    dec b
    jr nz, .clear

    ; ---- 2a. the low nibble and the 512-byte echo ------------------------
    ld a, $5A
    ld [$A000], a
    ld a, [$A000]
    ld [$A010], a          ; $FA once only the low nibble is wired up

    ld a, [$A200]
    ld [$A011], a          ; A200 must echo A000

    ld a, $B7
    ld [$A200], a          ; a write through the echo must land on A000
    ld a, [$A000]
    ld [$A012], a

    ; ---- 1a. RAM enable must be decoded at 2000-3FFF too -----------------
    ; Disable RAM (A8 clear, works on both), then try to re-enable it from
    ; the upper block.  If that write is dropped the store below is dropped
    ; with it and A013 keeps the 0 it was cleared to.
    xor a
    ld [$0000], a          ; RAM off
    ld a, $0A
    ld [$2000], a          ; A8 clear -> RAM enable, even up here
    ld a, $33
    ld [$A013], a          ; only lands if the enable above was honoured

    ld a, $0A
    ld [$0000], a          ; make sure RAM is on for the rest of the run
    ld a, [$A013]
    ld [$A016], a

    ; ---- 1b. ROM bank select must be decoded at 0000-1FFF too ------------
    ld a, 2
    ld [$0100], a          ; A8 set -> ROM bank select, even down here
    ld a, [$4000]
    ld [$A014], a

    ; control: the same select through the address games normally use.
    ; This works on both builds and proves banking itself is functional,
    ; so a failure above is about decode and not about mapping.
    ld a, 3
    ld [$2100], a
    ld a, [$4000]
    ld [$A015], a

    ld a, $5A
    ld [$A01F], a
.done:
    jr .done

; One signature byte at the start of each switchable bank.
SECTION "bank1", ROMX[$4000], BANK[1]
    db $01
    ds $3FFF, $11

SECTION "bank2", ROMX[$4000], BANK[2]
    db $02
    ds $3FFF, $22

SECTION "bank3", ROMX[$4000], BANK[3]
    db $03
    ds $3FFF, $33
