; HALT Bug Test ROM
;
; Tests the DMG HALT bug: when HALT executes with IME=0 and an
; interrupt is pending (IE & IF != 0), the CPU fails to increment
; PC, causing the next opcode byte to be read twice.
;
; Example: HALT / LD A,$12
; Opcode bytes: 76 3E 12
; Normal: HALT skips, then LD A,$12 → A=$12
; With bug: HALT skips, PC doesn't increment, reads 3E twice:
;           LD A,$3E → A=$3E (the opcode byte itself)
;
; Results in SRAM:
;   A000: A register value after HALT bug sequence
;         Expected on hardware: 0x3E (the bug exists on BOTH DMG and CGB;
;         only the interrupt-dispatch-during-halt variant differs)
;         An emulator without the bug reports 0x12
;   A001: 0x01 if HALT bug present, 0x00 if not
;   A010: 0xFF sentinel

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

; Declare SRAM
SECTION "SRAM Results", SRAM[$A000]
SramResults: ds 17

SECTION "Main", ROM0[$0150]
Main:
    di                      ; IME = 0
    ld sp, $FFFE

    ; Enable SRAM
    ld a, $0A
    ld [$0000], a

    ; Clear results
    xor a
    ld [$A000], a
    ld [$A001], a
    ld [$A010], a

    ; Set up: enable VBlank interrupt in IE, request it in IF
    ld a, $01               ; VBlank
    ldh [$FFFF], a            ; IE = VBlank enabled
    ld a, $01
    ldh [$FF0F], a            ; IF = VBlank pending

    ; Now execute HALT with IME=0 and pending interrupt.
    ; The CPU should skip the HALT but (on DMG) fail to
    ; increment PC, causing the next byte (0x3E = LD A,n)
    ; to be read as both the opcode AND the operand.
    ;
    ; Bytes: 76 3E 12
    ; With bug:    reads 3E as opcode (LD A,n), reads 3E as operand → A=0x3E
    ; Without bug: reads 3E as opcode (LD A,n), reads 12 as operand → A=0x12
    ;
    ; NOTE: must be `db $76`, not `halt` -- rgbasm pads `halt` with an
    ; automatic NOP, which turns the sequence into 76 00 3E 12 and makes
    ; the test vacuous (A=0x12 on every emulator, bug or no bug).
    ;
    ; When the bug fires, the $12 byte then executes as an instruction:
    ; LD (DE),A.  Point DE at scratch WRAM first -- at boot DE points
    ; into the $0000 mapper region, and the stray write ($3E) would
    ; DISABLE cartridge SRAM, silently dropping every result store.
    ld de, $C100
    db $76
    ld a, $12               ; Opcode 3E, operand 12

    ; Store result
    ld [$A000], a           ; A = 0x3E (bug) or 0x12 (no bug)

    ; Check if bug was present
    cp a, $3E
    jr nz, .noBug
    ld a, $01
    ld [$A001], a           ; Bug detected
    jr .done
.noBug:
    xor a
    ld [$A001], a           ; No bug
.done:
    ; Sentinel
    ld a, $FF
    ld [$A010], a

.loop:
    halt
    nop
    jr .loop
