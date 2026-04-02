; RST Timing Test ROM
;
; Measures cycle counts for all RST instructions using DIV register.
; All RST variants should have identical timing (16 T-cycles).
; Also measures CALL (24 T-cycles) for comparison.
;
; Method: Reset DIV, execute padding + instruction + more padding to total
; exactly 256 T-cycles between two DIV reads. Delta should be 1.
;
; Results written to SRAM (A000-A010) for external verification:
;   A000: RST 00h DIV delta (expect 1)
;   A001: RST 08h DIV delta
;   A002: RST 10h DIV delta
;   A003: RST 18h DIV delta
;   A004: RST 20h DIV delta
;   A005: RST 28h DIV delta
;   A006: RST 30h DIV delta
;   A007: RST 38h DIV delta
;   A008: CALL DIV delta (expect 1)
;   A009: mismatch count (0 = all RSTs match)
;   A00A: RST00 - RST38 (expect 0)
;   A010: 0xFF sentinel

; RST vectors — each just returns immediately
SECTION "RST 00", ROM0[$0000]
    ret
SECTION "RST 08", ROM0[$0008]
    ret
SECTION "RST 10", ROM0[$0010]
    ret
SECTION "RST 18", ROM0[$0018]
    ret
SECTION "RST 20", ROM0[$0020]
    ret
SECTION "RST 28", ROM0[$0028]
    ret
SECTION "RST 30", ROM0[$0030]
    ret
SECTION "RST 38", ROM0[$0038]
    ret

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

; Declare SRAM
SECTION "SRAM Results", SRAM[$A000]
SramResults: ds 17

SECTION "Main", ROM0[$0150]
Main:
    di
    ld sp, $FFFE

    ; Enable SRAM
    ld a, $0A
    ld [$0000], a

    ; Clear SRAM results
    xor a
    ld hl, $A000
    REPT 17
    ld [hl+], a
    ENDR

    ; ---- Measure each RST variant ----
    ; Cycle budget between two DIV reads:
    ;   ldh a,[$04] = 12, ld b,a = 4, RST+RET = 32, NOPs, ldh a,[$04] = 12
    ;   Total = 60 + N*4. For 256 cycles: N=49.

    ; RST 00h
    xor a
    ldh [$04], a
    ldh a, [$04]
    ld b, a
    rst $00
    REPT 49
    nop
    ENDR
    ldh a, [$04]
    sub a, b
    ld [$A000], a

    ; RST 08h
    xor a
    ldh [$04], a
    ldh a, [$04]
    ld b, a
    rst $08
    REPT 49
    nop
    ENDR
    ldh a, [$04]
    sub a, b
    ld [$A001], a

    ; RST 10h
    xor a
    ldh [$04], a
    ldh a, [$04]
    ld b, a
    rst $10
    REPT 49
    nop
    ENDR
    ldh a, [$04]
    sub a, b
    ld [$A002], a

    ; RST 18h
    xor a
    ldh [$04], a
    ldh a, [$04]
    ld b, a
    rst $18
    REPT 49
    nop
    ENDR
    ldh a, [$04]
    sub a, b
    ld [$A003], a

    ; RST 20h
    xor a
    ldh [$04], a
    ldh a, [$04]
    ld b, a
    rst $20
    REPT 49
    nop
    ENDR
    ldh a, [$04]
    sub a, b
    ld [$A004], a

    ; RST 28h
    xor a
    ldh [$04], a
    ldh a, [$04]
    ld b, a
    rst $28
    REPT 49
    nop
    ENDR
    ldh a, [$04]
    sub a, b
    ld [$A005], a

    ; RST 30h
    xor a
    ldh [$04], a
    ldh a, [$04]
    ld b, a
    rst $30
    REPT 49
    nop
    ENDR
    ldh a, [$04]
    sub a, b
    ld [$A006], a

    ; RST 38h
    xor a
    ldh [$04], a
    ldh a, [$04]
    ld b, a
    rst $38
    REPT 49
    nop
    ENDR
    ldh a, [$04]
    sub a, b
    ld [$A007], a

    ; ---- CALL for comparison ----
    ; CALL=24, RET=16, total=40. Budget: 12+4+40+N*4+12 = 68+N*4 = 256, N=47
    xor a
    ldh [$04], a
    ldh a, [$04]
    ld b, a
    call CallTarget
    REPT 47
    nop
    ENDR
    ldh a, [$04]
    sub a, b
    ld [$A008], a

    ; ---- Check results ----
    ld a, [$A000]
    ld b, a
    ld c, 0
    ld hl, $A001
    ld a, [hl+]
    cp a, b
    jr z, .ok1
    inc c
.ok1:
    ld a, [hl+]
    cp a, b
    jr z, .ok2
    inc c
.ok2:
    ld a, [hl+]
    cp a, b
    jr z, .ok3
    inc c
.ok3:
    ld a, [hl+]
    cp a, b
    jr z, .ok4
    inc c
.ok4:
    ld a, [hl+]
    cp a, b
    jr z, .ok5
    inc c
.ok5:
    ld a, [hl+]
    cp a, b
    jr z, .ok6
    inc c
.ok6:
    ld a, [hl+]
    cp a, b
    jr z, .ok7
    inc c
.ok7:
    ld a, c
    ld [$A009], a

    ; RST00 - RST38 delta
    ld a, [$A000]
    ld b, a
    ld a, [$A007]
    sub a, b
    ld [$A00A], a

    ; Sentinel
    ld a, $FF
    ld [$A010], a

.loop:
    halt
    nop
    jr .loop

SECTION "CallTarget", ROM0[$0500]
CallTarget:
    ret
