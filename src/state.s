	.text
	global_func SaveIo
	global_func LoadIo
	global_func SaveRegs
	global_func LoadRegs
	global_func AfterLoadState

SaveRegs:
	stmfd sp!,{r3-r11,lr}
	mov r12,r0
	
	@AF, BC, DE, HL, SP, PC, Cycles
	ldr r10,=GLOBAL_PTR_BASE
	adr_ r2,cpuregs
	ldmia r2,{gb_flg-gb_pc,gb_sp}
	encodeFLG
	orr r0,r0,gb_a,lsr#16
	strh r0,[r12],#2
	mov r0,gb_bc,lsr#16
	strh r0,[r12],#2
	mov r0,gb_de,lsr#16
	strh r0,[r12],#2
	mov r0,gb_hl,lsr#16
	strh r0,[r12],#2
	mov r0,gb_sp,lsr#16
	strh r0,[r12],#2
	ldr_ r0,lastbank
	sub r0,gb_pc,r0
	strh r0,[r12],#2
	str cycles,[r12],#4
	ldmfd sp!,{r3-r11,lr}
	mov r0,#16
	bx lr
LoadRegs:
	stmfd sp!,{r3-r11,lr}
	mov r12,r0
	ldr r10,=GLOBAL_PTR_BASE
	@AF, BC, DE, HL, SP, PC, Cycles
	
	adr_ r2,cpuregs
	ldmia r2,{gb_flg-gb_pc,gb_sp}
	ldrb r0,[r12],#1
	decodeFLG
	ldrb r0,[r12],#1
	mov gb_a,r0,lsl#24
	ldrh r0,[r12],#2
	mov gb_bc,r0,lsl#16
	ldrh r0,[r12],#2
	mov gb_de,r0,lsl#16
	ldrh r0,[r12],#2
	mov gb_hl,r0,lsl#16
	ldrh r0,[r12],#2
	mov gb_sp,r0,lsl#16
	ldrh r0,[r12],#2
	mov gb_pc,r0
	ldr cycles,[r12],#4
	
	stmia r2,{gb_flg-gb_pc,gb_sp}
	ldmfd sp!,{r3-r11,lr}
	mov r0,#1
	bx lr

SaveIo:
	@r0 = address to write 256 bytes to
	stmfd sp!,{r3-r11,lr}
	
	ldr r10,=GLOBAL_PTR_BASE
	ldr_ cycles,cpuregs+0x14
	mov r3,r0
	@clear state to 00s
	mov r2,#0x80
	mov r1,#0
	bl memset32_
	
	mov r4,#0
0:
	mov r0,#0
	mov r2,r4
	bl IO_High_R
	strb r0,[r3,r4]
	add r4,r4,#1
	cmp r4,#0x100
	blt 0b
	
	@write-only sound registers
	ldrb_ r0,sound_shadow+0
	strb r0,[r3,#0x11]
	ldrb_ r0,sound_shadow+1
	strb r0,[r3,#0x13]
	ldrb_ r0,sound_shadow+2
	strb r0,[r3,#0x14]

	ldrb_ r0,sound_shadow+3
	strb r0,[r3,#0x16]
	ldrb_ r0,sound_shadow+4
	strb r0,[r3,#0x18]
	ldrb_ r0,sound_shadow+5
	strb r0,[r3,#0x19]

	ldrb_ r0,sound_shadow+6
	strb r0,[r3,#0x1B]
	ldrb_ r0,sound_shadow+7
	strb r0,[r3,#0x1D]
	ldrb_ r0,sound_shadow+8
	strb r0,[r3,#0x1E]
	
	
	ldmfd sp!,{r3-r11,lr}
	mov r0,#0x100
	bx lr
	
	
LoadIo:
	@TODO: write this
	@r0 = address to read 256 bytes from
	stmfd sp!,{r3-r11,lr}
	ldr r10,=GLOBAL_PTR_BASE
	ldr_ cycles,cpuregs+0x14
	mov r3,r0
	@joystick, serial port
	ldrb r0,[r3,#0x00]
	strb_ r0,joy0serial
	ldrb r0,[r3,#0x02]
	strb_ r0,stctrl
	@divider, timer, interrupt flags
	ldrb r0,[r3,#0x04]
	strb_ r0,dividereg+3
	
	@timer flags, interrupt flags, sound registers...
	mov r0,#0x05
	
	ldrb r0,[r3,#0x05]
	strb_ r0,timercounter+3
	ldrb r0,[r3,#0x06]
	strb_ r0,timermodulo
	ldrb r0,[r3,#0x07]
	strb_ r0,timerctrl
	ldrb r0,[r3,#0x0F]
	@Savestates are untrusted input: one written before FF0F masked its
	@writes (or a hand-edited/corrupt file) carries bits 5-7 here, and
	@restoring them raw puts phantom bits back into IF.
	and r0,r0,#0x1F
	strb_ r0,gb_if
	
	@write IO registers 10-3F directly
	mov r4,#0x10
0:
	ldrb r0,[r3,r4]
	@set Initial flag on all sound registers
@	cmp r4,#0x14
@	cmpne r4,#0x19
@	cmpne r4,#0x1E
@	cmpne r4,#0x23
@	orreq r0,r0,#0x80
	mov r2,r4
	bl_long IO_High_W
	add r4,r4,#1
	cmp r4,#0x40
	blt 0b
	
	@lcd control, lcd status, scrolling
	ldrb r0,[r3,#0x40]
	strb_ r0,lcdctrl
	mov r1,r0
	bl_long FF40W_entry
	ldrb r0,[r3,#0x41]
	ldr r1,=lcdstat
	strb r0,[r1]
	bl_long FF41_W
	ldrb r0,[r3,#0x42]
	bl_long FF42W_entry
	ldrb r0,[r3,#0x43]
	bl_long FF43W_entry
	
	@ignore FF44 (scanline number)
	
	@line compare
	ldrb r0,[r3,#0x45]
	bl_long FF45_W
	
	@ignore FF46 (sprite DMA transfer)
	
	@gb palettes, windows
	ldrb r0,[r3,#0x47]
	bl_long FF47_W_
	ldrb r0,[r3,#0x48]
	bl_long FF48_W_
	ldrb r0,[r3,#0x49]
	bl_long FF49_W_
	ldrb r0,[r3,#0x4A]
	bl_long FF4A_W_
	ldrb r0,[r3,#0x4B]
	bl_long FF4B_W_
	
	@double speed
	ldrb r0,[r3,#0x4D]
	strb_ r0,doublespeed
	bl updatespeed
	
	@vram bank
	ldrb r0,[r3,#0x4F]
	bl_long FF4F_W
	
	@HDMA
	ldrb r0,[r3,#0x51]
	bl_long FF51_W
	ldrb r0,[r3,#0x52]
	bl_long FF52_W
	ldrb r0,[r3,#0x53]
	bl_long FF53_W
	ldrb r0,[r3,#0x54]
	bl_long FF54_W
	@HDMA5.  Only an *active* HBlank transfer may be replayed: FF55 reads
	@bit 7 = 0 while one is running, with the low bits holding remaining-1,
	@so writing that value back with bit 7 set restarts an HBlank DMA of the
	@same length.  An inactive value must not be replayed at all -- a write
	@with bit 7 clear either cancels a running transfer or kicks off an
	@immediate general-purpose DMA, neither of which the saved state asked
	@for.  Without this a state saved mid-transfer resumed with the transfer
	@silently dropped.
	ldrb r0,[r3,#0x55]
	tst r0,#0x80
	bne no_hdma_replay
	orr r0,r0,#0x80
	bl_long FF55_W
no_hdma_replay:
	
	@palette index
	ldrb r0,[r3,#0x68]
	bl_long FF68_W
	ldrb r0,[r3,#0x6A]
	bl_long FF6A_W
	
	@ram bank
	ldrb r0,[r3,#0x70]
	bl_long _FF70W
	
	@HRAM and IE
	mov r4,#0x80
0:
	ldrb r0,[r3,r4]
	mov r2,r4
	bl_long IO_High_W
	add r4,r4,#1
	cmp r4,#0x100
	blt 0b

	
	ldmfd sp!,{r3-r11,lr}
	mov r0,#1
	bx lr

AfterLoadState:
	stmfd sp!,{r3-r11,lr}
	ldr r10,=GLOBAL_PTR_BASE
	@AF, BC, DE, HL, SP, PC, Cycles
	adr_ r2,cpuregs
	ldmia r2,{gb_flg-gb_pc,gb_sp}
	
	mov r0,#0
	str_ r0,lastbank
	
	@make VRAM all dirty
	mov r1,#0xFFFFFFFF
	ldr r0,=DIRTY_TILE_BITS
	mov r2,#48
	bl memset32_
	ldr r0,=dirty_map_words
	mov r2,#64
	bl memset32_

	@clear all VRAM packets (Shantae)
	@sizes must match equates.h: 24 packets * 8 bytes = 192, dirty list 196
	mov r1,#0
	ldr r0,=vram_packets_incoming
	mov r2,#192
	bl memset32_
	ldr r0,=vram_packets_registered_bank0
	mov r2,#192
	bl memset32_
	ldr r0,=vram_packets_registered_bank1
	mov r2,#192
	bl memset32_
	ldr r0,=vram_packets_dirty
	mov r2,#196
	bl memset32_
	
	@load banks
	ldr_ r0,bank0
	bl_long map0123_
	ldr_ r0,bank1
	bl_long map4567_
	@ram enable/ram bank.  On MBC3, mapperdata+4 may have had an RTC register
	@selected (bit 3) rather than a RAM bank when the state was taken.
	@RamSelect always maps SRAM, so the RTC registers read back as SRAM until
	@the game happened to reselect them.  mbc3bank restores either mapping
	@from that same byte -- it falls through to RamSelect itself when bit 3 is
	@clear -- so route through it when it is the cart's own 4000-5FFF handler.
	@(cart.s installs the mapper's four init words into writemem_tbl in pairs,
	@so the third one, the RAM-bank selector, lands at +16.)
	ldr_ r1,writemem_tbl+16
	ldr r2,=mbc3bank
	cmp r1,r2
	bne rehydrate_ram_only
	ldrb_ r0,mapperdata+4
	bl_long mbc3bank
	b ram_rehydrated
rehydrate_ram_only:
	bl_long RamSelect
ram_rehydrated:
	
	adr_ r2,cpuregs
	stmia r2,{gb_flg-gb_pc,gb_sp}
	
	bl_long copy_gbc_palette
	bl_long transfer_palette
	bl_long display_sprites
	@these destroy r10
	bl_long render_dirty_tiles
	bl_long render_dirty_bg
	
	ldmfd sp!,{r3-r11,lr}
	bx lr
