#ifndef __MAIN_H__
#define __MAIN_H__

#define NORETURN __attribute__ ((noreturn))

#include "includes.h"

#define TRIM 0x4D495254

extern u32 max_multiboot_size;

extern u32 oldinput;
extern u8 *textstart;//points to first GB rom (initialized by boot.s)
extern u8 *ewram_start;//points to first NES rom (initialized by boot.s)
extern int roms;//total number of roms
extern int ui_x;
extern int ui_y;
extern int ui_y_real;
#if POGOSHELL
extern char pogoshell_romname[32];	//keep track of rom name (for state saving, etc)
extern char pogoshell;
#endif
extern char rtc;
extern char gameboyplayer;
extern char gbaversion;

void C_entry(void);
void splash(const u16* splashImage);
void jump_to_rommenu(void) NORETURN;
void rommenu(void);
u8 *findrom2(int n);
u8 *findrom(int n);

#endif
