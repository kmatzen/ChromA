; Sound post-boot state and wave RAM bank test (issue #55, items 4 and 3)
;
; Item 4 -- post-boot register values.  A cart started without running a boot
; ROM has to find the sound registers in the state the DMG boot ROM leaves
; them in.  chroma's Sound_reset wrote zero to every PSG register, and its own
; comments flagged the gap ("should read 0xF3BF").  After the read-back masks
; landed (item 1) all but two of the post-boot values fell out of a zeroed
; register anyway, because they are made up entirely of write-only and unused
; bits.  The two that do not are NR11's duty (boot leaves 10 -> reads $BF, not
; $3F) and NR12's envelope ($F3, not $00).  Games that read-modify-write NR12
; at start-up, or check the DAC before triggering, see the difference.
;
; Item 3 -- wave RAM writes while channel 3 is playing.  The GBA has two wave
; banks: SOUND3CNT_L bit 6 picks the one that plays, and $04000090-9F exposes
; the *other* one.  chroma flips that bit together with NR30 bit 7, so wave
; data written while the channel is off lands in the bank that starts playing
; when it is switched on -- the double buffer Alleyway depends on.  The GB has
; a single buffer, though, so a write made while the channel is *playing* also
; has to reach the live bank, and it did not: it went to the idle one.  CGB
; games that stream wave data without toggling NR30 kept hearing the previous
; waveform.
;
; The bank probe is deliberately ordered so the two banks hold different data:
;   NR30=0  -> window is the bank that is NOT playing; fill it with $00
;   NR30=$80, trigger -> the $00 bank is now live, window swings to the other
;   write $A5 through the window while the channel plays
;   NR30=0  -> window swings back to the bank that was just playing
;   read it: $A5 only if the streaming write reached the live bank
;
; Results in cart RAM (dumped as the .sav):
;   A000-A014  post-boot read-back of NR10,NR11,NR12,NR13,NR14, NR21,NR22,
;              NR23,NR24, NR30,NR31,NR32,NR33,NR34, NR41,NR42,NR43,NR44,
;              NR50,NR51,NR52 -- sampled before the ROM writes any register
;   A020       AND of the wave RAM read-back after streaming while playing
;   A021       OR  of the same                    -- both must be $A5
;   A022       AND of the off/on double-buffer control read-back
;   A023       OR  of the same                    -- both must be $5A
;   A03F       $5A when every step has run
;
; Build:
;   rgbasm -o snd.o test_roms/sound_state_test.asm
;   rgblink -o test_roms/sound_state_test.gb snd.o
;   rgbfix -v -p 0 -t "SOUNDST" -m 0x1B -r 2 test_roms/sound_state_test.gb

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
    ld b, 64
    xor a
.clear_results:
    ld [hl+], a
    dec b
    jr nz, .clear_results

    ; ---- item 4: sample the registers before touching any of them --------
    ; Nothing above writes to $FF10-$FF3F, so this is the state the emulator
    ; handed the cart.
    ld hl, $A000
    ldh a, [$FF10]
    ld [hl+], a            ; NR10 -> A000
    ldh a, [$FF11]
    ld [hl+], a
    ldh a, [$FF12]
    ld [hl+], a
    ldh a, [$FF13]
    ld [hl+], a
    ldh a, [$FF14]
    ld [hl+], a

    ldh a, [$FF16]
    ld [hl+], a            ; NR21 -> A005
    ldh a, [$FF17]
    ld [hl+], a
    ldh a, [$FF18]
    ld [hl+], a
    ldh a, [$FF19]
    ld [hl+], a

    ldh a, [$FF1A]
    ld [hl+], a            ; NR30 -> A009
    ldh a, [$FF1B]
    ld [hl+], a
    ldh a, [$FF1C]
    ld [hl+], a
    ldh a, [$FF1D]
    ld [hl+], a
    ldh a, [$FF1E]
    ld [hl+], a

    ldh a, [$FF20]
    ld [hl+], a            ; NR41 -> A00E
    ldh a, [$FF21]
    ld [hl+], a
    ldh a, [$FF22]
    ld [hl+], a
    ldh a, [$FF23]
    ld [hl+], a

    ldh a, [$FF24]
    ld [hl+], a            ; NR50 -> A012
    ldh a, [$FF25]
    ld [hl+], a
    ldh a, [$FF26]
    ld [hl+], a            ; NR52 -> A014

    ; ---- item 3: wave RAM write while channel 3 is playing ---------------
    ld a, $80
    ldh [$FF26], a         ; APU on (it already is; writes below need it)

    xor a
    ldh [$FF1A], a         ; NR30 DAC off -> window is the idle bank
    ld a, $00
    call FillWave          ; that bank now holds $00

    ld a, $80
    ldh [$FF1A], a         ; NR30 DAC on -> the $00 bank is live now
    ld a, $FF
    ldh [$FF1B], a         ; NR31 length
    ld a, $20
    ldh [$FF1C], a         ; NR32 volume 100%
    xor a
    ldh [$FF1D], a         ; NR33 frequency lo
    ld a, $80
    ldh [$FF1E], a         ; NR34 trigger, length disabled -- channel 3 plays

    ld a, $A5
    call FillWave          ; stream new data while it plays

    xor a
    ldh [$FF1A], a         ; NR30 off -> window swings to the bank that played
    call ReadWave
    ld a, c
    ld [$A020], a
    ld a, d
    ld [$A021], a

    ; ---- control: the off/on double buffer still works -------------------
    ; This is the path the bank flip in _FF1AW exists for, and it passed
    ; before the fix too -- it is here so a fix that reaches the live bank by
    ; breaking the idle one cannot go unnoticed.  Channel 3 is off, so the
    ; window is the bank that will start playing on the next NR30 write.
    ld a, $5A
    call FillWave
    ld a, $80
    ldh [$FF1A], a         ; on: that bank goes live
    xor a
    ldh [$FF1A], a         ; off: window swings back to it
    call ReadWave
    ld a, c
    ld [$A022], a
    ld a, d
    ld [$A023], a

    ld a, $5A
    ld [$A03F], a
.done:
    jr .done

; Write a to all 16 bytes of wave RAM.  Clobbers a, b, hl.
FillWave:
    ld hl, $FF30
    ld b, 16
.fill:
    ld [hl+], a
    dec b
    jr nz, .fill
    ret

; Read wave RAM, accumulating AND into c and OR into d.  Clobbers a, b, e, hl.
ReadWave:
    ld hl, $FF30
    ld b, 16
    ld c, $FF
    ld d, $00
.read:
    ld a, [hl+]
    ld e, a
    and c
    ld c, a
    ld a, e
    or d
    ld d, a
    dec b
    jr nz, .read
    ret
