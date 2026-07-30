; STAT (FF41) register-accuracy probe -- issue #52
;
; Covers the parts of the STAT/LY accuracy cluster that guest code can actually
; observe.  Each phase leaves its result in cart RAM; test_stat_ly.py asserts
; them, and also runs this same ROM directly in mGBA's own DMG core so the
; expected values are backed by an independent implementation rather than by
; this comment.
;
; Phases:
;   bit7       64 reads of FF41 with the LCD on, ANDed and ORed together.  Bit 7
;              is wired high on hardware, so it must survive the AND.
;   lcd-off    LCD off, 256 reads.  Hardware reports mode 0 the whole time; the
;              emulator's cycle counter keeps running while disabled, so the
;              mode bits used to freewheel through 0/2/3.  The OR of the mode
;              bits across every read must be 0, and bit 7 must still survive.
;   lyc-off    LCD off, LYC swept across all 154 line values with LYC IE on.
;              The internal scanline counter free-runs while disabled, so
;              without a gate the writes raise STAT from a counter hardware is
;              not even reporting.  IF bit 1 must stay clear.
;   statw-off  LCD off, FF41 written repeatedly.  With no LCD there is no STAT
;              line to drive, so IF bit 1 must stay clear.
;   statw-on   LCD on, DMG, write FF41 from mode 0 with only mode-1 IE set.
;              Mode-1 IE cannot fire on a visible line, so any IF bit 1 here is
;              the DMG STAT-write bug -- which is real hardware behaviour and
;              must be KEPT.  This is the positive control for statw-off: it
;              proves the gate above rejects for the right reason.
;   mode2-vbl  Entering line 144 asserts the mode-2 (OAM) condition as well as
;              mode 1.  Arm mode-2 IE only, clear IF during line 143, then read
;              IF once LY reads 144.  Bit 1 must be set.
;   blocking   Count STAT IRQs over 4 frames with (a) mode-0 IE alone and
;              (b) mode-0 + LYC IE.  The LYC coincidence cannot produce a rising
;              edge while mode-0 IE already holds the line high through the
;              preceding HBlank, so (b) must not exceed (a) by one-per-frame.
;   lyc0-delay Informational, for the LY=153->0 early-transition window: with
;              LYC=0 and LYC IE, count loop iterations from LY=144 until the
;              LYC=0 STAT IRQ lands.  Reported, not asserted -- see the issue
;              discussion of item 6.
;
; Results in cart RAM (dumped as the .sav):
;   A000  AND of 64 FF41 reads, LCD on      -- bit 7 must be set
;   A001  OR  of the same reads             -- bit 7 set, mode bits nonzero
;   A002  OR of (FF41 & 3), 256 reads, LCD off  -- must be $00
;   A003  AND of those reads                -- bit 7 must be set
;   A004  OR of those reads                 -- bit 7 must be set
;   A005  IF after LYC sweep with LCD off   -- bit 1 must be clear
;   A006  IF after FF41 writes, LCD off     -- bit 1 must be clear
;   A007  IF after FF41 write, LCD on (DMG) -- bit 1 must be SET (control)
;   A009  IF after LY 143->144, mode-2 IE   -- bit 1 must be set
;   A00A  STAT count over 4 frames, mode-0 IE only   (16-bit LE)
;   A00C  STAT count over 4 frames, mode-0 + LYC IE  (16-bit LE)
;   A00E  loop iterations from LY=144 to the LYC=0 STAT IRQ (16-bit LE)
;   A010  last phase reached (for diagnosing a hang)
;   A01F  $5A once every phase has run
;
; Build (the same object is fixed twice, once per model, so that the DMG-only
; STAT-write bug can be checked to be present on DMG and absent on CGB):
;   rgbasm -o stat.o test_roms/stat_ly_test.asm
;   rgblink -o test_roms/stat_ly_test.gb stat.o
;   rgbfix -v -p 0 -t "STATLY" -m 0x1B -r 2 test_roms/stat_ly_test.gb
;   rgblink -o test_roms/stat_ly_test_cgb.gbc stat.o
;   rgbfix -v -C -p 0 -t "STATLY" -m 0x1B -r 2 test_roms/stat_ly_test_cgb.gbc

SECTION "VBlank", ROM0[$40]
    jp VblankIrq
SECTION "LCDStat", ROM0[$48]
    jp StatIrq
SECTION "Timer", ROM0[$50]
    reti
SECTION "Serial", ROM0[$58]
    reti
SECTION "Joypad", ROM0[$60]
    reti

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Vars", WRAM0[$C000]
StatLo:   db
StatHi:   db
Frames:   db

SECTION "Main", ROM0[$0150]

; 16-bit count of STAT dispatches.
StatIrq:
    push af
    ld a, [StatLo]
    inc a
    ld [StatLo], a
    jr nz, .nocarry
    ld a, [StatHi]
    inc a
    ld [StatHi], a
.nocarry:
    pop af
    reti

VblankIrq:
    push af
    ld a, [Frames]
    inc a
    ld [Frames], a
    pop af
    reti

; Wait until LY is in VBlank / back on a visible line.  Only safe with the LCD
; on: LY does not advance while it is off.
WaitVbl:
    ldh a, [$FF44]
    cp 144
    jr c, WaitVbl
    ret
WaitVisible:
    ldh a, [$FF44]
    cp 144
    jr nc, WaitVisible
    ret
WaitFrame:
    call WaitVbl
    call WaitVisible
    ret

; d = STAT byte to arm, e = LYC.  Counts STAT dispatches over 4 frames,
; returns the count in bc.
MeasureStat:
    di
    call WaitVbl
    call WaitVisible
    ld a, e
    ldh [$FF45], a
    ld a, d
    ldh [$FF41], a
    xor a
    ld [StatLo], a
    ld [StatHi], a
    ld [Frames], a
    ldh [$FF0F], a          ; drop anything the FF41 write itself pulsed
    ld a, $03               ; VBlank (for the frame count) + STAT
    ldh [$FFFF], a
    ei
.wait:
    ld a, [Frames]
    cp 4
    jr c, .wait
    di
    xor a
    ldh [$FFFF], a
    ldh [$FF41], a
    ld a, [StatLo]
    ld c, a
    ld a, [StatHi]
    ld b, a
    ret

Main:
    di
    ld sp, $FFFE
    ld a, $0A
    ld [$0000], a           ; MBC5: enable cart RAM
    xor a
    ld [$4000], a           ; MBC5: RAM bank 0

    ld hl, $A000
    ld b, 32
.clear_results:
    xor a
    ld [hl+], a
    dec b
    jr nz, .clear_results

    ; ---- bit 7, LCD on ---------------------------------------------------
    ld a, 1
    ld [$A010], a
    ld b, 64
    ld c, $FF               ; running AND
    ld d, $00               ; running OR
.bit7:
    ldh a, [$FF41]
    ld e, a
    ld a, c
    and e
    ld c, a
    ld a, d
    or e
    ld d, a
    dec b
    jr nz, .bit7
    ld a, c
    ld [$A000], a
    ld a, d
    ld [$A001], a

    ; ---- mode bits with the LCD off --------------------------------------
    ld a, 2
    ld [$A010], a
    call WaitVbl            ; switch the LCD off during VBlank
    ldh a, [$FF40]
    and $7F
    ldh [$FF40], a

    ld b, 0                 ; 256 reads
    ld c, $FF               ; running AND
    ld d, $00               ; running OR
    ld e, $00               ; running OR of the mode bits alone
.lcdoff:
    ldh a, [$FF41]
    ld h, a
    and $03
    or e
    ld e, a
    ld a, c
    and h
    ld c, a
    ld a, d
    or h
    ld d, a
    dec b
    jr nz, .lcdoff
    ld a, e
    ld [$A002], a
    ld a, c
    ld [$A003], a
    ld a, d
    ld [$A004], a

    ; ---- LYC writes with the LCD off -------------------------------------
    ld a, 3
    ld [$A010], a
    ld a, $40               ; LYC IE only
    ldh [$FF41], a
    xor a
    ldh [$FF0F], a
    ld b, 0
    ld c, 0
.lycoff:
    ld a, c
    ldh [$FF45], a          ; sweep every line value the counter could hold
    inc c
    ld a, c
    cp 154
    jr c, .lycoff_next
    ld c, 0
.lycoff_next:
    dec b
    jr nz, .lycoff
    ldh a, [$FF0F]
    ld [$A005], a

    ; ---- FF41 writes with the LCD off ------------------------------------
    ld a, 4
    ld [$A010], a
    xor a
    ldh [$FF0F], a
    ld b, 32
.statwoff:
    ld a, $08
    ldh [$FF41], a
    ld a, $20
    ldh [$FF41], a
    ld a, $28
    ldh [$FF41], a
    xor a
    ldh [$FF41], a
    dec b
    jr nz, .statwoff
    ldh a, [$FF0F]
    ld [$A006], a

    ; ---- LCD back on, then the DMG write-bug control ---------------------
    ld a, 5
    ld [$A010], a
    xor a
    ldh [$FF41], a
    ldh a, [$FF40]
    or $80
    ldh [$FF40], a
    call WaitFrame
    call WaitFrame

.await_mode0:
    ldh a, [$FF41]          ; land in mode 0, where a condition can match
    and $03
    jr nz, .await_mode0
    xor a
    ldh [$FF0F], a
    ld a, $10               ; mode-1 IE only: cannot fire on a visible line
    ldh [$FF41], a
    ldh a, [$FF0F]
    ld [$A007], a

    ; ---- mode-2 condition at VBlank start --------------------------------
    ld a, 6
    ld [$A010], a
    xor a
    ldh [$FF41], a
.await_143:
    ldh a, [$FF44]
    cp 143
    jr nz, .await_143
    ld a, $20               ; mode-2 IE only
    ldh [$FF41], a
    xor a
    ldh [$FF0F], a          ; clear while still on line 143
.await_144:
    ldh a, [$FF44]
    cp 144
    jr nz, .await_144
    ldh a, [$FF0F]
    ld [$A009], a

    ; ---- STAT IRQ blocking ------------------------------------------------
    ld a, 7
    ld [$A010], a
    ld d, $08               ; mode-0 IE alone
    ld e, $50
    call MeasureStat
    ld a, c
    ld [$A00A], a
    ld a, b
    ld [$A00B], a

    ld a, 8
    ld [$A010], a
    ld d, $48               ; mode-0 IE + LYC IE
    ld e, $50
    call MeasureStat
    ld a, c
    ld [$A00C], a
    ld a, b
    ld [$A00D], a

    ; ---- LY=153->0 early transition, measured ----------------------------
    ld a, 9
    ld [$A010], a
    di
    xor a
    ldh [$FFFF], a
    ld a, $40               ; LYC IE only
    ldh [$FF41], a
    xor a
    ldh [$FF45], a          ; LYC = 0
.await_vbl_start:
    ldh a, [$FF44]
    cp 144
    jr nz, .await_vbl_start
    xor a
    ldh [$FF0F], a
    ld bc, 0
.lyc0_wait:
    inc bc
    ld a, b
    cp 8                    ; bail out rather than spin forever
    jr nc, .lyc0_done
    ldh a, [$FF0F]
    and $02
    jr z, .lyc0_wait
.lyc0_done:
    ld a, c
    ld [$A00E], a
    ld a, b
    ld [$A00F], a

    ld a, $5A
    ld [$A01F], a
.hang:
    jr .hang
