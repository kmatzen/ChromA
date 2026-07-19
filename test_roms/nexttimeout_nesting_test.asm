; nexttimeout_alt Nesting Test ROM
;
; ChromA implements three "hijack nexttimeout, stash the old value in
; nexttimeout_alt, restore it later" mechanisms that all share ONE global slot:
;
;   1. EI deferral            src/gbz80.s:1704  -> ei_finish
;   2. immediate_check_irq_2  src/timeout.s:370 -> no_more_irq_hack
;   3. checkIRQDelayed        src/timeout.s:546 -> checkMasterIRQ_minus12
;
; plus a fourth site that overwrites nexttimeout outright:
;
;   4. FF40_W turning the LCD on   src/lcd.s:3760/3765
;
; The only guard is src/timeout.s:365-367, which stops (2) from clobbering (3).
; Nothing stops (2) clobbering (1), or (4) landing on top of (1).
;
; This ROM exercises the two unguarded pairs that are reachable from GB code.
;
; Results in SRAM (A000-A00F):
;   A000: phase marker -- highest phase reached (see PHASE_* below)
;   A001: total ISR invocations
;   A002: test C result  $AA = pass, $EE = fail (EI silently lost)
;   A003: test A result  $AA = pass, $EE = fail (scanline machine frozen)
;   A004: LY sampled before test A wait loop
;   A005: LY sampled after  test A wait loop
;   A00F: $FF sentinel -- absent means the emulator never got this far

DEF rIF    EQU $FF0F
DEF rIE    EQU $FFFF
DEF rLCDC  EQU $FF40
DEF rLY    EQU $FF44

DEF PHASE_INIT    EQU $01
DEF PHASE_C_DONE  EQU $02
DEF PHASE_A_ARMED EQU $03
DEF PHASE_A_PAST  EQU $04
DEF PHASE_A_DONE  EQU $05

SECTION "VBlank Vector", ROM0[$0040]
    jp VBlankHandler

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "SRAM Results", SRAM[$A000]
SramResults: ds 16

SECTION "WRAM", WRAM0[$C000]
wIsrCount: ds 1

SECTION "Main", ROM0[$0150]
Main:
    di
    ld sp, $FFFE

    ; enable cartridge SRAM (MBC1) so results reach the .sav via write-through
    ld a, $0A
    ld [$0000], a

    ; clear result area
    ld hl, $A000
    ld b, 16
    xor a
.clear:
    ld [hl+], a
    dec b
    jr nz, .clear

    xor a
    ld [wIsrCount], a
    ldh [rIF], a
    ld a, $01                 ; VBlank only
    ldh [rIE], a

    ld a, PHASE_INIT
    ld [$A000], a

; ---------------------------------------------------------------------------
; Test C -- writer (4) landing inside window (1).
;
;   EI defers, then the very next instruction turns the LCD on.  FF40_W
;   overwrites nexttimeout with a scanline state, so ei_finish never runs and
;   CYC_IE is never set: the EI is silently lost.  (It also orphans the word
;   EI pushed on the ARM stack.)
;
; Detection: with IME supposedly on and a VBlank pending, the ISR must fire.
; ---------------------------------------------------------------------------
TestC:
    di
    xor a
    ldh [rLCDC], a            ; LCD off, so the next write is an off->on edge
    ldh [rIF], a

    ld a, $91                 ; LCD on, BG on
    ei                        ; <-- deferral begins
    ldh [rLCDC], a            ; <-- FF40_W overwrites nexttimeout here

    ; If the EI survived, IME is on. Raise VBlank and see if the ISR runs.
    ld a, $01
    ldh [rIF], a
    nop
    nop
    nop
    nop

    ld a, [wIsrCount]
    or a
    jr nz, .pass
    ld a, $EE                 ; ISR never ran -> EI was lost
    jr .store
.pass:
    ld a, $AA
.store:
    ld [$A002], a

    ld a, PHASE_C_DONE
    ld [$A000], a

; ---------------------------------------------------------------------------
; Test A -- hijack (2) landing inside window (1).
;
;   Requires CYC_IE already set when EI executes.  CYC_MASK is CYCLE-1 = $0F
;   and CYC_IE is $01 (src/equates.h:514-525), so EI's
;   `ands cycles,cycles,#CYC_MASK` preserves CYC_IE.  A write to IF inside the
;   deferral window then reaches immediate_check_irq with (IE & IF) != 0, and
;   immediate_check_irq_2's guard only tests for checkMasterIRQ_minus12 -- so
;   it overwrites nexttimeout_alt, which is currently holding the real
;   scanline state.  Predicted result: nexttimeout ends up pointing at
;   ei_finish permanently and the scanline state machine never advances.
;
; Detection: LY must keep changing.
; ---------------------------------------------------------------------------
TestA:
    ; make sure the LCD is on so LY advances, well clear of any EI window
    ld a, $91
    ldh [rLCDC], a
    ld a, $01
    ldh [rIE], a

    ; set CYC_IE via a normal EI that is allowed to complete
    ei
    nop

    xor a
    ldh [rIF], a              ; no interrupt pending going in

    ld a, PHASE_A_ARMED
    ld [$A000], a

    ld a, $01
    ei                        ; <-- deferral begins, CYC_IE already set
    ldh [rIF], a              ; <-- immediate_check_irq_2 fires in the window

    ld a, PHASE_A_PAST
    ld [$A000], a

    ; scanline machine still alive?
    ldh a, [rLY]
    ld [$A004], a
    ld b, a
    ld de, $4000              ; generous bound; LY changes every ~456 cycles
.wait:
    ldh a, [rLY]
    cp b
    jr nz, .advanced
    dec de
    ld a, d
    or e
    jr nz, .wait

    ldh a, [rLY]
    ld [$A005], a
    ld a, $EE                 ; LY frozen -> scanline state machine lost
    jr .storeA
.advanced:
    ld [$A005], a
    ld a, $AA
.storeA:
    ld [$A003], a

    ld a, PHASE_A_DONE
    ld [$A000], a

; ---------------------------------------------------------------------------
Done:
    ld a, [wIsrCount]
    ld [$A001], a
    ld a, $FF
    ld [$A00F], a             ; sentinel
.loop:
    halt
    nop
    jr .loop

SECTION "VBlank Handler", ROM0[$0200]
VBlankHandler:
    push af
    ld a, [wIsrCount]
    inc a
    ld [wIsrCount], a
    pop af
    reti
