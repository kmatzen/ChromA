 .section .iwram.2, "ax", %progbits

@	#include "equates.h"
@	#include "memory.h"
@	#include "lcd.h"
@	#include "cart.h"
@	#include "io.h"

	global_func mbc0init
	global_func mbc1init
	global_func mbc2init
	global_func mbc3init
	global_func mbc4init
	global_func mbc5init
	global_func mbc6init
	global_func mbc7init
	global_func mmm01init
	global_func huc1init
	global_func huc3init
	global_func RamSelect
@----------------------------------------------------------------------------
RamSelect:
@----------------------------------------------------------------------------
	ldrb_ r0,mapperdata+2	@ram enable
@----------------------------------------------------------------------------
RamEnable:
@----------------------------------------------------------------------------
	strb_ r0,mapperdata+2
	and r0,r0,#0x0F
	cmp r0,#0x0A
	adrnel r1,empty_W
	ldreq_ r1,sramwptr
	str_ r1,writemem_tbl+40
	str_ r1,writemem_tbl+44
	adrnel r1,empty_R
	adreql r1,mem_RA0
	str_ r1,readmem_tbl_-40
	str_ r1,readmem_tbl_-44
	ldrb_ r0,mapperdata+4		@rambank
	b mapAB_

@----------------------------------------------------------------------------
MBC2RamEnable:
@----------------------------------------------------------------------------
	@As RamEnable, but installs the MBC2-specific accessors: its RAM is 512
	@half-bytes, so A000-BFFF echoes every 512 bytes and reads return the
	@upper nibble as 1.  Lives here, next to RamEnable, because the adrl
	@below has to reach the handlers from the same section.
	strb_ r0,mapperdata+2
	and r0,r0,#0x0F
	cmp r0,#0x0A
	adrnel r1,empty_W
	adreql r1,mbc2_W
	str_ r1,writemem_tbl+40
	str_ r1,writemem_tbl+44
	adrnel r1,empty_R
	adreql r1,mbc2_R
	str_ r1,readmem_tbl_-40
	str_ r1,readmem_tbl_-44
	ldrb_ r0,mapperdata+4		@rambank
	b mapAB_

	.pushsection .text
@----------------------------------------------------------------------------
mbc0init:
@----------------------------------------------------------------------------
	.word void,void,void,void
	mov pc,lr

@mapperdata for mbc1:
@0	low 5 bits of rom bank number (00-1F), 00 becomes 01.
@1	high 2 bits of rom bank number
@2	sram enabled (0A if enabled)
@3	rom/ram bankswitch mode (0 for rom, 1 for ram)
@4	sram bank
@5	2 bits for either rom bank or sram bank

@----------------------------------------------------------------------------
mbc1init:
@----------------------------------------------------------------------------
	.word RamEnable,MBC1map0,MBC1map1,MBC1mode

	ldr r0,=empty_W					@ Disable RAM = $00
	str_ r0,writemem_tbl+40
	str_ r0,writemem_tbl+44

	@MBC1 multicart (#50): BANK1 is 4 bits wide, so BANK2 shifts by 4 and
	@selects one of four 256KB games instead of one of four 512KB halves.
	@Swap in dedicated handlers rather than branching inside the normal
	@ones, so the plain-MBC1 path -- which every other MBC1 game takes --
	@stays exactly as it was.  cart.s set this flag from the ROM contents.
	@MBC1map1 falls through into MBC1mode, so the 4000-5FFF slot has to be
	@replaced too or a BANK2 write would land back in the 5-bit code.
	ldrb_ r0,mapperdata+6
	cmp r0,#0
	moveq pc,lr
	ldr r0,=MBC1Mmap0
	str_ r0,writemem_tbl+8
	str_ r0,writemem_tbl+12
	ldr r0,=MBC1Mmap1
	str_ r0,writemem_tbl+16
	str_ r0,writemem_tbl+20
	ldr r0,=MBC1Mmode
	str_ r0,writemem_tbl+24
	str_ r0,writemem_tbl+28
	mov pc,lr

@----------------------------------------------------------------------------
MBC1Mmap0:	@multicart BANK1 write, 2000-3FFF -- 4 bits, not 5
@----------------------------------------------------------------------------
	ands r0,r0,#0x0f
	moveq r0,#1
	strb_ r0,mapperdata
	ldrb_ r1,mapperdata+1
	orr r0,r0,r1,lsl#4
	tst r0,#0x0f
	addeq r0,r0,#1
	b map4567_
@----------------------------------------------------------------------------
MBC1Mmap1:	@multicart BANK2 write, 4000-5FFF
@----------------------------------------------------------------------------
	and r0,r0,#0x03
	strb_ r0,mapperdata+5
	ldrb_ r0,mapperdata+3
@----------------------------------------------------------------------------
MBC1Mmode:	@multicart mode write, 6000-7FFF
@----------------------------------------------------------------------------
	strb_ r0,mapperdata+3
	tst r0,#1			@eq = mode 0, ne = mode 1
	ldrb_ r0,mapperdata+5		@r0 = BANK2
	mov r1,#0
	strb_ r0,mapperdata+1
	streqb_ r1,mapperdata+4
	strneb_ r0,mapperdata+4
	moveq r0,#0
	movne r0,r0,lsl#4
	str lr,[sp,#-4]!
	bl map0123_
	ldrb_ r0,mapperdata
	ldrb_ r1,mapperdata+1
	orr r0,r0,r1,lsl#4
	tst r0,#0x0f
	addeq r0,r0,#1
	bl map4567_
	ldr lr,[sp],#4
	b RamSelect

	.popsection
@----------------------------------------------------------------------------
MBC1map0:
@----------------------------------------------------------------------------
	ands r0,r0,#0x1f
    moveq r0,#1
	strb_ r0,mapperdata
	ldrb_ r1,mapperdata+1
	orr r0,r0,r1,lsl#5
    tst r0,#0x1f  @ r0 = rom bank.  If lower 5 bits = 0s
    addeq r0,r0,#1  @ Add 1
	b map4567_
	
	.pushsection .text
@----------------------------------------------------------------------------
MBC1map1:
@----------------------------------------------------------------------------
	and r0,r0,#0x03
	strb_ r0,mapperdata+5		@Ram/Rom bank select.
	ldrb_ r0,mapperdata+3
@----------------------------------------------------------------------------
MBC1mode:
@----------------------------------------------------------------------------
	strb_ r0,mapperdata+3
	tst r0,#1			@eq = mode 0, ne = mode 1
	ldrb_ r0,mapperdata+5		@r0 = BANK2
	mov r1,#0
	@BANK2 drives the 4000-7FFF bank in BOTH modes.  This used to store 0
	@in mode 1, which stripped bits 5-6 off every bank select on a cart
	@bigger than 512KB and fetched from the wrong half.
	strb_ r0,mapperdata+1
	streqb_ r1,mapperdata+4		@mode 0: RAM bank is always 0
	strneb_ r0,mapperdata+4		@mode 1: BANK2 selects the RAM bank

	@In mode 1 the low half follows BANK2 too, at bank BANK2<<5; in mode 0
	@it is pinned to bank 0.  The mapper never called map0123_ at all, so
	@0000-3FFF stayed on bank 0 forever.  Work out the bank before the
	@first bl, which clobbers the mode flags.
	moveq r0,#0
	movne r0,r0,lsl#5
	str lr,[sp,#-4]!
	bl map0123_

	ldrb_ r0,mapperdata
	ldrb_ r1,mapperdata+1
	orr r0,r0,r1,lsl#5
    tst r0,#0x1f  @ r0 = rom bank.  If lower 5 bits = 0s
    addeq r0,r0,#1  @ Add 1
	bl map4567_
	ldr lr,[sp],#4
	b RamSelect

@----------------------------------------------------------------------------
mbc2init:
@----------------------------------------------------------------------------
	@Both halves of 0000-3FFF go to the same handler: on MBC2 it is address
	@bit 8 alone that picks the register, not which 8KB block was written.
	.word MBC2reg,MBC2reg,void,void

	ldr r0,=empty_W					@ Disable RAM = $00
	str_ r0,writemem_tbl+40
	str_ r0,writemem_tbl+44

	mov pc,lr
	.popsection
@----------------------------------------------------------------------------
MBC2reg:	@MBC2 register write, anywhere in 0000-3FFF
@----------------------------------------------------------------------------
	@A8 set = ROM bank select, A8 clear = RAM enable -- across the whole
	@range.  These used to be wired one per 8KB block, so a bank select at
	@0100 and a RAM enable at 2000 were both silently dropped.
	tst addy,#0x0100
	beq MBC2RamEnable
@----------------------------------------------------------------------------
MBC2map:
@----------------------------------------------------------------------------
	ands r0,r0,#0xf
	moveq r0,#1
	b map4567_
	.pushsection .text

@----------------------------------------------------------------------------
mbc3init:
@----------------------------------------------------------------------------
	.word RamEnable,MBC3map,mbc3bank,mbc3latchtime

	ldr r0,=empty_W					@ Disable RAM = $00
	str_ r0,writemem_tbl+40
	str_ r0,writemem_tbl+44

	mov pc,lr
@----------------------------------------------------------------------------
mbc3latchtime:
@----------------------------------------------------------------------------
	ldrb_ r1,mapperdata+3
	strb_ r0,mapperdata+3
	eor r1,r1,r0
	and r1,r1,r0
	cmp r1,#1
	movne pc,lr
	stmfd sp!,{r3,lr}
	bl_long gettime
	ldmfd sp!,{r3,lr}
	mov pc,lr
@----------------------------------------------------------------------------
mbc3bank:
@----------------------------------------------------------------------------
	strb_ r0,mapperdata+4
	tst r0,#8
	beq RamSelect
	@The RTC registers are writable -- clock-set flows in games write them.
	@This used to install empty_W, so every write was dropped and the value
	@snapped straight back.
	ldr r1,=mbc3rtc_W
	str_ r1,writemem_tbl+40
	str_ r1,writemem_tbl+44
	ldr r1,=empty_R
	cmp r0,#0x8
	adreq r1,clk_sec
	cmp r0,#0x9
	adreq r1,clk_min
	cmp r0,#0xA
	adreq r1,clk_hrs
	cmp r0,#0xB
	adreq r1,clk_dayL
	cmp r0,#0xC
	adreq r1,clk_dayH
	str_ r1,readmem_tbl_-40
	str_ r1,readmem_tbl_-44
	mov pc,lr

@------------------------------
clk_sec:
	ldrb_ r0,mapperdata+30
	b calctime
@------------------------------
clk_min:
	ldrb_ r0,mapperdata+29
	b calctime
@------------------------------
clk_hrs:
	ldrb_ r0,mapperdata+28
	and r0,r0,#0x3F
	b calctime
@------------------------------
clk_dayL:
	@The day counter is a plain 9-bit binary count, not BCD -- gettime_sw
	@stores it as `days & 0xFF`.  Running it through calctime turned day 20
	@into 14, so day-based events drifted once the count passed 15.
	ldrb_ r0,mapperdata+26
	mov pc,lr
clk_dayH:
	@bit 0 = day counter bit 8, bit 6 = halt, bit 7 = 512-day carry.  This
	@used to return a flat 0, so the day count wrapped at 256 and the carry
	@was never visible; gettime_sw was already maintaining bit 8 here with
	@nothing reading it.
	ldrb_ r0,mapperdata+27
	and r0,r0,#0xC1
	mov pc,lr
@------------------------------
mbc3rtc_W:	@write to a selected RTC register
@------------------------------
	ldrb_ r1,mapperdata+4
	and r1,r1,#0x0F
	cmp r1,#0x0B
	streqb_ r0,mapperdata+26	@day low: binary, stored as-is
	moveq pc,lr
	cmp r1,#0x0C
	streqb_ r0,mapperdata+27	@day high/halt/carry
	moveq pc,lr
	@Seconds, minutes and hours are held BCD because the readers above
	@decode them with calctime, so convert on the way in.
	and r0,r0,#0x3F
	mov r2,#0
0:	cmp r0,#10
	subcs r0,r0,#10
	addcs r2,r2,#0x10
	bcs 0b
	orr r0,r0,r2
	cmp r1,#0x08
	streqb_ r0,mapperdata+30
	cmp r1,#0x09
	streqb_ r0,mapperdata+29
	cmp r1,#0x0A
	streqb_ r0,mapperdata+28
	mov pc,lr
@------------------------------
calctime:
	and r1,r0,#0xf
	mov r0,r0,lsr#4
	add r0,r0,r0,lsl#2
	add r0,r1,r0,lsl#1 
	mov pc,lr
@------------------------------
	

@----------------------------------------------------------------------------
mbc5init:
@----------------------------------------------------------------------------
	.word RamEnable,MBC5map0,MBC5RAMB,void

	ldr r0,=empty_W					@ Disable RAM = $00
	str_ r0,writemem_tbl+40
	str_ r0,writemem_tbl+44

	mov pc,lr
	.popsection
@----------------------------------------------------------------------------
MBC3map:
@----------------------------------------------------------------------------
	@7-bit ROM bank; bank 0 selects bank 1 on real MBC3
	ands r0,r0,#0x7f
	moveq r0,#1
	b map4567_
@----------------------------------------------------------------------------
MBC5map0:
@----------------------------------------------------------------------------
	tst addy,#0x1000
	andne r0,r0,#0x01
	strneb_ r0,mapperdata+1
	streqb_ r0,mapperdata
	ldr_ r0,mapperdata
	b map4567_
@----------------------------------------------------------------------------
MBC5RAMB:
@----------------------------------------------------------------------------
	@Full byte is stored, including the rumble bit (bit 3) on rumble carts.
	@mapAB_ clamps it against rammask, so it cannot escape the RAM window.
	strb_ r0,mapperdata+4
	b RamSelect

	.pushsection .text
@----------------------------------------------------------------------------
mbc7init:
@----------------------------------------------------------------------------
	.word void,MBC7map,MBC7RAMB,void
	mov pc,lr
	.popsection
@----------------------------------------------------------------------------
MBC7map:
@----------------------------------------------------------------------------
	ands r0,r0,#0x7f
	moveq r0,#1
	strb_ r0,mapperdata
	b map4567_
	.pushsection .text
@----------------------------------------------------------------------------
MBC7RAMB:
@----------------------------------------------------------------------------
	strb_ r0,mapperdata+4
	cmp r0,#9
	movmi r0,#0xA
	movpl r0,#0
	strb_ r0,mapperdata+2
	b RamSelect

@----------------------------------------------------------------------------
huc1init:
@----------------------------------------------------------------------------
	.word RamEnable,HUC1map0,MBC1map1,MBC1mode
@	DCD RamEnable,HUC1map0,MBC5RAMB,void

	ldr r0,=empty_W					@ Disable RAM = $00
	str_ r0,writemem_tbl+40
	str_ r0,writemem_tbl+44

	mov pc,lr
	.popsection
@----------------------------------------------------------------------------
HUC1map0:
@----------------------------------------------------------------------------
	ands r0,r0,#0x3f
	moveq r0,#1
	strb_ r0,mapperdata
@	ldrb r1,mapperdata+1
@	orr r0,r0,r1,lsl#5
	b map4567_

	.pushsection .text
@----------------------------------------------------------------------------
huc3init:
@----------------------------------------------------------------------------
	.word RamEnable,map4567_,MBC5RAMB,void

	ldr r0,=empty_W					@ Disable RAM = $00
	str_ r0,writemem_tbl+40
	str_ r0,writemem_tbl+44

	mov pc,lr

@----------------------------------------------------------------------------
mmm01init:
mbc4init:
mbc6init:
@----------------------------------------------------------------------------
	.word RamEnable,map4567_,void,void

	ldr r0,=empty_W					@ Disable RAM = $00
	str_ r0,writemem_tbl+40
	str_ r0,writemem_tbl+44

	mov pc,lr
	.popsection

@----------------------------------------------------------------------------
@----------------------------------------------------------------------------
	@.end
