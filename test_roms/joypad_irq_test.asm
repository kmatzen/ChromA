; Joypad interrupt / FF00 refresh regression test (issue #43)
;
; Two related holes in the FF00 emulation:
;
;   1. joy0serial -- the byte joy0_R hands back -- was only ever recomputed
;      when the game WROTE FF00.  A game that sets the select bits once and
;      then just polls saw frozen input forever.
;   2. Nothing in the tree ever set IF bit 4, so the joypad interrupt never
;      fired and a game that HALTs with IE=0x10 waiting on input hung.
;
; Phases (the harness presses A once inside each):
;   loop 1  select the button line ONCE, then only READ FF00 -- this is the
;           stale-poll case, and it only sees the press once (1) is fixed
;   loop 2  rewrite FF00 before every read -- the control: this always
;           worked, so it must pass before and after the fix
;   halt    IE=0x10, IME=1, HALT.  Only a joypad interrupt can wake it.
;
; Results in cart RAM (dumped as the .sav):
;   A000  joypad interrupt count (handler at $0060)
;   A001  buttons seen pressed in loop 1 (stale poll)   -- $01 once fixed
;   A002  buttons seen pressed in loop 2 (control)      -- $01 either way
;   A003  $5A when loop 1 finished
;   A005  $5A when loop 2 finished
;   A006  $01 on entering HALT, $5A once something woke it
;   A008  the last raw FF00 byte read in loop 1 (diagnostic)
;   A009  frame counter, low byte  (diagnostic: did the press land in phase?)
;   A00A  frame counter, high byte
;   A00F  $5A when every phase has run
;
; Note P14/P15 are active low: writing $10 leaves bit 4 high (directions off)
; and bit 5 low, which is what SELECTS the buttons.
;
; Build:
;   rgbasm -o joy.o test_roms/joypad_irq_test.asm
;   rgblink -o test_roms/joypad_irq_test.gb joy.o
;   rgbfix -v -p 0 -t "JOYPADIRQ" -m 0x1B -r 2 test_roms/joypad_irq_test.gb

SECTION "JoypadIrq", ROM0[$0060]
    push af
    ld a, [JoyCount]
    inc a
    ld [JoyCount], a
    pop af
    reti

SECTION "Header", ROM0[$0100]
    nop
    jp Main
    ds $0150 - @, 0

SECTION "Vars", WRAM0[$C000]
JoyCount:  db
AccStale:  db
AccFresh:  db
LastRaw:   db
FrameLo:   db
FrameHi:   db

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
.clear_results:
    xor a
    ld [hl+], a
    dec b
    jr nz, .clear_results

    xor a
    ld [JoyCount], a
    ld [AccStale], a
    ld [AccFresh], a
    ld [LastRaw], a
    ld [FrameLo], a
    ld [FrameHi], a

    ld a, $10              ; IE: joypad only, so nothing else can wake HALT
    ld [$FFFF], a
    xor a
    ldh [$FF0F], a
    ei

    ; ---- loop 1: select the button line once, then poll without writing ----
    ; P15 (bit 5) low selects the buttons; bit 4 high leaves directions off.
    ld a, $10
    ldh [$FF00], a

    ld c, 200
.loop1:
    ldh a, [$FF00]
    ld [LastRaw], a
    cpl
    and $0F
    ld hl, AccStale
    or [hl]
    ld [hl], a
    call StoreResults
    call WaitFrame
    dec c
    jr nz, .loop1

    ld a, $5A
    ld [$A003], a

    ; ---- loop 2: rewrite the select bits before every read (control) ------
    ld c, 200
.loop2:
    ld a, $10
    ldh [$FF00], a
    ldh a, [$FF00]
    cpl
    and $0F
    ld hl, AccFresh
    or [hl]
    ld [hl], a
    call StoreResults
    call WaitFrame
    dec c
    jr nz, .loop2

    ld a, $5A
    ld [$A005], a

    ; ---- HALT until a joypad interrupt arrives ----------------------------
    xor a
    ldh [$FF0F], a
    ld a, $01
    ld [$A006], a
    halt
    ld a, $5A
    ld [$A006], a
    call StoreResults

    ld a, $5A
    ld [$A00F], a
.done:
    call StoreResults
    jr .done

StoreResults:
    ld a, [JoyCount]
    ld [$A000], a
    ld a, [AccStale]
    ld [$A001], a
    ld a, [AccFresh]
    ld [$A002], a
    ld a, [LastRaw]
    ld [$A008], a
    ld a, [FrameLo]
    ld [$A009], a
    ld a, [FrameHi]
    ld [$A00A], a
    ret

; One LCD frame, counted off LY so the phases line up with the harness's
; frame-numbered button presses.
WaitFrame:
    push af
    ld a, [FrameLo]
    inc a
    ld [FrameLo], a
    jr nz, .no_carry
    ld a, [FrameHi]
    inc a
    ld [FrameHi], a
.no_carry:
.wait_vblank:
    ldh a, [$FF44]
    cp 144
    jr nz, .wait_vblank
.wait_out:
    ldh a, [$FF44]
    cp 144
    jr z, .wait_out
    pop af
    ret
