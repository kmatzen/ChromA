; Serial register behaviour and transfer duration (issue #153).
;
; Four things, all of which ChromA got wrong and none of which need a second
; Game Boy attached -- with no cable the other end holds the line high, which
; is a perfectly well defined thing to emulate:
;
;   A. SB reads back the byte written to it, while no transfer has completed.
;      ChromA returned a flat 0xFF.
;   B. SC's unused bits read 1.  ChromA returned the stored byte.
;   C. An internal-clock transfer takes 4096 T-cycles, measured here as the
;      number of poll-loop iterations SC bit 7 stays set.  ChromA completed at
;      the next scanline boundary, so at most 456.
;   D. Once the transfer completes SB reads 0xFF -- the idle line shifted in --
;      and the serial interrupt is requested.
;
; D is the half that makes A safe.  Pokemon's link-cable detection writes a
; byte, starts a transfer and reads SB back; if it sees its own byte it decides
; a cable is attached.  Returning the written byte *without* modelling the
; transfer is what broke it during the #110 work.
;
; Results at $A000, $5A at $A00F when done.

DEF SB      EQU $FF01
DEF SC      EQU $FF02
DEF IF_REG  EQU $FF0F

DEF R_SB_BEFORE  EQU $A000
DEF R_SC_READ    EQU $A001
DEF R_SB_AFTER   EQU $A002
DEF R_COUNT_LO   EQU $A003
DEF R_COUNT_HI   EQU $A004
DEF R_IF         EQU $A005
DEF R_DONE       EQU $A00F

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
    ld [$4000], a

    ; ---- A: SB reads back what was written ---------------------------------
    ld a, $5A
    ldh [SB], a
    ldh a, [SB]
    ld [R_SB_BEFORE], a

    ; ---- B: SC unused bits ------------------------------------------------
    ; Write only the transfer-start and internal-clock bits; everything else
    ; is unused on DMG and must still read back as 1.
    ld a, $81
    ldh [SC], a
    ldh a, [SC]
    ld [R_SC_READ], a

    ; The write above already started the transfer.  Clear IF so the flag
    ; recorded below is this transfer's.
    xor a
    ldh [IF_REG], a

    ; ---- C: how long the transfer stays busy -------------------------------
    ld hl, 0
.poll:
    inc hl
    ; Bail out rather than hang if the transfer never completes.
    ld a, h
    cp $40
    jr nc, .timeout
    ldh a, [SC]
    bit 7, a
    jr nz, .poll
.timeout:

    ld a, l
    ld [R_COUNT_LO], a
    ld a, h
    ld [R_COUNT_HI], a

    ; ---- D: SB after the transfer, and the interrupt -----------------------
    ldh a, [SB]
    ld [R_SB_AFTER], a
    ldh a, [IF_REG]
    ld [R_IF], a

    ld a, $5A
    ld [R_DONE], a
.done:
    jr .done
