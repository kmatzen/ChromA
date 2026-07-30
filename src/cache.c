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
		//Bank count comes from header byte 0x148: the cart is 32KB << n, so
		//it has 2<<n 16KB banks.  This used to map all 256 entries as
		//rom_base+16384*i unconditionally (the masking was commented out),
		//so every entry past the end of the cart pointed at whatever followed
		//it in GBA ROM -- the next appended ROM, or unmapped space past
		//__rom_end__ for the last one (issue #57 item 6).
		//
		//cart.s already masks bank numbers with rommask>>14, derived from
		//this same byte, and clamps the size to 4MB because this table only
		//has 256 entries.  Mirror that clamp exactly so the two agree, and
		//alias out-of-range banks back into the cart the way the real MBCs
		//do rather than pointing them outside it.
		//
		//A header that overstates its size still can't be caught here --
		//nothing in the image records the true ROM length -- but it no longer
		//reads foreign memory for banks the header does declare.
		u32 sizebyte=rom_base[0x148];
		u32 num_pages=(sizebyte<8)?(2u<<sizebyte):256u;
		u32 page_mask=num_pages-1;
		for (i=0;i<256;i++)
		{
			INSTANT_PAGES[i]=rom_base+page_size_2*(i&page_mask);
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
