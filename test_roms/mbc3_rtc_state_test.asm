; MBC3 RTC-select rehydration test (issue #49, item 4)
;
; Writing 8-C to 4000-5FFF on an MBC3 maps an RTC register over A000-BFFF
; instead of a RAM bank, and the selection lives in mapperdata+4.  A savestate
; records that byte, but AfterLoadState always called RamSelect, which maps
; SRAM unconditionally -- so after loading a state that had been taken with an
; RTC register selected, A000-BFFF read back as cart RAM until the game
; happened to reselect.  Pokemon G/S/C read the clock this way.
;
; Telling the two mappings apart needs a byte that differs between them, which
; is what the sentinel is for: cart RAM holds $E7 at A100, and the RTC seconds
; register holds a BCD value that can never be $E7 (its high nibble is at most
; 5).  So reading A100 says which one is mapped.
;
; The awkward part is that while an RTC register is selected there is nowhere
; to write results -- every store to A000-BFFF goes to the clock, not to RAM.
; So the ROM only writes its results at the very end, after a keypress tells
; it to sample the mapping and then switch back to a RAM bank:
;
;   phase 1  RTC seconds selected; idle.  This is the state a quicksave here
;            captures.
;   phase 2  entered on Up: select RAM bank 0, so the live mapping now differs
;            from the saved one.  A quickload has to undo this.
;   phase 3  entered on Down: read A100 through whatever mapping is currently
;            in effect and stash it, THEN select RAM bank 0 and start writing
;            results.  The stashed byte is the answer.
;
; The runner auto-releases inputs after 15 frames, so a phase entered before a
; quickload is not immediately re-entered after it.
;
; Results in cart RAM (dumped as the .sav):
;   A000   the byte read from A100 under the mapping in effect at phase 3
;   A001   phase reached ($03 once results are being written)
;   A002   frame counter low   \ mirrored from WRAM, which a savestate rewinds
;   A003   frame counter high  /
;   A004   $5A once the set-up has run
;   A100   sentinel $E7, written while a RAM bank was selected
;
; Build (-m 0x10 is MBC3+TIMER+RAM+BATTERY; without the TIMER the RTC
; registers do not exist and every read falls back to cart RAM):
;   rgbasm -o rs.o test_roms/mbc3_rtc_state_test.asm
;   rgblink -o test_roms/mbc3_rtc_state_test.gb rs.o
;   rgbfix -v -p 0 -t "MBC3RTCST" -m 0x10 -r 2 test_roms/mbc3_rtc_state_test.gb

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "State", WRAM0[$C000]
wFrames:  ds 2
wPhase:   ds 1
wSample:  ds 1

SECTION "Main", ROM0[$0150]
Main:
    di
    ld sp, $FFFE

    ld a, $0A
    ld [$0000], a          ; enable cart RAM / RTC
    xor a
    ld [$4000], a          ; select RAM bank 0

    ld hl, $A000
    ld b, 16
    xor a
.clear_results:
    ld [hl+], a
    dec b
    jr nz, .clear_results

    ld a, $E7
    ld [$A100], a          ; sentinel: this is what cart RAM reads back

    ld a, $5A
    ld [$A004], a

    ; ---- latch the clock, then map the seconds register ------------------
    xor a
    ld [$6000], a
    ld a, $01
    ld [$6000], a          ; 0 -> 1 latches the current time
    ld a, $08
    ld [$4000], a          ; RTC seconds now covers A000-BFFF

    xor a
    ld [wFrames], a
    ld [wFrames + 1], a
    ld [wPhase], a
    ld [wSample], a
    inc a
    ld [wPhase], a         ; phase 1

.loop:
.wait_vblank:
    ldh a, [$FF44]
    cp 144
    jr nz, .wait_vblank

    ld hl, wFrames
    inc [hl]
    jr nz, .counted
    inc hl
    inc [hl]
.counted:

    ; Re-latch every frame so the seconds register tracks elapsed time.  A
    ; clock latched once at boot reads $00, and $00 is weak evidence -- a
    ; handler that was never installed could read that too.  A live value is
    ; unmistakably the clock.  The latch register is at 6000-7FFF, so this
    ; works whichever mapping A000-BFFF currently has.
    xor a
    ld [$6000], a
    ld a, $01
    ld [$6000], a

    ; ---- read the keys ---------------------------------------------------
    ld a, $20
    ldh [$FF00], a         ; select the direction row
    ldh a, [$FF00]
    ldh a, [$FF00]         ; settling read
    ld c, a

    ld a, [wPhase]
    cp 3
    jr z, .writing         ; already sampled; just keep the results fresh

    bit 3, c               ; Down: 0 = pressed
    jr z, .sample

    bit 2, c               ; Up: 0 = pressed
    jr nz, .next

    ; phase 2: deliberately move the live mapping away from the saved one
    xor a
    ld [$4000], a          ; select RAM bank 0
    ld a, 2
    ld [wPhase], a
    jr .next

.sample:
    ; phase 3: sample A100 through whatever mapping is in effect *first* --
    ; selecting a RAM bank to make the results writable would destroy the
    ; very thing being measured.
    ld a, [$A100]
    ld [wSample], a
    xor a
    ld [$4000], a          ; now a RAM bank, so cart RAM is writable again
    ld a, 3
    ld [wPhase], a

.writing:
    ld a, [wSample]
    ld [$A000], a
    ld a, [wPhase]
    ld [$A001], a
    ld a, [wFrames]
    ld [$A002], a
    ld a, [wFrames + 1]
    ld [$A003], a

.next:
.wait_active:
    ldh a, [$FF44]
    cp 144
    jr z, .wait_active
    jr .loop
