; HBlank DMA savestate replay test (issue #51, item 1)
;
; SaveIo captures FF55, but LoadIo replayed only FF51-FF54 -- so a state saved
; while an HBlank DMA was running came back with the transfer silently
; cancelled, and the game's remaining blocks never arrived.
;
; Replaying FF55 is not simply a matter of writing the saved byte back.  FF55
; reads bit 7 = 0 while a transfer is running, with the low bits holding
; remaining-1, and a *write* with bit 7 clear means something else entirely:
; it cancels a running HBlank transfer, or starts an immediate
; general-purpose DMA.  So only an active value may be replayed, and it has to
; be written with bit 7 set.
;
; Making this observable needs an HBlank DMA that is still running at save
; time and demonstrably not running at load time.  Both halves are arranged
; without depending on frame timing:
;
;   - An HBlank DMA only advances on the HBlank of a visible line with the LCD
;     on.  This ROM turns the LCD off immediately after starting one, so the
;     transfer freezes with all 128 blocks outstanding and stays that way for
;     the rest of the run.  FF55 reads $7F (bit 7 clear, remaining-1 = 127).
;   - The transfer is cancelled on a keypress rather than on a frame count.
;     The harness presses Up between the quicksave and the quickload, and the
;     runner auto-releases it after 15 frames, so after the state is restored
;     the ROM does not immediately cancel again.  Cancelled, FF55 reads $FF.
;
; So at the end of the run FF55 reads $7F if the active transfer was restored
; and $FF if it was not.  The cancel is idempotent -- it only fires while a
; transfer is actually running -- so a held key cannot turn into a stream of
; stray general-purpose DMAs.
;
; Results in cart RAM (dumped as the .sav):
;   A000   FF55 straight after starting the transfer  -- must be $7F
;   A001   FF55, re-stamped every loop (so: after the load)
;   A002   loop counter low   \ mirrored from WRAM, which a savestate rewinds
;   A003   loop counter high  /
;   A004   $5A once the set-up has run
;   A005   $01 once the ROM has seen Up and cancelled the transfer
;
; The -C is not optional: FF51-FF55 are CGB-only registers, and without the
; CGB flag in the header the cart runs as a DMG, every HDMA write is ignored
; and FF55 reads back $FF -- the ROM would report "no transfer" throughout and
; the test would be measuring nothing.
;
; Build:
;   rgbasm -o hd.o test_roms/hdma_state_test.asm
;   rgblink -o test_roms/hdma_state_test.gb hd.o
;   rgbfix -v -p 0 -t "HDMAST" -m 0x1B -r 2 -C test_roms/hdma_state_test.gb

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Counter", WRAM0[$C000]
wCount: ds 2

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

    ; ---- set up an HBlank DMA, then freeze it by turning the LCD off -----
    ; Source $0000 (this ROM), destination VRAM $8000.  Nothing reads the
    ; transferred bytes; FF55 is the whole observable.
    xor a
    ldh [$FF51], a         ; HDMA1 source high
    ldh [$FF52], a         ; HDMA2 source low
    ld a, $80
    ldh [$FF53], a         ; HDMA3 destination high -> $8000
    xor a
    ldh [$FF54], a         ; HDMA4 destination low

    xor a
    ldh [$FF40], a         ; LCD off: no visible HBlanks, so no blocks move

    ld a, $FF
    ldh [$FF55], a         ; bit 7 set = HBlank DMA, low bits 127 -> 128 blocks

    ldh a, [$FF55]
    ld [$A000], a          ; $7F: running, 128 blocks outstanding

    xor a
    ld [wCount], a
    ld [wCount + 1], a

    ld a, $5A
    ld [$A004], a

    ; The LCD is off for the whole run, so LY never advances and cannot pace
    ; the counter -- a per-iteration count would wrap 16 bits many times over.
    ; DIV runs regardless of the LCD, at 16384Hz, so counting its wraps gives
    ; a ~64Hz tick: a few thousand over the run, comfortably inside 16 bits.
    ldh a, [$FF04]
    ld b, a                ; b = previous DIV

.loop:
    ldh a, [$FF04]
    ld c, a
    cp b                   ; carry set means DIV went backwards, i.e. wrapped
    jr nc, .no_wrap
    ld hl, wCount
    inc [hl]
    jr nz, .no_wrap
    inc hl
    inc [hl]
.no_wrap:
    ld b, c

    ; ---- cancel the transfer the first time Up is seen ------------------
    ld a, $20
    ldh [$FF00], a         ; select the direction row
    ldh a, [$FF00]
    ldh a, [$FF00]         ; read twice, the usual settling read
    bit 2, a               ; Up: 0 = pressed
    jr nz, .no_key

    ldh a, [$FF55]
    bit 7, a               ; only cancel while a transfer is actually running,
    jr nz, .no_key         ; otherwise a bit-7-clear write starts a general DMA
    xor a
    ldh [$FF55], a         ; cancel
    ld a, $01
    ld [$A005], a
.no_key:

    ldh a, [$FF55]
    ld [$A001], a
    ld a, [wCount]
    ld [$A002], a
    ld a, [wCount + 1]
    ld [$A003], a
    jr .loop
