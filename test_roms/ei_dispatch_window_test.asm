; EI-inside-dispatch-window test ROM (hijack (1) landing inside window (3))
;
; checkIRQDelayed (src/timeout.s) parks the real scanline handler in
; nexttimeout_alt and sets nexttimeout = checkMasterIRQ_minus12 when an
; interrupt is dispatched at a scanline boundary with <= 8 cycles of
; overshoot, then lets 1-2 guest instructions run before the dispatch.
; If one of those instructions is an EI taking the deferral path, _FB
; saves nexttimeout -- checkMasterIRQ_minus12 itself -- into
; nexttimeout_alt, destroying the parked handler.  minus12's restore then
; loads minus12 back into nexttimeout forever: LY freezes and the
; scanline machine is dead.
;
; Reaching the window is deterministic: every SM83 instruction duration
; is a multiple of 4 T-cycles, so any scanline-boundary overshoot is
; 0/4/8 cycles -- always within the window.  With the timer firing every
; scanline (TAC=%101) and an `ei / nop` spam stream (consecutive EIs
; take the ei_immediate path, so the NOPs are required to force the
; deferral path), an EI executes inside the window almost immediately.
;
; Results in SRAM (A000-A00F):
;   A000: phase marker -- highest phase reached (see PHASE_* below)
;   A001: timer ISR invocation count (mod 256, must be nonzero)
;   A002: spam-survival result  $AA = pass, $EE = LY frozen after spam
;   A004: LY sampled before the wait loop
;   A005: LY sampled after the wait loop
;   A00F: $FF sentinel -- absent means the emulator wedged mid-test

DEF rIF    EQU $FF0F
DEF rIE    EQU $FFFF
DEF rLCDC  EQU $FF40
DEF rLY    EQU $FF44
DEF rTIMA  EQU $FF05
DEF rTMA   EQU $FF06
DEF rTAC   EQU $FF07

DEF PHASE_INIT      EQU $01
DEF PHASE_SPAM_DONE EQU $02
DEF PHASE_DONE      EQU $03

SECTION "Timer Vector", ROM0[$0050]
    jp TimerHandler

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

    ; LCD on so LY advances
    ld a, $91
    ldh [rLCDC], a

    ; timer IRQ roughly every scanline: TAC=%101 (enabled, 262144 Hz)
    xor a
    ldh [rTMA], a
    ldh [rTIMA], a
    ld a, $05
    ldh [rTAC], a
    ld a, $04                 ; timer only
    ldh [rIE], a

    ld a, PHASE_INIT
    ld [$A000], a

    ; IME on via an EI allowed to complete normally
    ei
    nop

; ---------------------------------------------------------------------------
; Spam ei/nop with a timer IRQ pending at nearly every scanline boundary.
; Each boundary with a pending IRQ opens the minus12 window; the first
; window whose 1-2 instructions include a deferring EI triggers the
; nexttimeout_alt clobber on unfixed builds.
; ---------------------------------------------------------------------------
    ld bc, 2048               ; ~2048 * 64 * 8 cycles ~= 7 frames of spam
.spamloop:
    REPT 32
    ei
    nop
    ENDR
    dec bc
    ld a, b
    or c
    jr nz, .spamloop

    ld a, PHASE_SPAM_DONE
    ld [$A000], a

    ; scanline machine still alive?
    di
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
    jr .store
.advanced:
    ld [$A005], a
    ld a, $AA
.store:
    ld [$A002], a

    ld a, [wIsrCount]
    ld [$A001], a
    ld a, PHASE_DONE
    ld [$A000], a
    ld a, $FF
    ld [$A00F], a             ; sentinel
.loop:
    jr .loop

SECTION "Timer Handler", ROM0[$0060]
TimerHandler:
    push af
    ld a, [wIsrCount]
    inc a
    ld [wIsrCount], a
    pop af
    reti
