; IF (FF0F) register semantics regression test (issue #42)
;
; Two related holes in the interrupt-flag emulation:
;
;   1. _FF0FR returned the raw stored IF byte.  Hardware wires the top three
;      bits high, so FF0F always reads back 0xE0 | IF.  Anything doing
;      full-byte arithmetic on `ldh a,($FF0F)` -- Zerd no Densetsu is the
;      known case -- saw the wrong value.
;   2. _FF0FW stored all 8 bits.  Only 5 interrupts exist, so the phantom
;      upper bits could then match the same bits in IE (a full 8-bit R/W
;      register on hardware, which a game may legitimately leave set).
;      checkIRQ ANDed IE & IF with no 0x1F mask, none of the five `tst`
;      checks in the priority chain claimed the IRQ, and control fell out of
;      _irqGBZ80_ into its unknown-IRQ tail, which dispatches to vector 0x40.
;      A game that never enabled VBlank got VBlank interrupts anyway.
;
; Phases:
;   read-back  with IME=0, write four values to FF0F and read each straight
;              back.  Nothing clears IF while IME=0, so the 0xFF cases are
;              exact; the 0x00/0xE0 cases only assert the upper bits, since
;              a VBlank may set bit 0 between the write and the read.
;   spurious   IF <- 0xFF, IE <- 0xE0 (phantom bits ONLY -- no real interrupt
;              is enabled), IME=1, then idle.  Handlers on all five vectors
;              count dispatches.  Any count here is the bug: with IE's five
;              real bits clear, nothing may ever be dispatched.
;   control    IE <- 0x01 (VBlank), IME=1, idle.  The count must be nonzero,
;              which proves interrupts dispatch at all -- otherwise a zero in
;              the spurious phase would mean nothing.
;
; Results in cart RAM (dumped as the .sav):
;   A000  FF0F read back after writing $00   -- upper 3 bits must be set
;   A001  FF0F read back after writing $FF   -- must be exactly $FF
;   A002  FF0F read back after writing $1F   -- must be exactly $FF
;   A003  FF0F read back after writing $E0   -- upper set, low bits not $1F
;   A004  interrupts dispatched with IE=$E0  -- must be $00
;   A005  interrupts dispatched with IE=$01  -- must be nonzero (control)
;   A006  $5A once the spurious phase finished
;   A007  $5A once the control phase finished
;   A00F  $5A when every phase has run
;
; Build:
;   rgbasm -o if.o test_roms/if_register_test.asm
;   rgblink -o test_roms/if_register_test.gb if.o
;   rgbfix -v -p 0 -t "IFREG" -m 0x1B -r 2 test_roms/if_register_test.gb

SECTION "VBlank", ROM0[$40]
    jp IrqHandler
SECTION "LCDStat", ROM0[$48]
    jp IrqHandler
SECTION "Timer", ROM0[$50]
    jp IrqHandler
SECTION "Serial", ROM0[$58]
    jp IrqHandler
SECTION "Joypad", ROM0[$60]
    jp IrqHandler

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Vars", WRAM0[$C000]
IrqCount:  db

SECTION "Main", ROM0[$0150]
; Every vector lands here.  Which vector fired does not matter: during the
; spurious phase no vector may fire at all, and during the control phase only
; VBlank is enabled.
IrqHandler:
    push af
    ld a, [IrqCount]
    inc a
    ld [IrqCount], a
    pop af
    reti

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

    xor a
    ld [IrqCount], a

    ; ---- read-back semantics (IME still 0, so nothing clears IF) ----------
    xor a                  ; $00 -> low bits clear, upper 3 still read 1
    ldh [$FF0F], a
    ldh a, [$FF0F]
    ld [$A000], a

    ld a, $FF              ; $FF -> stores $1F, reads back $E0|$1F = $FF
    ldh [$FF0F], a
    ldh a, [$FF0F]
    ld [$A001], a

    ld a, $1F              ; same value by a different route
    ldh [$FF0F], a
    ldh a, [$FF0F]
    ld [$A002], a

    ld a, $E0              ; phantom bits only -> the 5 real bits stay clear
    ldh [$FF0F], a
    ldh a, [$FF0F]
    ld [$A003], a

    ; ---- spurious-dispatch phase -----------------------------------------
    ; Leave every real IF flag set, then enable ONLY the phantom bits in IE.
    ; IE & IF must come out zero once masked to the five real interrupts.
    ld a, $FF
    ldh [$FF0F], a
    ld a, $E0
    ld [$FFFF], a
    xor a
    ld [IrqCount], a
    ei

    ld c, 60
.spurious_loop:
    call WaitFrame
    dec c
    jr nz, .spurious_loop

    di
    ld a, [IrqCount]
    ld [$A004], a
    ld a, $5A
    ld [$A006], a

    ; ---- control phase: a real VBlank must still dispatch -----------------
    xor a
    ldh [$FF0F], a
    ld a, $01
    ld [$FFFF], a
    xor a
    ld [IrqCount], a
    ei

    ld c, 60
.control_loop:
    call WaitFrame
    dec c
    jr nz, .control_loop

    di
    ld a, [IrqCount]
    ld [$A005], a
    ld a, $5A
    ld [$A007], a

    ld a, $5A
    ld [$A00F], a
.done:
    jr .done

; One LCD frame, counted off LY.
WaitFrame:
    push af
.wait_vblank:
    ldh a, [$FF44]
    cp 144
    jr nz, .wait_vblank
.wait_out:
    ldh a, [$FF44]
    cp 144
    jr z, .wait_out
    pop af
    ret
