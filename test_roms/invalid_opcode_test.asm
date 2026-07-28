; Invalid opcode / unmapped-region regression test (issue #56)
;
; Three contained accuracy bugs, all reachable from ordinary GB code:
;
;   1. Opcode $ED had a fully commented-out body and fell straight through
;      into jr_fixup, which rewrites gb_pc from a stale register -- so
;      executing one byte of garbage teleported the program counter.  Every
;      other invalid opcode routes to _xx.
;   2. FEA0-FEFF is not OAM.  OAM_W refuses to write past offset $A0, but
;      OAM_R had no bound and read off the end of the 160-byte OAM buffer
;      into whatever EWRAM follows it.  Hardware returns $00.
;   3. KEY1 ($FF4D) only has bits 7 and 0; bits 1-6 read 1 on hardware.
;      This ROM is CGB-compatible so the register is live.
;
; The $ED subtest runs LAST on purpose: on a build where it still
; teleports, the other two subtests have already stored their results.
;
; Results in cart RAM (dumped as the .sav):
;   A000  $11 -- reached the $ED
;   A001  $22 -- the instruction AFTER the $ED ran, so PC did not teleport
;   A002  $33 -- still executing straight-line code afterwards
;   A003  OR of every byte read from FEA0-FEFF   -- must be $00
;   A004  AND of every byte read from FEA0-FEFF  -- must be $00
;   A005  KEY1 read with bits 7 and 0 masked off -- must be $7E
;   A00F  $5A when every subtest has run
;
; Build:
;   rgbasm -o inv.o test_roms/invalid_opcode_test.asm
;   rgblink -o test_roms/invalid_opcode_test.gb inv.o
;   rgbfix -v -p 0 -c -t "INVALIDOP" -m 0x1B -r 2 test_roms/invalid_opcode_test.gb

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

    ld hl, $A000
    ld b, 16
.clear_results:
    xor a
    ld [hl+], a
    dec b
    jr nz, .clear_results

    ; ---- 2. FEA0-FEFF reads ---------------------------------------------
    ; Fill OAM proper with a pattern first, so a read that walks off the end
    ; of the buffer has something recognisable next to it, and so an
    ; all-zero result cannot come from an all-zero buffer.
    ld hl, $FE00
    ld b, $A0
    ld a, $5A
.fill_oam:
    ld [hl+], a
    dec b
    jr nz, .fill_oam

    ld hl, $FEA0
    ld b, $60              ; FEA0..FEFF
    ld c, $00              ; running OR
    ld d, $FF              ; running AND
.read_unused:
    ld a, [hl+]
    ld e, a
    or c
    ld c, a                ; c |= byte
    ld a, e
    and d
    ld d, a                ; d &= byte
    dec b
    jr nz, .read_unused
    ld a, c
    ld [$A003], a
    ld a, d
    ld [$A004], a

    ; ---- 3. KEY1 unused bits --------------------------------------------
    ldh a, [$FF4D]
    and $7E                ; drop bit 7 (current speed) and bit 0 (armed)
    ld [$A005], a

    ; ---- 1. an invalid opcode must just be skipped ----------------------
    ; If $ED still falls into jr_fixup, PC is rewritten from a stale
    ; register and the two stores below never run.  A000 is written first
    ; so the .sav distinguishes "teleported" from "never got here".
    ld a, $11
    ld [$A000], a
    db $ED
    ld a, $22
    ld [$A001], a
    ld a, $33
    ld [$A002], a

    ld a, $5A
    ld [$A00F], a
.done:
    jr .done
