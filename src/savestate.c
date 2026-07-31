#include "includes.h"

void AfterLoadState(void);

/* The SGB globals block in sgb.s, starting at packetcursor.  Only the SGB
 * protocol state is part of a savestate; see SaveSgb below for the layout and
 * for why the bytes in the middle are deliberately left out.
 */
extern u8 g_sgb_state[];

#define SGB_PROTOCOL_BYTES 12   /* packetcursor, packetbitcursor, packetstate,
                                 * player_turn, player_mask, sgb_mask */
#define SGB_LINESLOW_OFF   24   /* lineslow, past the settings bytes */
#define SGB_SAVE_BYTES     16   /* the 12 above, lineslow, 3 reserved */

typedef int(*saveFuncPtr)(u8*);
typedef bool(*loadFuncPtr)(u8*, int);

int SaveVers(u8* dest);
int SaveRam(u8 *dest);
int SaveRam2(u8 *dest);
int SaveVram(u8 *dest);
int SaveIo(u8 *dest);
int SaveRegs(u8* dest);
int SaveMapper(u8 *dest);
int SavePalette(u8 *dest);
int SaveEmu(u8 *dest);
int SaveOam(u8 *dest);
int SaveSgb(u8 *dest);

static const int SAVE_VERSION = 1;
EWRAM_BSS int saveVersion;

bool LoadVers(u8 *src, int size);
bool LoadRam(u8 *src, int size);
bool LoadRam2(u8 *src, int size);
bool LoadVram(u8 *src, int size);
bool LoadIo(u8 *src, int size);
bool LoadRegs(u8 *src, int size);
bool LoadMapper(u8 *src, int size);
bool LoadPalette(u8 *src, int size);
bool LoadEmu(u8 *src, int size);
bool LoadOam(u8 *src, int size);
bool LoadSgb(u8 *src, int size);

const char tags[][4] =
{
	{'V','E','R','S'},
	{'R','A','M',' '},
	{'R','A','M','2'},
	{'V','R','A','M'},
	{'I','O',' ',' '},
	{'R','E','G','S'},
	{'M','A','P','R'},
	{'P','A','L',' '},
	{'E','M','U',' '},
	{'O','A','M',' '},
	{'S','G','B',' '},
};

const saveFuncPtr saveFunc[] =
{
	SaveVers,
	SaveRam,
	SaveRam2,
	SaveVram,
	SaveIo,
	SaveRegs,
	SaveMapper,
	SavePalette,
	SaveEmu,
	SaveOam,
	SaveSgb
};

const loadFuncPtr loadFunc[] =
{
	LoadVers,
	LoadRam,
	LoadRam2,
	LoadVram,
	LoadIo,
	LoadRegs,
	LoadMapper,
	LoadPalette,
	LoadEmu,
	LoadOam,
	LoadSgb
};

typedef enum 
{
	_Success,
	_OutOfBoundsTag,
	_UnknownTag,
	_Failed
} LoadStateError;

static u32 GetTagName(int tagId)
{
	if (tagId < 0 || tagId >= ARRSIZE(tags))
	{
		return 0;
	}
	else
	{
		const char *tagNameChar = tags[tagId];
		u32 tagNameInt = *((const u32*)tagNameChar);
		return tagNameInt;
	}
}

static int GetTagId(u32 tagName)
{
	for (int i = 0; i < ARRSIZE(tags); i++)
	{
		u32 otherTag = GetTagName(i);
		if (otherTag == tagName)
		{
			return i;
		}
	}
	return -1;
}


LoadStateError LoadState(u8 *source, int maxLength)
{
	u8 *ptr = source;
	u8 *limit = source + maxLength;
	LoadStateError status = _Success;
	while (ptr < limit)
	{
		//Get Tag Name
		u32 tagName = *((u32*)(ptr + 0));
		u32 tagLength = *((u32*)(ptr + 4));
		
		ptr += 8;
		u8 *nextPtr = ptr + (((tagLength - 1) | 3) + 1);
		if (nextPtr > limit)
		{
			return _OutOfBoundsTag;
		}
		
		int tagId = GetTagId(tagName);
		if (tagId == -1)
		{
			status = _UnknownTag;
			return status;
		}
		else
		{
			bool value = loadFunc[tagId](ptr, tagLength);
			if (value == false)
			{
				status = _Failed;
				return status;
			}
		}
		ptr = nextPtr;
	}
	AfterLoadState();
	return status;
}

int SaveState(u8 *dest)
{
	u8 *startPosition = dest;
	for (int i=0; i < ARRSIZE(tags); i++)
	{
		u32 tagName = GetTagName(i);
		int size = saveFunc[i](dest + 8);
		if (size > 0)
		{
			*((u32*)dest) = tagName;
			dest += 4;
			*((u32*)dest) = size;
			dest += 4;
			dest += size;
		}
	}
	return dest - startPosition;
}


int SaveVers(u8 *dest)
{
	*((u32*)(dest)) = SAVE_VERSION;
	return 4;
}
//in state.s
//int SaveRegs(u8* dest)
//{
//	return 0;
//}
int SaveRam(u8 *dest)
{
	memcpy32(dest, XGB_RAM, 0x2000);
	return 0x2000;
}
int SaveRam2(u8 *dest)
{
	if (gbc_mode)
	{
		memcpy32(dest, GBC_EXRAM, 0x6000);
		return 0x6000;
	}
	return 0;
}
int SaveVram(u8 *dest)
{
	if (!gbc_mode)
	{
		memcpy32(dest, XGB_VRAM, 0x2000);
		return 0x2000;
	}
	else
	{
		memcpy32(dest, XGB_VRAM, 0x4000);
		return 0x4000;
	}
	return 0;
}
//In state.s
//int SaveIo(u8 *dest)
//{
//	return 0;
//}
int SaveMapper(u8 *dest)
{
	memcpy32(dest, g_banks, 44);
	return 44;
}
int SavePalette(u8 *dest)
{
	if (gbc_mode)
	{
		memcpy32(dest, gbc_palette, 128);
		return 128;
	}
	return 0;
}
int SaveEmu(u8 *dest)
{
	return 0;
}
int SaveOam(u8 *dest)
{
	memcpy32(dest, _gb_oam_buffer_writing, 160);
	return 160;
}
/* SGB protocol state.  This returned 0, so no SGB section was ever written and
 * a state taken during the SGB handshake came back with the packet assembler
 * mid-transfer, the screen mask lost and the multiplayer turn reset (#51).
 *
 * What is saved is the protocol state only: the packet cursors and state
 * machine, which player's pad is being read, the player mask, the screen mask,
 * and lineslow (the player-switch bitmask).  The bytes between sgb_mask and
 * lineslow -- update_border_palette, autoborder, autoborderstate,
 * borderpartsadded, and the two boot-hack frame stamps -- are ChromA's own
 * settings and boot bookkeeping rather than game state.  Restoring autoborder
 * from a state would override the setting the user has now, and the frame
 * stamps are absolute counts that mean nothing after a load.
 *
 * Nothing is written for a non-SGB game, exactly as SavePalette does for
 * non-CGB: states for other games keep their existing layout, so this only
 * changes the format of SGB states.
 */
int SaveSgb(u8 *dest)
{
	if (!sgb_mode)
	{
		return 0;
	}
	memcpy32(dest, g_sgb_state, SGB_PROTOCOL_BYTES);
	dest[12] = g_sgb_state[SGB_LINESLOW_OFF];
	dest[13] = 0;
	dest[14] = 0;
	dest[15] = 0;
	return SGB_SAVE_BYTES;
}

bool LoadVers(u8 *src, int size)
{
	if (size == 4)
	{
		saveVersion = *((u32*)(src));
		return true;
	}
	return false;
}
//bool LoadRegs(u8 *src, int size)
//{
//	return false;
//}
bool LoadRam(u8 *src, int size)
{
	if (size == 0x2000)
	{
		memcpy32(XGB_RAM, src, size);
		return true;
	}
	return false;
}
bool LoadRam2(u8 *src, int size)
{
	if (size == 0x6000)
	{
		memcpy32(GBC_EXRAM, src, size);
		return true;
	}
	return false;
}
bool LoadVram(u8 *src, int size)
{
	if (size == 0x2000 || size == 0x4000)
	{
		memcpy32(XGB_VRAM, src, size);
		return true;
	}
	return false;
}
//In state.s
//bool LoadIo(u8 *src, int size)
//{
//	return false;
//}
bool LoadMapper(u8 *src, int size)
{
	if (size == 44)
	{
		memcpy32(g_banks, src, size);
		return true;
	}
	return false;
}
bool LoadPalette(u8 *src, int size)
{
	if (size == 128)
	{
		memcpy32(gbc_palette, src, size);
		return true;
	}
	return false;
}
bool LoadEmu(u8 *src, int size)
{
	return false;
}
bool LoadOam(u8 *src, int size)
{
	if (size == 160)
	{
		memcpy32(_gb_oam_buffer_writing, src, size);
		memcpy32(_gb_oam_buffer_screen, src, size);
		memcpy32(_gb_oam_buffer_alt, src, size);
		return true;
	}
	return false;
}
bool LoadSgb(u8 *src, int size)
{
	if (size == SGB_SAVE_BYTES)
	{
		memcpy32(g_sgb_state, src, SGB_PROTOCOL_BYTES);
		g_sgb_state[SGB_LINESLOW_OFF] = src[12];
		return true;
	}
	return false;
}
