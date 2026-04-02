#include "includes.h"

#define page_size (16)
#define page_size_2 (page_size*1024)

#define CRAP_AMOUNT 512

u8 *const bank_1=(u8*)0x06010000-CRAP_AMOUNT;

u8 *make_instant_pages(u8* rom_base)
{
	//this is for cases where there is no caching!
	u32 *p=(u32*)rom_base;
	u8 *page0_rom;
//	u8 cartsizebyte;
	int i;
	
#if USETRIM
	if (*p==TRIM)
	{
		p+=2;
//		num_pages=p[0]/4-8;
//		page_mask=num_pages-1;
		for (i=0;i<256;i++)
		{
			INSTANT_PAGES[i]=rom_base+p[i];//&page_mask];
		}
	}
	else
#endif
	{
//		num_pages=(2<<rom_base[148]);
//		page_mask=num_pages-1;
		for (i=0;i<256;i++)
		{
			INSTANT_PAGES[i]=rom_base+16384*(i);//&page_mask);
		}
	}
	page0_rom=INSTANT_PAGES[0];
//	cartsizebyte=page0_rom[0x148];

//	if (cartsizebyte>0)
	{
		//copy bank 0 to VRAM
//		memcpy(bank_1,page0_rom,16384);
		memcpy(bank_1,page0_rom,16384+CRAP_AMOUNT);
		INSTANT_PAGES[0]=bank_1;
	}
	return page0_rom;
}

void init_cache() {}
