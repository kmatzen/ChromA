@	#include "equates.h"
@	#include "lcd.h"

	global_func Sound_reset
	global_func _FF10W
	global_func _FF11W
	global_func _FF12W
	global_func _FF13W
	global_func _FF14W
	global_func _FF16W
	global_func _FF17W
	global_func _FF18W
	global_func _FF19W
	global_func _FF1AW
	global_func _FF1BW
	global_func _FF1CW
	global_func _FF1DW
	global_func _FF1EW
	global_func _FF20W
	global_func _FF21W
	global_func _FF22W
	global_func _FF23W
	global_func _FF24W
	global_func _FF25W
	global_func _FF26W
	global_func _FF30W

	global_func _FF10R
	global_func _FF11R
	global_func _FF12R
	global_func _FF13R
	global_func _FF14R
	global_func _FF16R
	global_func _FF17R
	global_func _FF18R
	global_func _FF19R
	global_func _FF1AR
	global_func _FF1BR
	global_func _FF1CR
	global_func _FF1DR
	global_func _FF1ER
	global_func _FF20R
	global_func _FF21R
	global_func _FF22R
	global_func _FF23R
	global_func _FF24R
	global_func _FF25R
	global_func _FF26R
	global_func _FF30R
 .align
 .pool
 .text
 .align
 .pool

@----------------------------------------------------------------------------
Sound_reset:
@----------------------------------------------------------------------------
	mov r1,#REG_BASE

	@Master enable has to be set first: the GBA ignores writes to the PSG
	@registers at 4000060-4000080 while the APU is powered down, so NR50/NR51
	@below were being dropped and came up as 0x00 instead of 0x77/0xF3.
	mov r0,#0xF1
	strh r0,[r1,#REG_SGCNT_X]	@sound master enable. NR52

	ldr r0,=0x0002F377		@stop all channels, output ratio=full range. NR50,NR51 & GBA mixer
	str r0,[r1,#REG_SGCNT_L]


	mov r0,#0x0000
	strh r0,[r1,#REG_SG1CNT_L]	@NR10, reads 0x80 (bit 7 unused)
	@The DMG boot ROM leaves NR11=0x80 (duty 10) and NR12=0xF3 behind, and a
	@cart booted without a boot ROM has to find them already set: NR11 must
	@read 0xBF and NR12 0xF3, not 0x3F and 0x00.  The rest of the post-boot
	@table is either zero or made up purely of write-only and unused bits,
	@which the _FFxxR masks already supply from a zeroed GBA register.
	mov r2,#0x80			@NR11 duty 10, length 0
	orr r2,r2,#0xF300		@NR12 envelope 0xF3 (DAC on, not triggered)
	strh r2,[r1,#REG_SG1CNT_H]	@NR11,NR12, reads 0xF3BF
	@SaveIo reports sound_shadow for NR11, so seed it with the same byte or a
	@state taken before the game ever writes NR11 loses the duty bits.
	strb_ r2,sound_shadow+0
	strh r0,[r1,#REG_SG1CNT_X]	@(NR13),NR14, should read 0xBF00

	strh r0,[r1,#REG_SG2CNT_L]	@NR21,NR22
	strh r0,[r1,#REG_SG2CNT_H]	@NR24

	strh r0,[r1,#REG_SG3CNT_L]	@NR30, should read 0x7F
	strh r0,[r1,#REG_SG3CNT_H]	@NR31,NR32 should read 0x9FFF
	strh r0,[r1,#REG_SG3CNT_X]	@NR33, should read 0xBF

	strh r0,[r1,#REG_SG4CNT_L]	@NR41,NR42
	strh r0,[r1,#REG_SG4CNT_H]	@NR43,NR44

	mov pc,lr

@----------------------------------------------------------------------------
_FF10W:@		NR10 - Channel 1 Sweep register
@----------------------------------------------------------------------------
	mov addy,#REG_BASE
	strb r0,[addy,#REG_SG1CNT_L]
	mov pc,lr
@----------------------------------------------------------------------------
_FF11W:@		NR11 - Channel 1 Sound length/Wave pattern duty
@----------------------------------------------------------------------------
	mov addy,#REG_BASE
	strb r0,[addy,#REG_SG1CNT_H]
	strb_ r0,sound_shadow+0
	mov pc,lr
@----------------------------------------------------------------------------
_FF12W:@		NR12 - Channel 1 Volume Envelope
@----------------------------------------------------------------------------
	mov addy,#REG_BASE
	strb r0,[addy,#REG_SG1CNT_H+1]
	mov pc,lr
@----------------------------------------------------------------------------
_FF13W:@		NR13 - Channel 1 Frequency lo
@----------------------------------------------------------------------------
	mov addy,#REG_BASE
	strb r0,[addy,#REG_SG1CNT_X]
	strb_ r0,sound_shadow+1
	mov pc,lr
@----------------------------------------------------------------------------
_FF14W:@		NR14 - Channel 1 Frequency hi
@----------------------------------------------------------------------------
	mov addy,#REG_BASE
	strb r0,[addy,#REG_SG1CNT_X+1]
	strb_ r0,sound_shadow+2
	mov pc,lr

@----------------------------------------------------------------------------
_FF16W:@		NR21 - Channel 2 Sound Length/Wave Pattern Duty
@----------------------------------------------------------------------------
	mov addy,#REG_BASE
	strb r0,[addy,#REG_SG2CNT_L]
	strb_ r0,sound_shadow+3
	mov pc,lr
@----------------------------------------------------------------------------
_FF17W:@		NR22 - Channel 2 Volume Envelope
@----------------------------------------------------------------------------
	mov addy,#REG_BASE
	strb r0,[addy,#REG_SG2CNT_L+1]
	mov pc,lr
@----------------------------------------------------------------------------
_FF18W:@		NR23 - Channel 2 Frequency lo
@----------------------------------------------------------------------------
	mov addy,#REG_BASE
	strb r0,[addy,#REG_SG2CNT_H]
	strb_ r0,sound_shadow+4
	mov pc,lr
@----------------------------------------------------------------------------
_FF19W:@		NR24 - Channel 2 Frequency hi
@----------------------------------------------------------------------------
	mov addy,#REG_BASE
	strb r0,[addy,#REG_SG2CNT_H+1]
	strb_ r0,sound_shadow+5
	mov pc,lr

@----------------------------------------------------------------------------
_FF1AW:@		NR30 - Channel 3 Sound on/off
@----------------------------------------------------------------------------
	mov addy,#REG_BASE
	and r0,r0,#0x80
	orr r0,r0,r0,lsr#1		@also change wave bank when turning on/off sound.
	strb r0,[addy,#REG_SG3CNT_L]
	mov pc,lr
@----------------------------------------------------------------------------
_FF1BW:@		NR31 - Channel 3 Sound Length
@----------------------------------------------------------------------------
	mov addy,#REG_BASE
	strb r0,[addy,#REG_SG3CNT_H]
	strb_ r0,sound_shadow+6
	mov pc,lr
@----------------------------------------------------------------------------
_FF1CW:@		NR32 - Channel 3 Select output level
@----------------------------------------------------------------------------
	mov addy,#REG_BASE
	and r0,r0,#0x60
	strb r0,[addy,#REG_SG3CNT_H+1]
	mov pc,lr
@----------------------------------------------------------------------------
_FF1DW:@		NR33 - Channel 3 Frequency lo
@----------------------------------------------------------------------------
	mov addy,#REG_BASE
	strb r0,[addy,#REG_SG3CNT_X]
	strb_ r0,sound_shadow+7
	mov pc,lr
@----------------------------------------------------------------------------
_FF1EW:@		NR34 - Channel 3 Frequency hi
@----------------------------------------------------------------------------
	mov addy,#REG_BASE
	strb r0,[addy,#REG_SG3CNT_X+1]
	strb_ r0,sound_shadow+8
	mov pc,lr

@----------------------------------------------------------------------------
_FF30W:@		Channel 3 wave data
@----------------------------------------------------------------------------
	mov r1,#REG_BASE
	add r2,r2,#0x60			@GB 30-3F, GBA 90-9F.
	strb r0,[r1,r2]
	@The GBA plays the wave bank selected by SG3CNT_L bit 6 and exposes the
	@other one at 0090-009F, and _FF1AW flips that bit along with NR30 bit 7
	@so data written while channel 3 is off lands in the bank that starts
	@playing when it is switched on (Alleyway wants it that way).  The GB has
	@only one buffer though, so a write made while the channel is *playing*
	@has to reach the live bank as well -- games that stream wave data without
	@toggling NR30 otherwise keep hearing the previous waveform.  Writing both
	@banks makes it not matter which one is live, and leaves the off-then-on
	@double-buffer above working unchanged.
	ldrb addy,[r1,#REG_SG3CNT_L]
	eor addy,addy,#0x40		@expose the other bank...
	strb addy,[r1,#REG_SG3CNT_L]
	strb r0,[r1,r2]
	eor addy,addy,#0x40		@...and put the selection back
	strb addy,[r1,#REG_SG3CNT_L]
	mov pc,lr

@----------------------------------------------------------------------------
_FF20W:@		NR41 - Channel 4 Sound Length
@----------------------------------------------------------------------------
	mov addy,#REG_BASE
	strb r0,[addy,#REG_SG4CNT_L]
	mov pc,lr
@----------------------------------------------------------------------------
_FF21W:@		NR42 - Channel 4 Volume Envelope
@----------------------------------------------------------------------------
	mov addy,#REG_BASE
	strb r0,[addy,#REG_SG4CNT_L+1]
	mov pc,lr
@----------------------------------------------------------------------------
_FF22W:@		NR43 - Channel 4 Polynomial Counter
@----------------------------------------------------------------------------
	mov addy,#REG_BASE
	strb r0,[addy,#REG_SG4CNT_H]
	mov pc,lr
@----------------------------------------------------------------------------
_FF23W:@		NR44 - Channel 4 Counter/consecutive; Inital
@----------------------------------------------------------------------------
	mov addy,#REG_BASE
	strb r0,[addy,#REG_SG4CNT_H+1]
	mov pc,lr

@----------------------------------------------------------------------------
_FF24W:@		NR50 - Channel control / ON-OFF / Volume
@----------------------------------------------------------------------------
	mov addy,#REG_BASE
	strb r0,[addy,#REG_SGCNT_L]
	mov pc,lr
@----------------------------------------------------------------------------
_FF25W:@		NR51 - Selection of Sound output terminal
@----------------------------------------------------------------------------
	mov addy,#REG_BASE
	strb r0,[addy,#REG_SGCNT_L+1]
	mov pc,lr
@----------------------------------------------------------------------------
_FF26W:@		NR52 - Sound on/off
@----------------------------------------------------------------------------
	mov addy,#REG_BASE
	strb r0,[addy,#REG_SGCNT_X]
	tst r0,#0x80
	movne pc,lr
	@Clearing bit 7 powers the APU down, and the GBA resets every PSG register
	@to zero when that happens.  sound_shadow holds the write-only halves of
	@those registers on SaveIo's behalf and nothing else ever clears it, so a
	@state saved after a power-cycle used to restore values the APU no longer
	@held: power off, power back on, save, load, and NR11's duty bits return
	@from before the power-cycle.  Follow the hardware and drop them.
	mov r0,#0
	strb_ r0,sound_shadow+0
	strb_ r0,sound_shadow+1
	strb_ r0,sound_shadow+2
	strb_ r0,sound_shadow+3
	strb_ r0,sound_shadow+4
	strb_ r0,sound_shadow+5
	strb_ r0,sound_shadow+6
	strb_ r0,sound_shadow+7
	strb_ r0,sound_shadow+8
	mov pc,lr

@----------------------------------------------------------------------------


@----------------------------------------------------------------------------
_FF10R:@		NR10 - Channel 1 Sweep register
@----------------------------------------------------------------------------
	mov r1,#REG_BASE
	ldrb r0,[r1,#REG_SG1CNT_L]
	orr r0,r0,#0x80		@NR10 bit 7 is unused
	mov pc,lr
@----------------------------------------------------------------------------
_FF11R:@		NR11 - Channel 1 Sound length/Wave pattern duty
@----------------------------------------------------------------------------
	mov r1,#REG_BASE
	ldrb r0,[r1,#REG_SG1CNT_H]
	orr r0,r0,#0x3F		@NR11 length (bits 5-0) is write-only; the duty reads back
	mov pc,lr
@----------------------------------------------------------------------------
_FF12R:@		NR12 - Channel 1 Volume Envelope
@----------------------------------------------------------------------------
	mov r1,#REG_BASE
	ldrb r0,[r1,#REG_SG1CNT_H+1]
	mov pc,lr
@----------------------------------------------------------------------------
_FF13R:@		NR13 - Channel 1 Frequency lo
@----------------------------------------------------------------------------
	mov r0,#0xff		@NR13 is write-only; it reads back $FF
	mov pc,lr
@----------------------------------------------------------------------------
_FF14R:@		NR14 - Channel 1 Frequency hi
@----------------------------------------------------------------------------
	mov r1,#REG_BASE
	ldrb r0,[r1,#REG_SG1CNT_X+1]
	orr r0,r0,#0xBF		@NR14 only bit 6 (length enable) reads back
	mov pc,lr

@----------------------------------------------------------------------------
_FF16R:@		NR21 - Channel 2 Sound Length/Wave Pattern Duty
@----------------------------------------------------------------------------
	mov r1,#REG_BASE
	ldrb r0,[r1,#REG_SG2CNT_L]
	orr r0,r0,#0x3F		@NR21 length (bits 5-0) is write-only; the duty reads back
	mov pc,lr
@----------------------------------------------------------------------------
_FF17R:@		NR22 - Channel 2 Volume Envelope
@----------------------------------------------------------------------------
	mov r1,#REG_BASE
	ldrb r0,[r1,#REG_SG2CNT_L+1]
	mov pc,lr
@----------------------------------------------------------------------------
_FF18R:@		NR23 - Channel 2 Frequency lo
@----------------------------------------------------------------------------
	mov r0,#0xff		@NR23 is write-only; it reads back $FF
	mov pc,lr
@----------------------------------------------------------------------------
_FF19R:@		NR24 - Channel 2 Frequency hi
@----------------------------------------------------------------------------
	mov r1,#REG_BASE
	ldrb r0,[r1,#REG_SG2CNT_H+1]
	orr r0,r0,#0xBF		@NR24 only bit 6 (length enable) reads back
	mov pc,lr

@----------------------------------------------------------------------------
_FF1AR:@		NR30 - Channel 3 Sound on/off
@----------------------------------------------------------------------------
	mov r1,#REG_BASE
	ldrb r0,[r1,#REG_SG3CNT_L]
	and r0,r0,#0x80
	orr r0,r0,#0x7F		@NR30 only bit 7 (DAC) reads back
	mov pc,lr
@----------------------------------------------------------------------------
_FF1BR:@		NR31 - Channel 3 Sound Length
@----------------------------------------------------------------------------
	mov r0,#0xff		@NR31 is write-only; it reads back $FF
	mov pc,lr
@----------------------------------------------------------------------------
_FF1CR:@		NR32 - Channel 3 Select output level
@----------------------------------------------------------------------------
	mov r1,#REG_BASE
	ldrb r0,[r1,#REG_SG3CNT_H+1]
	and r0,r0,#0x60
	orr r0,r0,#0x9F		@NR32 only bits 6-5 (output level) read back
	mov pc,lr
@----------------------------------------------------------------------------
_FF1DR:@		NR33 - Channel 3 Frequency lo
@----------------------------------------------------------------------------
	mov r0,#0xff		@NR33 is write-only; it reads back $FF
	mov pc,lr
@----------------------------------------------------------------------------
_FF1ER:@		NR34 - Channel 3 Frequency hi
@----------------------------------------------------------------------------
	mov r1,#REG_BASE
	ldrb r0,[r1,#REG_SG3CNT_X+1]
	orr r0,r0,#0xBF		@NR34 only bit 6 (length enable) reads back
	mov pc,lr

@----------------------------------------------------------------------------
_FF30R:@		Channel 3 wave data
@----------------------------------------------------------------------------
	mov r1,#REG_BASE
	add r2,r2,#0x60			@GB 30-3F, GBA 90-9F.
	ldrb r0,[r1,r2]
	mov pc,lr

@----------------------------------------------------------------------------
_FF20R:@		NR41 - Channel 4 Sound Length
@----------------------------------------------------------------------------
	mov r0,#0xff		@NR41 is write-only; it reads back $FF
	mov pc,lr
@----------------------------------------------------------------------------
_FF21R:@		NR42 - Channel 4 Volume Envelope
@----------------------------------------------------------------------------
	mov r1,#REG_BASE
	ldrb r0,[r1,#REG_SG4CNT_L+1]
	mov pc,lr
@----------------------------------------------------------------------------
_FF22R:@		NR43 - Channel 4 Polynomial Counter
@----------------------------------------------------------------------------
	mov r1,#REG_BASE
	ldrb r0,[r1,#REG_SG4CNT_H]
	mov pc,lr
@----------------------------------------------------------------------------
_FF23R:@		NR44 - Channel 4 Counter/consecutive; Inital
@----------------------------------------------------------------------------
	mov r1,#REG_BASE
	ldrb r0,[r1,#REG_SG4CNT_H+1]
	orr r0,r0,#0xBF		@NR44 only bit 6 (length enable) reads back
	mov pc,lr

@----------------------------------------------------------------------------
_FF24R:@		NR50 - Channel control / ON-OFF / Volume
@----------------------------------------------------------------------------
	mov r1,#REG_BASE
	ldrb r0,[r1,#REG_SGCNT_L]
	mov pc,lr
@----------------------------------------------------------------------------
_FF25R:@		NR51 - Selection of Sound output terminal
@----------------------------------------------------------------------------
	mov r1,#REG_BASE
	ldrb r0,[r1,#REG_SGCNT_L+1]
	mov pc,lr
@----------------------------------------------------------------------------
_FF26R:@		NR52 - Sound on/off
@----------------------------------------------------------------------------
	mov r1,#REG_BASE
	ldrb r0,[r1,#REG_SGCNT_X]
	@work around for bugs in VBA-M, fixes Zelda Oracles games when running Goomba Color in that emulator
	ldrb r2,[r1,#REG_SG3CNT_L]	@is channel 3 "play" flag off?
	tst r2,#0x80
	biceq r0,#0x04				@clear "channel 3 is playing" bit
	
	orr r0,r0,#0x70		@NR52 bits 6-4 are unused
	mov pc,lr

@----------------------------------------------------------------------------
	@.end

