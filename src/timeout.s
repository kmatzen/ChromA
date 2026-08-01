	.section .vram1, "ax", %progbits
@----------------------------------------------------------------------------
@cycles ran out
@----------------------------------------------------------------------------
 .global line0
line0:
	adr_ r2,cpuregs
	stmia r2,{gb_flg-gb_pc,gb_sp}	@save gbz80 state
	
	ldrb_ r0,autoborderstate
	cmp r0,#1
	bne 0f
	ldr_ r0,frame
	ldr_ r1,auto_border_reboot_frame
	cmp r0,r1
	blt 0f
	bl_long loadcart_after_sgb_border
0:
	


@waitformulti
	ldr r1,=REG_P1		@refresh input every frame
	ldrh r0,[r1]
		eor r0,r0,#0xff
		eor r0,r0,#0x300	@r0=button state (raw)
	ldr_ r1,AGBjoypad
	eor r1,r1,r0
	and r1,r1,r0		@r1=button state (0->1)
	str_ r0,AGBjoypad

	ldrb_ r2,dontstop_
	cmp r2,#0
	ldmeqfd sp!,{gb_flg-gb_pc,globalptr,r11,lr}	@exit here if doing single frame:
	bxeq lr							@return to rommenu()

	@----anything from here til line0x won't get executed while rom menu is active---

@	mov r2,#REG_BASE
@	mov r3,#0x0110				;was 0x0310
@	strh r3,[r2,#REG_BLDMOD]	;stop darkened screen,OBJ blend to BG0/1
@	mov r3,#0x1000				;BG0/1=16, OBJ=0
@	strh r3,[r2,#REG_BLDALPHA]	;Alpha values

	adr lr,line0x		@return here after doing L/R + SEL/START

	tst r1,#0x300		@if L or R was pressed
	tstne r0,#0x100
	tstne r0,#0x200		@and both L+R are held..
	ldrne r1,=ui
	bxne r1			@do menu


	ands r3,r0,#0x300		@if either L or R is pressed (not both)
	eornes r3,r3,#0x300
	bicne r0,r0,#0x0c		@	hide sel,start from NES
	str_ r0,XGBjoypad
	beq line0x		@skip ahead if neither or both are pressed

@	tst r0,#0x200
@	tstne r1,#4		;L+SEL for BG adjust
@	ldrne r2,adjustblend
@	addne r2,r2,#1
@	strne r2,adjustblend

	tst r0,#0x200		@L?
	tstne r1,#8		@START?
	ldrb_ r2,novblankwait_	@0=Normal, 1=No wait, 2=Slomo
	addne r2,r2,#1
	cmp r2,#3
	moveq r2,#0
	strb_ r2,novblankwait_

	tst r0,#0x100		@R?
	tstne r1,#8		@START:
	ldrne r1,=quickload
	bxne r1

	tst r0,#0x100		@R?
	tstne r1,#4		@SELECT:
	ldrne r1,=quicksave
	bxne r1
line0x:
	bl_long refreshNESjoypads	@Z=1 if communication ok

#if JOYSTICK_READ_HACKS
	@joystick speed hacks
	mov r1,#-64
	strb_ r1,joy_read_count
#endif

@	bne waitformulti	;waiting on other GBA..

	ldr_ r0,AGBjoypad
	ldr_ r2,fiveminutes_		@sleep after 5/10/30 minutes of inactivity
	cmp r0,#0				@(left out of the loop so waiting on multi-link
	ldrne_ r2,sleeptime_		@doesn't accelerate time)
	subs r2,r2,#1
	str_ r2,fiveminutes_
	bleq_long suspend

	mov r1,#0
	strb_ r1,scanline		@reset scanline count
@	bl newframe		@display update

	@ Initialize mid-frame palette tracking
	mov r0,#0
	strb_ r0,pal_dirty
	ldr r1,=pal_split_count
	strb r0,[r1]
	ldr r1,=pal_split_count_screen
	strb r0,[r1]
	ldr r1,=pal_last_split_line
	mov r0,#0xFF
	strb r0,[r1]			@ no split recorded yet

	@ Scanlines outside the range this game has ever driven still hold the
	@ buffer's power-on contents, and DMA3 replays those as black (issue #36).
	@ Extend the nearest real palette into them at both ends.  Lines inside
	@ the range are deliberately left alone even when this frame skipped them:
	@ games like Hercules build their per-line palettes up over several
	@ frames, and overwriting that with a frame-start snapshot corrupts the
	@ lower half of the screen.  Only worth doing when the frame actually
	@ drove the buffer -- the display replays it above the same threshold.
	ldr r0,=pal_frame_writes
	ldr r1,[r0]
	mov r2,#0
	str r2,[r0]
	cmp r1,#4
	ble 1f
	ldr r0,=pal_min_line_p1
	ldrb r2,[r0]
	subs r2,r2,#1			@ un-bias; negative means never written
	bmi 2f
	sub r1,r2,#1			@ last line below the range
	mov r0,#0
	bl_long pal_forward_fill
2:	ldr r0,=pal_max_line
	ldrb r2,[r0]
	add r0,r2,#1			@ first line above the range
	mov r1,#143
	bl_long pal_forward_fill
1:	ldr r0,=pal_fill_line
	mov r1,#0
	strb r1,[r0]			@ new frame: forward-fill restarts at line 0

	@ Snapshot full palette (BG+OBJ, 128 bytes) as pal_before baseline
	stmfd sp!,{r2-r9}
	ldr r0,=gbc_palette
	ldr r1,=pal_before
	ldmia r0!,{r2-r9}
	stmia r1!,{r2-r9}
	ldmia r0!,{r2-r9}
	stmia r1!,{r2-r9}
	ldmia r0!,{r2-r9}
	stmia r1!,{r2-r9}
	ldmia r0!,{r2-r9}
	stmia r1!,{r2-r9}		@ 128 bytes copied
	ldmfd sp!,{r2-r9}

	@now do double speed vblank stuff:
	ldr_ r0,doubletimer_
	tst r0,#0x01
	blne_long updatespeed

	adr_ r0,cpuregs
	ldmia r0,{gb_flg-gb_pc,gb_sp}	@restore GB-Z80 state

@	ldrb r1,lcdctrl		;not liked by SML.
@	tst r1,#0x80
	ldr r1,=lcdstat
	ldrb r0,[r1]		@
	and r2,r0,#0xFC		@reset lcd mode flags (vblank/hblank/oam/lcd),
				@keeping bit 7 -- it is wired high on hardware, and
				@masking it out here would clear it once a frame
	cmp r0,r2
	strneb r2,[r1]		@
	strneb r2,[r1,#-12] @FIXME

	ldr_ r0,cyclesperscanline
	add cycles,cycles,r0

	ldr r0,=line1_to_71
	str_ r0,nexttimeout

	adrl_ r1,FF41_R_function
	ldr r0,[r1]
@	ldr r0,=FF41_R
	ldr r1,=FF41_R_ptr
	str r0,[r1]

	ldr_ pc,scanlinehook

 .section .iwram.3, "ax", %progbits

line1_to_71: @------------------------
	ldr_ r0,cyclesperscanline
	add cycles,cycles,r0

	ldrb_ r1,scanline
	add r1,r1,#1
	strb_ r1,scanline

	cmp r1,#75		@was 71
	ldrmi_ pc,scanlinehook
@--------------------------------------------- between 71 and 72

	ldrb_ r0,lcdctrl
	strb_ r0,lcdctrl0midframe		@Chase HQ likes this

	adr addy,line72_to_143
	str_ addy,nexttimeout
	ldr_ pc,scanlinehook
line72_to_143: @------------------------
	ldr_ r0,cyclesperscanline
	add cycles,cycles,r0

	ldrb_ r1,scanline
	add r1,r1,#1
	strb_ r1,scanline
	cmp r1,#143
	ldrmi_ pc,scanlinehook

	adr addy,line144
	str_ addy,nexttimeout
	ldr_ pc,scanlinehook

	.pushsection .iwram.3
line144: @------------------------
#if SPEEDHACKS_NEW
	@quick hack finder code
	
	@quick hack finder used?
	ldrb_ r0,quickhackused
	movs r0,r0
	bne 0f
	@increment counter
	ldrb_ r0,quickhackcounter
	adds r0,r0,#1
	strb_ r0,quickhackcounter
	cmp r0,#8
	@under 8, don't search
	blt 1f
	stmfd sp!,{r3}

	adr_ r0,cpuregs
	stmia r0,{gb_flg-gb_pc,gb_sp}
	
	mov r0,gb_pc
	ldr_ r1,lastbank
	blx_long quickhackfinder
	ldmfd sp!,{r3}
0:	
	@if quick hack finder was called, or hack was used, reset counter to 0
	mov r0,#0
	strb_ r0,quickhackcounter
	strb_ r0,quickhackused
1:
#endif	
	ldrb_ r0,doubletimer_
	tst r0,#1
	blne_long updatespeed
	bl newframe_vblank
@	stmfd sp!,{r0-addy,lr}

@ [ BUILD <> "DEBUG"
@	ldrb r2,novblankwait
@	teq r2,#1
@	beq l03
@l01
@	mov r0,#0				;don't wait if not necessary
@	mov r1,#1				;VBL wait
@	swi 0x040000			; Turn of CPU until IRQ if not too late allready.
@	teq r2,#2				;Check for slomo
@	moveq r2,#0
@	beq l01
@l03
@ ]
@	ldmfd sp!,{r0-addy,lr}


	ldr_ r0,fpsvalue
	add r0,r0,#1
	str_ r0,fpsvalue



@ [ DEBUG
@	mov r1,#REG_BASE			;darken screen during GB vblank
@	mov r0,#0x00f1
@	strh r0,[r1,#REG_BLDMOD]
@	ldrh r0,[r1,#REG_VCOUNT]
@	mov r1,#19
@	bl debug_
@ ]
	tst cycles,#CYC_LCD_ENABLED
	@ldrb_ r0,lcdctrl		@LCD turned on?
	@tst r0,#0x80
	beq novbirq

	adrl_ r1,FF41_R_vblank_function
	ldr r0,[r1]
@	ldr r0,=FF41_R_vblank
	ldr r1,=FF41_R_ptr
	str r0,[r1]

	adrl r1,lcdstat
	ldrb r0,[r1]		@vbl flag
	and r0,r0,#0xFC		@keep bit 7 (wired high); clear only the mode field
	orr r2,r0,#0x01		@set mode 1 (VBlank)
	strb r2,[r1]		@vbl flag
	strb r2,[r1,#-12] @FIXME

	ldrb_ r2,gb_if
	orr r2,r2,#0x01		@1=VBL
	@ Fire STAT interrupt if mode 1 (VBlank) STAT IE is enabled (bit 4).
	@ Also apply IRQ blocking: skip if LYC is already holding line high.
	ldrb r1,[r1]		@re-read lcdstat (now has mode 1 set)
	@Entering line 144 asserts the mode-2 (OAM) STAT condition as well as the
	@mode-1 one, so a game that enables only bit 5 still gets a STAT IRQ at
	@VBlank start.  Checking bit 4 alone missed that.
	tst r1,#0x30		@mode 1 (bit 4) or mode 2 (bit 5) STAT IE enabled?
	beq .noVblStat
	@ Check IRQ blocking: if STAT line was already high, no rising edge
	@ Block if mode 0 (HBlank) IE held line high from preceding scanline
	tst r1,#0x08		@mode 0 STAT IE enabled?
	bne .noVblStat		@blocked: HBlank held line high
	@ Block if LYC=LY coincidence holds line high
	tst r1,#0x40		@LYC IE enabled?
	tstne r1,#0x04		@AND coincidence flag set?
	bne .noVblStat		@blocked
	orr r2,r2,#0x02		@2=LCD STAT
.noVblStat:
	strb_ r2,gb_if
novbirq:
	mov r0,#24*CYCLE
	add cycles,cycles,r0

	mov r1,#144
	strb_ r1,scanline

	adr addy,VBL_Hook
	str_ addy,nexttimeout
	b _GO
VBL_Hook:
	ldr_ r0,cyclesperscanline
	sub r0,r0,#24*CYCLE
	add cycles,cycles,r0

	adr addy,line145_to_end
	str_ addy,nexttimeout
	ldr_ pc,scanlinehook
line145_to_end: @------------------------
	ldr_ r0,cyclesperscanline
	add cycles,cycles,r0

	ldrb_ r1,scanline
	add r1,r1,#1
	strb_ r1,scanline
	cmp r1,#153				@last scanline
	ldrmi_ pc,scanlinehook
	
#if !EARLY_LINE_0
	ldr addy,=line0
	str_ addy,nexttimeout
	ldr_ pc,scanlinehook
#else
	sub cycles,cycles,r0
toLineZero_modify1:
	adds cycles,cycles,#16*CYCLE  @8 for non-double speed mode
	
	@bmi toLineZero
	adr addy,toLineZero
	str_ addy,nexttimeout
	ldr_ pc,scanlinehook
	
toLineZero:
	@line 0, but still in Vblank state
	mov r0,#0
	strb_ r0,scanline
@	bl_long newframe	@display update
	
	ldr_ r0,cyclesperscanline
toLineZero_modify2:
	sub r0,r0,#16*CYCLE  @8 for non-double speed mode
	add cycles,cycles,r0
	ldr addy,=line0
	str_ addy,nexttimeout
	ldr_ r0,frame
	add r0,r0,#1
	str_ r0,frame
	ldr_ pc,scanlinehook
#endif

immediate_check_irq:
	ldrb_ r0,gb_ie		@0xFFFF=Interrupt Enable.
	ldrb_ r1,gb_if
	and r1,r1,r0
	ands r1,r1,#0x1f	@only 5 interrupts exist; see checkIRQ
	tstne cycles,#CYC_IE
	bxeq lr
	b_long immediate_check_irq_2
@	ldrb_ r0,gb_ime
@	movs r0,r0
@	bxeq lr
	@different ugly hack which doesn't mess up timing,
	@this is necessary because goomba must finish executing its instruction before checking for GB interrupts
	.pushsection .text
immediate_check_irq_2:
	ldr_ r0,nexttimeout
	@don't override checkMasterIRQ_minus12
	ldr r1,=checkMasterIRQ_minus12
	cmp r0,r1
	bxeq lr
	sub cycles,cycles,#1024*CYCLE  @this just makes it go somewhere else instead of the next instruction

	@Chain rather than share: save into our OWN slot.  nexttimeout may be
	@ei_finish (an EI deferral is live), and that deferral's real scanline
	@state is parked in nexttimeout_alt -- writing there would destroy it,
	@leaving nexttimeout self-referential and the scanline machine dead.
	@Saving here means no_more_irq_hack hands control back to ei_finish,
	@which then restores the real state.  Preserves the original dispatch
	@timing, which games depend on.
	@Kept outside the globalptr block: adding a word there shifts xgb_ram
	@from 0x25c0 to 0x25c4, which is not an encodable ARM immediate.
	ldr r1,=nexttimeout_alt2
	str r0,[r1]
	ldr r1,=no_more_irq_hack
	str_ r1,nexttimeout
	bx lr

no_more_irq_hack:
	add cycles,cycles,#1024*CYCLE
	ldr r1,=nexttimeout_alt2
	ldr r0,[r1]
	str_ r0,nexttimeout
	b_long checkIRQ
	.popsection


@----------------------------------------------------------
default_scanlinehook:
checkScanlineIRQ:
default_scanlinehook_nohblank:
    ldrb_ r1,dma_blocks_total
    cmp r1,#0
    beq _checkScanlineIRQ  @ If not mid-hdma, continue normal execution.
    @ HBlank DMA only transfers at HBlanks of visible lines with the LCD on.
    @ The hook runs after scanline is incremented, so scanline==N here means
    @ line N-1 just ended: its HBlank is visible for N-1 in [0,143], i.e.
    @ scanline in [1,144].  VBlank lines and LCD-off get no blocks.
    tst cycles,#CYC_LCD_ENABLED
    beq _checkScanlineIRQ
    ldrb_ r1,scanline
    sub r1,r1,#1
    cmp r1,#144
    bhs _checkScanlineIRQ
    @ Else, fall through to tick_hdma
tick_hdma:
    @ Transfer one 16-byte block per HBlank (matching real GBC behavior)
    stmfd sp!,{r0-r12,lr}
    mov r0,#16
    blx_long DoDma
    ldmfd sp!,{r0-r12,lr}

    @ Steal CPU cycles for HDMA block (8 machine cycles, 16 in double speed)
    ldr_ r1,cyclesperscanline
    cmp r1,#DOUBLE_SPEED
    mov r1,#8 << CYC_SHIFT
    moveq r1,#16 << CYC_SHIFT
    sub cycles,cycles,r1

    @ Decrement _dma_blocks_remaining
    ldr r1,=_dma_blocks_remaining
    ldrb r2,[r1]
    sub r2,r2,#1
    strb r2,[r1]

    @ If _dma_blocks_remaining == 0, HDMA is complete
    cmp r2,#0
    bne _checkScanlineIRQ
    ldr r1,=_dma_blocks_total
    strb r2,[r1]
    

    @ Finally, fall through and continue execution
_checkScanlineIRQ:
	tst cycles,#CYC_LCD_ENABLED
	beq noScanlineIRQ

	@do LC==LYC test
	ldrb_ r1,scanline
	ldrb_ r0,lcdyc
	cmp r0,r1
	adrl r1,lcdstat
	ldrb r0,[r1]
	@LY==LYC bit must change from 0 to 1 to trigger an LY==LYC interrupt
	orreq r2,r0,#4
	bicne r2,r0,#4
	cmp r2,r0
	@ne if LYC bit has changed
	strneb r2,[r1]
	strneb r2,[r1,#-12] @FIXME
	@has it turned on, and interrupts are enabled?
	@
	@Deliberately NOT blocked when mode-0 IE held the STAT line high through
	@the preceding HBlank, which issue #52 item 8 asks for.  A pure
	@OR-of-conditions rising-edge model says the LYC coincidence opening this
	@line cannot be an edge, so the line should yield nothing -- but measured
	@against mGBA's DMG core (test_roms/test_stat_ly.py), mode-0 IE plus LYC IE
	@gives exactly 144 STAT IRQs per frame, the same as mode-0 IE alone, and
	@adding the block drops it to 143.  The likely reason is the documented
	@one-cycle window at the start of a line where the LY==LYC comparison reads
	@false: the line dips low for that cycle and the coincidence then is a real
	@edge.  Left alone rather than changed away from the reference.
	tstne r2,#4
	tstne r2,#0x40
	bne ScanlineIRQ_fromLYC

	@in vblank?  no Hblank or Mode 2 IRQ
	tst r2,#0x01
	bne noScanlineIRQ
	@Hblank IRQ or Mode 2 IRQ enabled?
	tst r2,#0x28
	beq noScanlineIRQ

	@ STAT IRQ blocking: if LYC=LY is active on this scanline (coincidence
	@ flag set AND LYC IE enabled), the STAT line is already high from LYC.
	@ Mode 0/2 transitions cannot cause a new rising edge, so block.
	tst r2,#0x40			@LYC interrupt enabled?
	tstne r2,#0x04			@AND coincidence flag set?
	bne noScanlineIRQ		@blocked: LYC holds line high

ScanlineIRQ_fromLYC:
	ldrb_ r0,gb_if
	orr r0,r0,#0x02		@2=LCD STAT
	strb_ r0,gb_if
noScanlineIRQ:
@------------------
	@ Mid-frame palette tracking disabled — DMA3 buffer filled from FF69_W tail
	@ Per-scanline hook overhead (~70 cycles) disrupts GBC VBlank handler timing
@------------------

	.pushsection .text
pal_fill_dma_scanline:
	@ r0 = scanline, r1 = split index (both preserved)
	stmfd sp!,{r2-r6}
	ldr r2,=pal_dma_buffer
	add r2,r2,r0,lsl#8		@ buffer[scanline * 256]
	ldr r3,=gbc_palette
	mov r4,#8
1:	ldr r5,[r3],#4
	ldr r6,[r3],#4
	str r5,[r2],#4
	str r6,[r2],#4
	add r2,r2,#24
	subs r4,r4,#1
	bne 1b
	ldmfd sp!,{r2-r6}
	b_long checkTimerIRQ

	.popsection

@------------------
checkTimerIRQ:
	ldr_ r2,timercyclesperscanline
	
	ldr_ r0,dividereg
	add r0,r0,r2,lsl#12		@256th cycles.
	str_ r0,dividereg

	ldrb_ r1,timerctrl
	tst r1,#0x4
	beq noTimer
	ands r1,r1,#3
	moveq r1,#4
	mov r0,#18
	sub r1,r0,r1,lsl#1
	ldr_ r0,timercounter
	adds r0,r0,r2,lsl r1
	bcc noTimerIRQ
	ldrb_ r1,gb_if
	orr r1,r1,#0x04		@4=Timer
	strb_ r1,gb_if
	@ TIMA overflowed at least once during this scanline.  r0 now holds the
	@ excess past the wrap point; fold it back through the reload period
	@ rather than dropping it (#44 item 1).
	@
	@ This used to store a flat TMA<<24, discarding the sub-period fraction
	@ and every overflow after the first.  Both matter: at TAC=01 the period
	@ is 16 cycles, so one scanline is ~28 TIMA periods, and with a high TMA
	@ the reload period is short enough that several overflows land in a
	@ single scanline.  Restarting from a flat TMA<<24 each time made the
	@ timer lose the leftover phase every scanline and drift steadily.
	@
	@ _FF05R already projects reads through this same fold, so before this
	@ the committed state and the value a game read back disagreed.
	@
	@ The IRQ is still raised once per scanline; delivering one interrupt per
	@ overflow needs sub-scanline dispatch, which is the architecture limit
	@ #44 items 3-4 describe.  The counter phase is now right regardless.
	@
	@ Bounded: the largest increment is DOUBLE_SPEED<<16, and the smallest
	@ reload period is 1<<24 (TMA=255), so the loop runs at most 57 times and
	@ only on a scanline that actually overflowed.
	ldrb_ r1,timermodulo
	rsb r2,r1,#256
	movs r2,r2,lsl#24	@(256-TMA)<<24; 0 means a full 2^32 period
	beq 3f
0:	cmp r0,r2
	subcs r0,r0,r2
	bcs 0b
3:	add r0,r0,r1,lsl#24
noTimerIRQ:
	str_ r0,timercounter
noTimer:
	ldrb_ r1,stctrl
	and r1,r1,#0x81
	cmp r1,#0x81		@Are going to transfer on internal clock?

	ldreqb_ r1,gb_if		@IRQ flags
	orreq r1,r1,#8		@8=Serial
	streqb_ r1,gb_if

	ldreqb_ r0,stctrl
	andeq r0,r0,#0x7F		@Clear Serial Transfer flag.
	streqb_ r0,stctrl
checkMasterIRQDelayed:
	tst cycles,#CYC_IE
	beq _GO
checkIRQDelayed:
	ldrb_ r0,gb_ie
	ldrb_ r1,gb_if
	and r0,r0,r1
	ands r0,r0,#0x1f	@only 5 interrupts exist; see checkIRQ
	beq _GO
	
	@Halted-ness is a state, not a byte.  Inferring it from [gb_pc]==0x76
	@meant an interrupt dispatched at the boundary immediately *before* a
	@not-yet-executed HALT looked identical to waking from one: the handler
	@stepped gb_pc over the HALT and charged the wake cycle, so a
	@halt/nop/jr wait loop woke an interrupt period early (#41 item 2).
	tst cycles,#CYC_HALT
	bne irqGBZ80_ifhalt

	ldr_ r12,cyclesperscanline
	sub r12,r12,#8*CYCLE
	subs r12,cycles,r12
	bmi irqGBZ80_nothalt
	mov cycles,r12

	ldrb r0,lcdstat
	orr r0,r0,#2
	strb r0,lcdstat

	ldr_ r0,nexttimeout
	str_ r0,nexttimeout_alt
	adr r0,checkMasterIRQ_minus12
	str_ r0,nexttimeout
	b _GO

checkMasterIRQ_minus12:
	ldrb r0,lcdstat
	bic r0,r0,#2
	strb r0,lcdstat

	ldr_ r0,cyclesperscanline
	add r0,#8*CYCLE
	add cycles,cycles,r0
	ldr_ r0,nexttimeout_alt
	str_ r0,nexttimeout
	@proceed to checkMasterIRQ
	
@----------------------------------------------------------
checkMasterIRQ:
@----------------------------------------------------------
	tst cycles,#CYC_IE
	@ldrb_ r2,gb_ime
	@tst r2,#1
	beq _GO
@----------------------------------------------------------
checkIRQ:
@----------------------------------------------------------
	ldrb_ r0,gb_ie
	ldrb_ r1,gb_if
	and r0,r0,r1
	@Only 5 interrupts exist.  IE is a full 8-bit R/W register on hardware,
	@so a game may legitimately leave bits 5-7 set in it; without this mask
	@those phantom bits match anything stale in IF, no tst below claims the
	@IRQ, and the priority chain falls out of _irqGBZ80_ into its unknown-
	@IRQ tail, dispatching a spurious interrupt to vector 0x40.
	ands r0,r0,#0x1f
	beq _GO
@----------------------------------------------------------
irqGBZ80:
@----------------------------------------------------------
	tst cycles,#CYC_HALT
irqGBZ80_ifhalt:
@	cmpne r2,#0x10                  ;or STOP
	addne gb_pc,gb_pc,#1	@get out of HALT
	subne cycles,cycles,#4*CYCLE	@waking from HALT costs 24, not 20
	bicne cycles,cycles,#CYC_HALT
irqGBZ80_nothalt:
	bic cycles,cycles,#CYC_IE
@	mov r2,#0				@disable IRQ
@	strb_ r2,gb_ime

	tst r0,#0x01			@VBlank
	movne r2,#0x40
	bicne r1,r1,#0x01		@clear the IRQ flag
	bne doIRQ

	tst r0,#0x02			@LCD Stat
	movne r2,#0x48
	bicne r1,r1,#0x02		@clear the  IRQ flag
	bne doIRQ

	tst r0,#0x04			@Timer
	movne r2,#0x50
	bicne r1,r1,#0x04		@clear the  IRQ flag
@	bne doIRQ
	beq_long _irqGBZ80_
	@10 instructions moved to .text section
@	tst r0,#0x08			@Serial
@	movne r2,#0x58
@	bicne r1,r1,#0x08		@clear the  IRQ flag
@	bne doIRQ
@
@	tst r0,#0x10			@Joypad
@	movne r2,#0x60
@	bicne r1,r1,#0x10		@clear the  IRQ flag
@	bne doIRQ
@
@	and r1,r1,#0x1f			@unknown IRQ?
@	mov r2,#0x40

doIRQ:
	strb_ r1,gb_if
	ldr_ r0,lastbank
	sub r0,gb_pc,r0
	mov gb_pc,r2			@get IRQ vector

	push16_novram					@save PC
	encodePC_afterpush16

	@Interrupt dispatch is 20 T-cycles from the run state.  24 is the cost
	@when the CPU was in HALT: waking from it adds one extra machine cycle
	@on top.  A flat 24 made every interrupt in a running program 4 cycles
	@too expensive (#41 item 3); irqGBZ80_ifhalt adds the 4 back on the
	@path that actually earns it.
	fetch 20

.pushsection .text
_irqGBZ80_:
	tst r0,#0x08			@Serial
	movne r2,#0x58
	bicne r1,r1,#0x08		@clear the  IRQ flag
	bne_long doIRQ

	tst r0,#0x10			@Joypad
	movne r2,#0x60
	bicne r1,r1,#0x10		@clear the  IRQ flag
	bne_long doIRQ

	and r1,r1,#0x1f			@unknown IRQ?
	mov r2,#0x40
	b_long doIRQ
.popsection


 .section .iwram.end.105, "ax", %progbits
@----------------------------------------------------------------------------
fiveminutes: .word 5*60*60 @fiveminutes_
sleeptime: .word 5*60*60 @sleeptime_
dontstop: .byte 0 @dontstop_
g_hackflags: .byte 0 @hackflags
g_hackflags2: .byte 0 @hackflags2
 .byte 0
@----------------------------------------------------------------------------
