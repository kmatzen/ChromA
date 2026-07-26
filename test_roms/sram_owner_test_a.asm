; SRAM cross-game ownership regression test -- game "A" (issue #48)
;
; Paired with sram_owner_test_b.asm.  Both are MBC5+RAM+BATTERY carts with
; 8KB of SRAM; they differ only in their signature byte and their ID tag,
; which is what gives them different checksum_this() values.
;
; Each ROM, at boot:
;   1. copies the 16 bytes it INHERITED at A000 to A100 (the "echo"), then
;   2. stamps its own 16-byte signature over A000.
;
; The echo is the whole point: it records what the write-through region
; held at the moment this game booted, which is exactly what the ownership
; handoff is supposed to control.  test_sram_ownership.py boots A, then B,
; then A again against one shared .sav and reads the echoes back:
;
;   run 2 (B) echo == A's signature  -> B inherited A's save (the bug)
;   run 3 (A) echo == A's signature  -> A's save was archived and restored
;   run 3 (A) echo == B's signature  -> A got handed B's save (the bug)
;
; Build:
;   rgbasm -o a.o test_roms/sram_owner_test_a.asm
;   rgblink -o test_roms/sram_owner_test_a.gb a.o
;   rgbfix -v -p 0 -t "SRAMOWNA" -m 0x1B -r 2 test_roms/sram_owner_test_a.gb

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "IdTag", ROM0[$0180]
    ; checksum_this() sums 4 bytes at every 128-byte boundary, so $0180 is
    ; one of the offsets it actually reads.  A and B must differ WITHIN
    ; these first 4 bytes or the emulator sees them as the same ROM.
    db $A1,$A1,$A1,$A1

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
    ld a, $A1
    ld [hl+], a
    dec b
    jr nz, .fill

.done:
    jr .done
