#include "includes.h"

// Save type identification string for GBA emulators (e.g., mGBA).
// Emulators scan the ROM binary for this marker to detect SRAM support.
// Aligned to 4 bytes with null padding to avoid adjacent data confusing
// the scanner.
static const char sram_id[] __attribute__((used, aligned(4))) = "SRAM_Vnnn";

//#define UI_TILEMAP_NUMBER 30
//#define SCREENBASE (u16*)(MEM_VRAM+UI_TILEMAP_NUMBER*2048)
//#define FONT_MEM (u16*)(MEM_VRAM+0x4000)
#define COLOR_ZERO_TILES (u16*)(MEM_VRAM+0xC000)


EWRAM_BSS u32 oldinput;
EWRAM_BSS u8 *textstart;//points to first GB rom (initialized by boot.s)
EWRAM_BSS u8 *ewram_start;//points to first NES rom (initialized by boot.s)
EWRAM_BSS int roms;//total number of roms
#if RTCSUPPORT
EWRAM_BSS char rtc=0;
#endif
EWRAM_BSS char gameboyplayer=0;
EWRAM_BSS char gbaversion;

#define TRIM 0x4D495254

#if GCC
EWRAM_BSS u32 copiedfromrom=0;
int main()
{
	//this function does what boot.s used to do
	extern u8 __rom_end__[]; //using this instead of __end__, because it's also cart compatible
	extern u8 __eheap_start[];
	
	u32 end_addr = (u32)(&__rom_end__);
	textstart = (u8*)(end_addr);
	u32 heap_addr = (u32)(&__eheap_start);
	ewram_start = (u8*)heap_addr;
	
	if (end_addr < 0x08000000 && copiedfromrom)
	{
		textstart += (0x08000000 - 0x02000000);
	}

	bool is_multiboot = (copiedfromrom == 0) && (end_addr < 0x08000000);
	if (is_multiboot)
	{
		//copy appended data to __iwram_lma
		u8* append_src=(u8*)end_addr;
		u8* append_dest=(u8*)ewram_start;
		u8* EWRAM_end=(u8*)0x02040000;
		memmove(append_dest,append_src,EWRAM_end-append_src);
		textstart=append_dest;
		ewram_start=append_dest;
	}
	
	ewram_canary_1 = 0xDEADBEEF;
	ewram_canary_2 = 0xDEADBEEF;

	C_entry();
	return 0;
}

#endif


void C_entry()
{
	int i,j;
	#if RTCSUPPORT
	vu16 *timeregs=(u16*)0x080000c8;
	#endif
	#if !GCC
	ewram_start=(u8*)&Image$$RO$$Limit;
	if (ewram_start>=(u8*)0x08000000)
	{
		ewram_start=(u8*)0x02000000;
	}
	#endif



	#if RTCSUPPORT
	*timeregs=1;
	if(*timeregs & 1)
		rtc=1;
	#endif
	gbaversion=CheckGBAVersion();
	vblankfptr=&vbldummy;
	
	GFX_init_irq();

	{
		int gbx_id=0x6666edce;
		u8 *p;
		u8 *q;

		#if SPLASH
		bool wantToSplash = false;
		const u16 *splashImage = NULL;
		//splash screen present?
		p=textstart;
		#if USETRIM
		if(*((u32*)p)==TRIM) p+=((u32*)p)[2];
		#endif
		if(*(u32*)(p+0x104)!=gbx_id) {
			wantToSplash = true;
			splashImage = (const u16*)textstart;
			textstart+=76800;
		}
		#endif

		roms=1;
		p=textstart;
		#if USETRIM
		if(*((u32*)p)==TRIM) q=p+((u32*)p)[2];
		else
		#endif
		q=p;
		if(*(u32*)(q+0x104)!=gbx_id)
		{
			get_ready_to_display_text();
			cls(3);
			ui_x=0;
			move_ui();
			drawtext(0,"No ROM found!",0);
			drawtext(19,"ChromA " VERSION,0);
			while (1)
			{
				waitframe();
			}
		}
		if (wantToSplash)
		{
			splash(splashImage);
		}
	}
	
	//Fade either from white, or from whatever bitmap is visible
	if(REG_DISPCNT==FORCE_BLANK)	//is screen OFF?
	{
		REG_DISPCNT=0;				//screen ON
	}
	//start up graphics
	*MEM_PALETTE=0x7FFF;			//white background
	REG_BLDMOD=0x00ff;				//brightness decrease all
	for (i=0;i<17;i++)
	{
		REG_BLDY=i;
		waitframe();
	}
	*MEM_PALETTE=0;					//black background (avoids blue flash when doing multiboot)
	REG_DISPCNT=0;					//screen ON, MODE0
	
	//clear VRAM
	memset32(MEM_VRAM,0,0x18000);
	
	//new: load VRAM code
	extern u8 __vram1_start[], __vram1_lma[], __vram1_end[];
	int vram1_size = ((((u8*)__vram1_end - (u8*)__vram1_start) - 1) | 3) + 1;
	memcpy32((u32*)__vram1_start,(const u32*)__vram1_lma,vram1_size);
	
	//Start up interrupt system
	GFX_init();
	vblankfptr=&vblankinterrupt;
	


//	vcountfptr=&vcountinterrupt;
#if CARTSRAM
	
#endif

	//make 16 solid tiles
	{
		u32*  p=(u32*)COLOR_ZERO_TILES;
		for (i=0;i<16;i++)
		{
			u32 val=(u32)i*(u32)0x11111111;
			for (j=0;j<8;j++)
			{
				*p=val;
				p++;
			}
		}
	}


	//load font+palette
	loadfont();
	loadfontpal();
#if CARTSRAM
	readconfig();
#endif

	jump_to_rommenu();
}

#if SPLASH
//show splash screen
void splash(const u16 *splashImage)
{
	int i;

	REG_DISPCNT=FORCE_BLANK;	//screen OFF
	memcpy((u16*)MEM_VRAM,splashImage,240*160*2);
	waitframe();
	REG_BG2CNT=0x0000;
	REG_DISPCNT=BG2_EN|MODE3;
	for(i=16;i>=0;i--) {	//fade from white
		setbrightnessall(i);
		waitframe();
	}
	for(i=0;i<150;i++) {	//wait 2.5 seconds
		waitframe();
		if (REG_P1==0x030f)
		{
			gameboyplayer=1;
			gbaversion=3;
		}
	}
}
#endif

void jump_to_rommenu(void)
{
#if GCC
	extern u8 __sp_usr[];
	u32 newstack=(u32)(&__sp_usr);
	__asm__ volatile ("mov sp,%0": :"r"(newstack));
#else
	__asm {mov r0,#0x3007f00}		//stack reset
	__asm {mov sp,r0}
#endif
	rommenu();
	run(1);
	while (true);
}


void rommenu(void)
{
	cls(3);
	ui_x=0x100;

	setdarkness(16);
	cls(3);
	make_ui_visible();
#if CARTSRAM
	backup_gb_sram(0); //includes emergency delete menu
#endif

	{
		int i;
		oldinput=AGBinput=~REG_P1;
		loadcart(0,g_emuflags&0x300);
		run(0);
		for(i=1;i<9;i++)
		{
			setdarkness(8-i);		//Lighten screen
			ui_x=i*32;
			move_ui_scroll();
			run(0);
			move_ui_expose();
		}
		cls(3);
		while(AGBinput&(A_BTN+B_BTN+START)) {
			AGBinput=0;
			run(0);
		}
	}
#if CARTSRAM
	if(autostate)quickload();
#endif
	setdarkness(0);
	make_ui_invisible();
	
	//run(1);
}

//returns the start address of the ROM (including TRIM header)
u8 *findrom2(int n)
{
	(void)n;
	return textstart;
}

//returns the first page of the ROM
u8 *findrom(int n)
{
	u8 *p=findrom2(n);
#if USETRIM
	if (*((u32*)p)==TRIM) //trimmed
	{
		p+=((u32*)p)[2];
	}
#endif
	return p;
}

