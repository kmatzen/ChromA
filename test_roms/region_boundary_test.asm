; Instruction fetch across the echo/OAM region boundary (issue #116, split
; out of #106).
;
; gb_pc is a raw host pointer and nothing re-checks it as the CPU advances,
; so execution running off the end of a region walks into whatever host
; memory follows.  Echo RAM ends at $FDFF, which is 0x1DFF into XGB_RAM, so
; a fetch crossing into $FE00 read $DE00's byte out of WRAM instead of OAM
; and the CPU wandered until it died -- a hang, not a wrong value.
;
; Three cases in increasing order of suspicion, so the progress byte says
; which one broke:
;   case 1  ($A000, expect $55)  an instruction wholly inside echo RAM
;   case 2  ($A001, expect $66)  a single-byte RET on the last echo byte
;   case 3  ($A002, expect $77)  an operand that crosses $FDFF -> $FE00
; $A00E counts completed cases, $A00F is $5A once the ROM finishes.
; $DE00 holds $99 -- the decoy a straddle bug reads instead of the OAM byte.
;
; Build: rgbasm -o x.o x.asm && rgblink -o x.gb x.o
;        rgbfix -v -p 0xFF -m 0x03 -r 2 x.gb
; The MBC1+RAM header matters: without it the SRAM writes go nowhere and
; every case reads back $FF, which looks far more dramatic than it is.
;
; Reference (mGBA): progress 3, $55/$66/$77.

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Main", ROM0[$0150]
Main:
    di
    ld sp, $FFFE
    ld a, $0A
    ld [$0000], a
    xor a
    ld [$4000], a
    ld hl, $A000
    ld b, 16
.clear:
    xor a
    ld [hl+], a
    dec b
    jr nz, .clear

    xor a
    ldh [$FF40], a         ; LCD off so OAM is accessible

    ld a, $3E              ; case 1: wholly inside echo RAM
    ld [$DDFC], a
    ld a, $55
    ld [$DDFD], a
    ld a, $C9
    ld [$DDFE], a

    ld a, $C9              ; case 2: single-byte ret on the last echo byte
    ld [$DDFF], a

    ld a, $77
    ld [$FE00], a          ; case 3 operand, in OAM
    ld a, $C9
    ld [$FE01], a
    ld a, $99
    ld [$DE00], a          ; decoy a straddle bug picks up instead

    xor a
    call $FDFC             ; case 1
    ld [$A000], a
    ld a, 1
    ld [$A00E], a

    ld a, $66
    call $FDFF             ; case 2
    ld [$A001], a
    ld a, 2
    ld [$A00E], a

    ld a, $3E              ; make $FDFF an opcode that needs an operand
    ld [$DDFF], a
    xor a
    call $FDFF             ; case 3 -- operand crosses into OAM
    ld [$A002], a
    ld a, 3
    ld [$A00E], a

    ld a, $5A
    ld [$A00F], a
.done:
    jr .done
