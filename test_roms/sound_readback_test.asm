; Sound register read-back mask test (issue #55, item 1)
;
; Every GB sound register has write-only or unused bits, and those bits read
; back as 1 on hardware.  chroma's _FFxxR handlers pass the GBA PSG register
; value straight through, and the GBA returns 0 for its write-only bits, so
; the whole set read back too low.  Blargg's dmg_sound "registers" test fails
; on this, and read-modify-write game code (ldh a,[rNR51] / or / ldh [rNR51],a
; is a common idiom) silently clears bits it never meant to touch.
;
; This ROM powers the APU on, writes a known value to every NRxx, and dumps
; the raw read-back so the harness can check it.  No channel is ever
; triggered (bit 7 of every NRx4 write is 0), so nothing here depends on
; envelope/sweep timing -- the values are stable whenever the ROM is sampled.
;
; Two controls guard against a fix that just returns $FF everywhere:
;   - the unused registers FF15/FF1F/FF27-FF2F must ALREADY read $FF
;   - wave RAM FF30-FF3F is fully readable and must read back exactly what
;     was written ($A5), NOT $FF
;
; Results in cart RAM (dumped as the .sav):
;   A000-A014  read-back of NR10,NR11,NR12,NR13,NR14, NR21,NR22,NR23,NR24,
;              NR30,NR31,NR32,NR33,NR34, NR41,NR42,NR43,NR44, NR50,NR51,NR52
;   A015       AND of every unused-register read (FF15,FF1F,FF27-FF2F)
;   A016       OR  of the same                    -- both must be $FF
;   A017       AND of wave RAM FF30-FF3F read-back
;   A018       OR  of the same                    -- both must be $A5
;   A01F       $5A when every step has run
;
; Build:
;   rgbasm -o snd.o test_roms/sound_readback_test.asm
;   rgblink -o test_roms/sound_readback_test.gb snd.o
;   rgbfix -v -p 0 -t "SOUNDRB" -m 0x1B -r 2 test_roms/sound_readback_test.gb

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
    ld b, 32
    xor a
.clear_results:
    ld [hl+], a
    dec b
    jr nz, .clear_results

    ; ---- power the APU on -----------------------------------------------
    ; While NR52 bit 7 is clear the APU ignores writes to NR10-NR51, so this
    ; has to come first or every write below is dropped.
    ld a, $80
    ldh [$FF26], a

    ; ---- write a known value to every register ---------------------------
    ; Chosen so that no expected read-back is $FF: a handler that blanket
    ; returns $FF has to fail somewhere.  NRx4 writes keep bit 7 clear so no
    ; channel is triggered and NR52's status bits stay quiet.
    ld a, $35
    ldh [$FF10], a         ; NR10  sweep
    ld a, $80
    ldh [$FF11], a         ; NR11  duty 10, length 0
    ld a, $F0
    ldh [$FF12], a         ; NR12  envelope (DAC on)
    ld a, $55
    ldh [$FF13], a         ; NR13  freq lo (write-only)
    xor a
    ldh [$FF14], a         ; NR14  no trigger, no length enable

    ld a, $40
    ldh [$FF16], a         ; NR21  duty 01, length 0
    ld a, $F0
    ldh [$FF17], a         ; NR22  envelope
    ld a, $55
    ldh [$FF18], a         ; NR23  freq lo (write-only)
    xor a
    ldh [$FF19], a         ; NR24

    xor a
    ldh [$FF1A], a         ; NR30  DAC off
    ld a, $55
    ldh [$FF1B], a         ; NR31  length (write-only)
    ld a, $20
    ldh [$FF1C], a         ; NR32  output level 01
    ld a, $55
    ldh [$FF1D], a         ; NR33  freq lo (write-only)
    xor a
    ldh [$FF1E], a         ; NR34

    ld a, $15
    ldh [$FF20], a         ; NR41  length (write-only)
    ld a, $F0
    ldh [$FF21], a         ; NR42  envelope
    ld a, $55
    ldh [$FF22], a         ; NR43  polynomial (fully readable)
    xor a
    ldh [$FF23], a         ; NR44

    ld a, $77
    ldh [$FF24], a         ; NR50  master volume
    ld a, $F3
    ldh [$FF25], a         ; NR51  output terminals

    ; ---- wave RAM: fully readable, used as a control ---------------------
    ld hl, $FF30
    ld b, 16
    ld a, $A5
.fill_wave:
    ld [hl+], a
    dec b
    jr nz, .fill_wave

    ; ---- dump every register read-back ----------------------------------
    ld hl, $A000
    ldh a, [$FF10]
    ld [hl+], a
    ldh a, [$FF11]
    ld [hl+], a
    ldh a, [$FF12]
    ld [hl+], a
    ldh a, [$FF13]
    ld [hl+], a
    ldh a, [$FF14]
    ld [hl+], a

    ldh a, [$FF16]
    ld [hl+], a
    ldh a, [$FF17]
    ld [hl+], a
    ldh a, [$FF18]
    ld [hl+], a
    ldh a, [$FF19]
    ld [hl+], a

    ldh a, [$FF1A]
    ld [hl+], a
    ldh a, [$FF1B]
    ld [hl+], a
    ldh a, [$FF1C]
    ld [hl+], a
    ldh a, [$FF1D]
    ld [hl+], a
    ldh a, [$FF1E]
    ld [hl+], a

    ldh a, [$FF20]
    ld [hl+], a
    ldh a, [$FF21]
    ld [hl+], a
    ldh a, [$FF22]
    ld [hl+], a
    ldh a, [$FF23]
    ld [hl+], a

    ldh a, [$FF24]
    ld [hl+], a
    ldh a, [$FF25]
    ld [hl+], a
    ldh a, [$FF26]
    ld [hl+], a            ; -> A014

    ; ---- control 1: the unused registers must already read $FF ----------
    ld c, $FF              ; running AND
    ld d, $00              ; running OR
    ldh a, [$FF15]
    call AccumUnused
    ldh a, [$FF1F]
    call AccumUnused
    ldh a, [$FF27]
    call AccumUnused
    ldh a, [$FF28]
    call AccumUnused
    ldh a, [$FF29]
    call AccumUnused
    ldh a, [$FF2A]
    call AccumUnused
    ldh a, [$FF2B]
    call AccumUnused
    ldh a, [$FF2C]
    call AccumUnused
    ldh a, [$FF2D]
    call AccumUnused
    ldh a, [$FF2E]
    call AccumUnused
    ldh a, [$FF2F]
    call AccumUnused
    ld a, c
    ld [$A015], a
    ld a, d
    ld [$A016], a

    ; ---- control 2: wave RAM must read back exactly what was written ----
    ld hl, $FF30
    ld b, 16
    ld c, $FF              ; running AND
    ld d, $00              ; running OR
.read_wave:
    ld a, [hl+]
    ld e, a
    and c
    ld c, a
    ld a, e
    or d
    ld d, a
    dec b
    jr nz, .read_wave
    ld a, c
    ld [$A017], a
    ld a, d
    ld [$A018], a

    ld a, $5A
    ld [$A01F], a
.done:
    jr .done

; a = byte just read; c &= a, d |= a.  Preserves nothing else.
AccumUnused:
    ld e, a
    and c
    ld c, a
    ld a, e
    or d
    ld d, a
    ret
