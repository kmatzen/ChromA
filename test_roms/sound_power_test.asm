; APU power-off shadow test (issue #55, item 2)
;
; chroma keeps `sound_shadow`, a 9-byte copy of the halves of NR11/NR13/NR14,
; NR21/NR23/NR24 and NR31/NR33/NR34 that the hardware will not read back.
; SaveIo copies it into a savestate verbatim, because those bits cannot be
; recovered from the GBA registers.  Writing 0 to NR52 bit 7 powers the APU
; down and resets every PSG register to zero -- but nothing cleared the
; shadow, so a state saved after a power-cycle carried write-only values the
; APU no longer held, and loading it put them back.
;
; The power-cycle alone is not observable: LoadIo replays FF10-FF3F in
; ascending order, so if the APU was *off* at save time the NR52 write at
; FF26 wipes everything replayed before it.  Powering back on afterwards is
; what makes it visible, and it is also what real games do -- "NR52=0 then
; NR52=$80" is the standard APU init.  So this ROM writes a duty to NR11,
; power-cycles, powers back on, and leaves the emulator to be quicksaved and
; quickloaded underneath it:
;
;   NR11 = $C0     duty 11; shadow records $C0
;   NR52 = $00     APU off; the GBA clears NR11, the shadow keeps $C0
;   NR52 = $80     APU on again; NR11 genuinely reads $3F now
;   <quicksave>    SaveIo writes the shadow over the read value at offset $11
;   <quickload>    LoadIo replays it while the APU is on -- nothing wipes it
;
; After the load NR11 reads $3F if the shadow was cleared with the APU, and
; $FF ($C0 | the $3F of write-only length bits) if the stale duty came back.
;
; The 16-bit frame counter lives in WRAM, not cart RAM, so it is rewound by
; the savestate whether or not cart RAM is part of one.  The harness runs this
; ROM twice -- once with the quicksave/quickload keys and once without -- and
; a lower final count in the first run is what proves the load actually
; happened, so a NR11 read-back of $3F cannot pass for the trivial reason that
; no state was ever restored.
;
; Results in cart RAM (dumped as the .sav):
;   A000   NR11 read-back straight after the power-cycle, before any save
;   A001   NR11 read-back, re-stamped every frame (so: after the load)
;   A002   frame counter low  \  mirrored from WRAM every frame
;   A003   frame counter high /
;   A004   $5A once the set-up has run
;
; Build:
;   rgbasm -o snd.o test_roms/sound_power_test.asm
;   rgblink -o test_roms/sound_power_test.gb snd.o
;   rgbfix -v -p 0 -t "SOUNDPW" -m 0x1B -r 2 test_roms/sound_power_test.gb

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Counter", WRAM0[$C000]
wFrames: ds 2

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
    xor a
.clear_results:
    ld [hl+], a
    dec b
    jr nz, .clear_results

    ; ---- give NR11 a duty, then power-cycle the APU ---------------------
    ld a, $80
    ldh [$FF26], a         ; NR52: APU on
    ld a, $C0
    ldh [$FF11], a         ; NR11: duty 11, length 0 -- shadow records $C0
    xor a
    ldh [$FF26], a         ; NR52: APU off -- the GBA clears NR11
    ld a, $80
    ldh [$FF26], a         ; NR52: APU on again

    ldh a, [$FF11]
    ld [$A000], a          ; $3F: the duty really is gone from the register

    xor a
    ld [wFrames], a
    ld [wFrames + 1], a

    ld a, $5A
    ld [$A004], a

    ; ---- free-running loop -----------------------------------------------
    ; One pass per frame, so the counter stays well inside 16 bits over the
    ; few thousand frames the harness runs.
.loop:
.wait_vblank:
    ldh a, [$FF44]
    cp 144
    jr nz, .wait_vblank

    ld hl, wFrames
    inc [hl]
    jr nz, .no_carry
    inc hl
    inc [hl]
.no_carry:

    ldh a, [$FF11]
    ld [$A001], a          ; NR11 read-back
    ld a, [wFrames]
    ld [$A002], a
    ld a, [wFrames + 1]
    ld [$A003], a

.wait_active:
    ldh a, [$FF44]
    cp 144
    jr z, .wait_active
    jr .loop
