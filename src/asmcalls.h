#ifndef __ASMCALLS_H__
#define __ASMCALLS_H__

static __inline void breakpoint()
{
	__asm volatile ("mov r11,r11");
}


#if ROMVERSION
	extern u8 chroma_mb_gba[];
	#if !GCC
		extern u32 chroma_mb_gba_size[];
		#define CHROMA_MB_GBA_SIZE ((u32)(&chroma_mb_gba_size))
	#else
		extern u32 chroma_mb_gba_size;
		#define CHROMA_MB_GBA_SIZE chroma_mb_gba_size
	#endif
#endif

void jump_r0(u32);

extern u8 auto_border;

extern u8 ui_border_visible;
extern u8 darkness;
extern int ui_x;
extern int ui_y_real;

extern u8 sgb_palette_number;

extern u32 ewram_canary_1;
extern u32 ewram_canary_2;

#if !GCC
extern u8 Image$$RO$$Base[];
extern u8 Image$$RW$$Base[];
extern u8 Image$$RO$$Limit[];
extern u8 Image$$RW$$Limit[];
#endif

//gbz80.s
void update_doublespeed_ui(void);

void emu_reset(void);
void cpuhack_reset(void);
void run(int dont_stop);
extern u32 op_table[256];
extern void default_scanlinehook(void);
extern u32 cpustate[26];
extern u32 _lastbank;

#define STATE_A  (cpustate[1] >> 24)
#define STATE_BC (cpustate[2] >> 16)
#define STATE_DE (cpustate[3] >> 16)
#define STATE_HL (cpustate[4] >> 16)
#define STATE_PC (cpustate[6] - (u32)_lastbank);

extern u8 *rommap[16];
extern u8 *g_memmap_tbl[16];

extern void* g_readmem_tbl[8];
extern void* g_writemem_tbl[8];

extern u32 frametotal;
extern u32 sleeptime;
extern u8 novblankwait;
extern u8 request_gb_type;
extern u8 request_gba_mode;

extern u8 g_hackflags;
extern u32 num_speedhacks;
extern u16 speedhacks[256];

extern u8 gbc_mode;
extern u8 sgb_mode;
extern u8 doubletimer;

extern u8 dontstop;

extern u8 XGB_RAM[0x2000];
extern u8 XGB_HRAM[128];
extern u8 XGB_SRAM[0x8000];
extern u8 XGB_VRAM[0x4000];
extern u8 GBC_EXRAM[0x6000];

//apack.s
void depack(u8 *source, u8 *destination);

//boot.s
extern u8 font_lz77[];				//from boot.s
extern u8 fontpal_bin[];				//from boot.s

//cart.s

extern u8* INSTANT_PAGES[256];

extern u32 g_rammask;
extern u32 g_banks[2];

void loadcart(int rom_number,int emu_flags);			//from cart.s
void map0123_(int page);
void map4567_(int page);
void map01234567_(int page);
void mapAB_(int page);

int savestate(void* dest);
void loadstate(int, void* dest);

extern u32 g_emuflags;
extern u8* romstart;
extern u32 romnum;
extern u32 END_OF_EXRAM;

extern char SramName[256];
extern u8 mapperstate[32];

extern u8 AGB_BG[8192];

extern u8 g_cartflags;	//(from GB header)
extern int bcolor;		//Border Color

//io.s
extern u32 joycfg;				//from io.s
void vbaprint(const char *text);		//io.s
void LZ77UnCompVram(const void *source,u16 *destination);		//io.s
void waitframe(void);			//io.s
int CheckGBAVersion(void);		//io.s
void suspend(void);			//io.s
void waitframe(void);		//io.s
int gettime(void);			//io.s

//lcd.s
extern u32 *vblankfptr;			//from lcd.s
extern u32 vbldummy;			//from lcd.s
extern u32 vblankinterrupt;		//from lcd.s
extern u32 AGBinput;			//from lcd.s
extern u32 EMUinput;

void GFX_init(void);			//lcd.s
void GFX_init_irq(void);			//lcd.s
void debug_(int,int);		//lcd.s
void paletteinit(void);		//lcd.s
void PaletteTxAll(void);	//lcd.s
void transfer_palette(void);	//lcd.s
void move_ui_asm(void);
extern u32 FPSValue;		//from lcd.s
extern u8 fpsenabled;		//from lcd.s
extern u32 palettebank;		//from lcd.s palette bank
extern u8 gammavalue;	//from lcd.s

extern u8 g_lcdhack;
extern u8 _dmamode;
extern u16 _dma_src;
extern u16 _dma_dest;
extern u8 _vrambank;

extern u8 _dma_blocks_remaining;
extern u8 _dma_blocks_total;


extern u8 gbc_palette[];

extern u8* _dirty_tile_bits;
extern u8* _gb_oam_buffer_screen;
extern u8* _gb_oam_buffer_writing;
extern u8* _gb_oam_buffer_alt;

extern u8 dirty_map_words[];

void memcpy32(void *dest, const void *src, int byteCount);
void memset32(void *dest, u32 value, int byteCount);
void memset8(u8 *dest, u8 value, int byteCount);
void memcpy_unaligned_src(void *dest, const void *src, int byteCount);

void copy_map_and_compare(u8 *destAddress, u8 *sourceAddress, int byteCount, u8* dirtyMapWordsPtr);


void update_lcdhack(void);

//io.s
void doReset(void);

//sgb.s
extern u8 g_update_border_palette;

#if SPEEDHACKS_NEW
extern u8 _quickhackcount;
extern u8 _quickhackused;
extern const u8* _speedhack_pc;

void speedhack_reset(void);
void install_speedhack(const u8 *speedhack_pc, int isJump);

#endif

#endif
