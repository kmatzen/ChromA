#ifndef __CACHE_H__
#define __CACHE_H__

extern u8 *const bank_0;
extern u8 *const bank_1;

u8 *make_instant_pages(u8* rom_base);
void init_cache(void);

#endif
