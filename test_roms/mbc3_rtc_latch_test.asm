; MBC3 RTC: does a clock-set survive the latch? (issue #49)
;
; mbc3_rtc_test.asm checks that the RTC registers accept writes and read back,
; deliberately without latching in between.  That is only half the story: the
; latch is what a real clock-set flow does next, and ChromA derives the time
; from its frame counter, so a write that is merely stored into mapperdata is
; recomputed away the moment the game latches.  The value snaps back and the
; game's clock-set is lost -- the symptom issue #49 actually describes.
;
; This probe does the whole flow: halt, write every field, release halt,
; latch, read back.  It then checks that the halt bit really stops the
; counters, and that they move again once it is cleared.
;
; The RTC registers are BINARY on hardware -- seconds and minutes 0-59, hours
; 0-23, DL the low 8 bits of a 9-bit day counter -- so the values below cross
; the bus as binary regardless of how an emulator stores them internally.
;
; Results in cart RAM (bank 0):
;   A000  seconds after clock-set + latch    expect 0
;   A001  minutes after clock-set + latch    expect 30
;   A002  hours   after clock-set + latch    expect 12
;   A003  day low after clock-set + latch    expect 20
;   A004  DH      after clock-set + latch    expect 0
;   A005  seconds halted, first latch
;   A006  seconds halted, 240 frames later   expect == A005
;   A007  DH      while halted               expect bit 6 set
;   A008  seconds running, first latch
;   A009  seconds running, 240 frames later  expect != A008
;   A00F  $5A once every step has run
;
; Build:
;   rgbasm -o rtc2.o test_roms/mbc3_rtc_latch_test.asm
;   rgblink -o test_roms/mbc3_rtc_latch_test.gb rtc2.o
;   rgbfix -v -p 0 -t "MBC3LATCH" -m 0x10 -r 2 test_roms/mbc3_rtc_latch_test.gb

DEF SEC_REG  EQU $08
DEF MIN_REG  EQU $09
DEF HRS_REG  EQU $0A
DEF DAYL_REG EQU $0B
DEF DH_REG   EQU $0C

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Main", ROM0[$0150]
Main:
    di
    ld sp, $FFFE

    ; The frame wait below counts VBlanks, so the LCD has to be running.
    ld a, $91
    ldh [$FF40], a

    ld a, $0A
    ld [$0000], a          ; enable cart RAM / RTC register access

    call SelectRam
    ld hl, $A000
    ld b, 16
    xor a
.clear:
    ld [hl+], a
    dec b
    jr nz, .clear

    ; ---- halt, set every field, release halt, latch ----------------------
    ; Games halt first so the counters cannot tick between the writes.
    ld b, DH_REG
    ld c, $40              ; halt = 1, day bit 8 = 0
    call WriteRtc

    ld b, SEC_REG
    ld c, 0
    call WriteRtc

    ld b, MIN_REG
    ld c, 30
    call WriteRtc

    ld b, HRS_REG
    ld c, 12
    call WriteRtc

    ld b, DAYL_REG
    ld c, 20               ; past 15, where a BCD/binary mix-up would show
    call WriteRtc

    ld b, DH_REG
    ld c, $00              ; halt = 0
    call WriteRtc

    call Latch

    ld b, SEC_REG
    ld c, $00
    call ReadRtcToRam
    ld b, MIN_REG
    ld c, $01
    call ReadRtcToRam
    ld b, HRS_REG
    ld c, $02
    call ReadRtcToRam
    ld b, DAYL_REG
    ld c, $03
    call ReadRtcToRam
    ld b, DH_REG
    ld c, $04
    call ReadRtcToRam

    ; ---- halted: the counters must not move ------------------------------
    ld b, DH_REG
    ld c, $40
    call WriteRtc

    call Latch
    ld b, SEC_REG
    ld c, $05
    call ReadRtcToRam

    call Wait240

    call Latch
    ld b, SEC_REG
    ld c, $06
    call ReadRtcToRam
    ld b, DH_REG
    ld c, $07
    call ReadRtcToRam

    ; ---- running again: the counters must move ---------------------------
    ld b, DH_REG
    ld c, $00
    call WriteRtc

    call Latch
    ld b, SEC_REG
    ld c, $08
    call ReadRtcToRam

    call Wait240

    call Latch
    ld b, SEC_REG
    ld c, $09
    call ReadRtcToRam

    call SelectRam
    ld a, $5A
    ld [$A00F], a
.done:
    jr .done

; ---------------------------------------------------------------------------
; Latch the counters into the readable registers: 0 then 1 to $6000.
Latch:
    xor a
    ld [$6000], a
    ld a, 1
    ld [$6000], a
    ret

; Select RAM bank 0, so A000-BFFF is cart RAM again rather than an RTC
; register.  Every result store goes through here.
SelectRam:
    xor a
    ld [$4000], a
    ret

; b = RTC register, c = value.  Leaves RAM bank 0 selected.
WriteRtc:
    ld a, b
    ld [$4000], a
    ld a, c
    ld [$A000], a
    jr SelectRam

; b = RTC register, c = result offset in cart RAM.  The read has to finish
; before the store: storing needs RAM bank 0 selected, which unmaps the RTC.
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

; Wait 240 frames -- just over 4 seconds of emulated time, comfortably past
; the one-second granularity of the seconds register.
Wait240:
    push bc
    ld b, 240
.frame:
.wait_vblank:
    ldh a, [$FF44]
    cp 144
    jr nz, .wait_vblank
.wait_leave:
    ldh a, [$FF44]
    cp 144
    jr z, .wait_leave
    dec b
    jr nz, .frame
    pop bc
    ret
