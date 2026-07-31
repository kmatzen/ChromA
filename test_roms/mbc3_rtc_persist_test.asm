; Report the MBC3 RTC at boot, without touching it (issue #49 item 5).
;
; The software clock used to restart at 10:00:00 on every power-on, so a
; game's in-game clock ran backwards between sessions.  This probe latches
; once at boot and writes the time to cart RAM, so running it twice against
; the same save file shows whether the clock carried over.
;
; It deliberately never writes an RTC register: a clock-set would be adopted
; by the emulator and would mask the thing being measured.
;
; Results in cart RAM (bank 0):
;   A000 seconds   A001 minutes   A002 hours   A003 day low
;   A00F $5A when the probe ran to completion
;
; Build:
;   rgbasm -o p.o test_roms/mbc3_rtc_persist_test.asm
;   rgblink -o test_roms/mbc3_rtc_persist_test.gb p.o
;   rgbfix -v -p 0 -t "MBC3PERSIST" -m 0x10 -r 2 test_roms/mbc3_rtc_persist_test.gb

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Main", ROM0[$0150]
Main:
    di
    ld sp, $FFFE
    ld a, $0A
    ld [$0000], a          ; enable cart RAM / RTC access

    xor a                  ; latch the counters: 0 then 1 to $6000
    ld [$6000], a
    ld a, 1
    ld [$6000], a

    ld b, $08
    ld c, $00
    call ReadRtcToRam
    ld b, $09
    ld c, $01
    call ReadRtcToRam
    ld b, $0A
    ld c, $02
    call ReadRtcToRam
    ld b, $0B
    ld c, $03
    call ReadRtcToRam

    call SelectRam
    ld a, $5A
    ld [$A00F], a
.done:
    jr .done

SelectRam:
    xor a
    ld [$4000], a
    ret

; b = RTC register, c = result offset.  Reading has to finish before the
; store: storing needs RAM bank 0, which unmaps the RTC registers.
ReadRtcToRam:
    ld a, b
    ld [$4000], a
    ld a, [$A000]
    ld d, a
    call SelectRam
    ld h, $A0
    ld l, c
    ld [hl], d
    ret
