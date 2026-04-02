#include "includes.h"

#define VRAM_CODE	__attribute__((section(".vram1"), long_call))

extern u16 _dma_src;
extern u16 _dma_dest;
extern u8 _vrambank;

//void UpdateTiles1(u8 *sourceAddress, int byteCount, int vramAddress1);
//void UpdateTiles2(u8 *sourceAddress, int byteCount, int vramAddress1);
//void UpdateTiles3(u8 *sourceAddress, int byteCount, int vramAddress1);

void new_dma_packet(u32 newDestAddress, u8* newSourceAddress);

static const int MAX_PACKETS = 24;
typedef struct
{
	u16 dest;
	u16 length;
	u8 *source;
} VramPacketData2;

typedef struct
{
	u16 byteCount;
	u16 tileNumber;
	u8 *source;
} VramPacketData3;

EWRAM_BSS int dmaBaseAddress;

extern VramPacketData2 vram_packets_incoming[];
extern VramPacketData2 vram_packets_registered_bank0[];
extern VramPacketData2 vram_packets_registered_bank1[];
extern VramPacketData3 vram_packets_dirty[];
//int registeredPacketCount0;
//int registeredPacketCount1;




//extern VramPacketData2 vram_packets_finished[];
//extern VramPacketData2 vram_packets_display[];

static __inline bool PacketOverlaps(VramPacketData2 *newPacket, VramPacketData2 *oldPacket)
{
	return newPacket->dest + newPacket->length > oldPacket->dest && newPacket->dest < oldPacket->dest + oldPacket->length;
}

static void RegisterDmaPackets();

static __inline u8* GetRealAddress(int address)
{
	return (u8*)(g_memmap_tbl[address >> 12] + address);
}

static __inline VRAM_CODE void SetBits(u32 *base, int firstBit, int lastBit)
{
	int firstWord = firstBit / 32;
	int firstBitNumber = firstBit & 0x1F;
	int firstMask = (u32)(-1) << firstBitNumber;
	
	int lastWord = lastBit / 32;
	int lastBitNumber = lastBit & 0x1F;
	int lastMask = ~((u32)(-1) << lastBitNumber);
	
	if (firstWord == lastWord)
	{
		base[firstWord] |= (firstMask & lastMask);
	}
	else 
	{
		int i;
		base[firstWord] |= firstMask;
		for (i = firstWord + 1; i < lastWord; i++)
		{
			base[i] |= 0xFFFFFFFF;
		}
		base[i] |= lastMask;
	}
}

static __inline VRAM_CODE void SetDirtyTiles(int dest, int byteCount)
{
	if (dest < 0x9800)
	{
		//mark tiles as dirty
		int firstTileNumber = (dest - 0x8000) >> 4;
		int lastTileNumber = (dest - 0x8000 + byteCount + 15) >> 4;

		int firstBit = firstTileNumber / 2;
		int lastBit = (lastTileNumber + 1) / 2;
		SetBits((u32*)_dirty_tile_bits, firstBit, lastBit);
	}
}

void VRAM_CODE DoDma(int byteCountRemaining)
{
	while (byteCountRemaining > 0)
	{
		//first do range and count checking to make memory blocks contiguous

		int byteCount = byteCountRemaining;
		byteCountRemaining = 0;

		int src = _dma_src;

		int srcEnd = src + byteCount;
		int srcEndBlock = (srcEnd - 1) & 0xF000;  // What do all these hex values mean
		int srcBlock = src & 0xF000;
		
		if (src < 0x8000)
		{
			srcBlock &= 0xC000;
			srcEndBlock &= 0xC000;
		}
		
		if (srcEndBlock != srcBlock)
		{
			byteCountRemaining += srcEnd - srcEndBlock;
			byteCount = srcEndBlock - src;
		}
		
		int dest = _dma_dest;
		int destEnd = dest + byteCount;
		
		int destEndBlock = (destEnd - 1) & 0xF800;
		int destBlock = dest & 0xF800;
		
		if (destEndBlock != destBlock)
		{
			byteCountRemaining += destEnd - destEndBlock;
			byteCount = destEndBlock - dest;
		}
		
		u8 *sourceAddress = GetRealAddress(src);
		
		
		if (_dmamode == 2)  // _dmamode 2 is for WayForward games, leave alone
		{
			u8 *destAddress = GetRealAddress(dest);
			if (dest == 0x8000 && src == dmaBaseAddress)  // 0x8000 = lowest VRAM destination?
			{
				//finish up list of DMA packets
				new_dma_packet(0, NULL);
				RegisterDmaPackets();
			}
			else
			{
				if (dest >= 0x9800)  // 0x9800 = highest VRAM destination?
				{
					copy_map_and_compare(destAddress, sourceAddress, byteCount, &dirty_map_words[(dest - 0x9800) / 32]);
					//_set_bg_cache_full(2);
				}
				else
				{
					memcpy32(destAddress, sourceAddress, byteCount);
					SetDirtyTiles(dest, byteCount);
				}
			}
		}
		else if (_dmamode != 1)
		{
			//do the memory copy
			u8 *destAddress = GetRealAddress(dest);
            if (dest >= 0x9800)
            {
                copy_map_and_compare(destAddress, sourceAddress, byteCount, &dirty_map_words[(dest - 0x9800) / 32]);
                //_set_bg_cache_full(2);
            }
            else
            {
                memcpy32(destAddress, sourceAddress, byteCount);
                SetDirtyTiles(dest, byteCount);
            }
		} // else {}  // I guess DMA mode 1 is unused
		
	//finishBlock:
		_dma_src += byteCount;
		_dma_dest += byteCount;
		_dma_dest &= ~0xE000;
		_dma_dest |= 0x8000;
	}
    // Out of the while loop
}


//extern VramPacketData2 vram_packets_incoming[];
//extern u8* vram_packets_sources[];	//40 of them

//long long vram_packets_dirty;

//extern VramPacketData2 vram_packets_finished[];
//extern VramPacketData2 vram_packets_display[];

extern u32 _vram_packet_dest;
extern u8* _vram_packet_source;

u32 vram_packet_first_dest;
u8 *vram_packet_first_source;

int incoming_packet_cursor;

void VRAM_CODE new_dma_packet(u32 newDestAddress, u8* newSourceAddress)
{
	//we are calling this to finish up the VRAM packet that started at first_source and ended at _vram_packet_source
	u8 *startSource = vram_packet_first_source;
	u32 startDest = vram_packet_first_dest;
	int vramPacketSize = _vram_packet_dest - startDest;
	VramPacketData2 *packet;
	
	if (startDest == 0)
	{
		incoming_packet_cursor = 0;
		packet = &vram_packets_incoming[incoming_packet_cursor];
		packet->dest = 0;
	}
	else if (incoming_packet_cursor < MAX_PACKETS)
	{
		VramPacketData2 *packet = &vram_packets_incoming[incoming_packet_cursor];
		packet->dest = startDest;
		packet->length = vramPacketSize;
		packet->source = startSource;
		incoming_packet_cursor++;
		if (newDestAddress == 0 && incoming_packet_cursor < MAX_PACKETS)
		{
			packet = &vram_packets_incoming[incoming_packet_cursor];
			packet->dest = 0;
		}
	}
	else
	{
		//cache full, see if this ever happens
		breakpoint();
	}
	
	vram_packet_first_source = newSourceAddress;
	vram_packet_first_dest = newDestAddress;
	_vram_packet_source = newSourceAddress + 0x20;
	_vram_packet_dest = newDestAddress + 0x20;
}

static int GetPacketListCount(VramPacketData2 *list)
{
	int outCount = MAX_PACKETS;
	for (int i = 0; i < MAX_PACKETS; i++)
	{
		if (list[i].dest == 0)
		{
			outCount = i;
			break;
		}
	}
	return outCount;
}

static void InsertIntoPacketList(VramPacketData2 *list, int listCount, int index)
{
	//copy elements from index to listCount into index+1 to listCount+1
	int copyCount = listCount - index;
	if (copyCount <= 0)
	{
		return;
	}
	memmove(&list[index + 1], &list[index], copyCount * sizeof(VramPacketData2));
}

static void RemoveFromPacketList(VramPacketData2 *list, int listCount, int index, int removeCount)
{
	int copyCount = listCount - index - removeCount;
	if (copyCount <= 0)
	{
		return;
	}
	memmove(&list[index], &list[index + removeCount], copyCount * sizeof(VramPacketData2));
}

int dirtyPacketIndex = 0;

static void StoreDirtyPacket(VramPacketData2 *packet)
{
	if (dirtyPacketIndex < MAX_PACKETS)
	{
		VramPacketData3 *out = &vram_packets_dirty[dirtyPacketIndex];
		out->byteCount = packet->length;
		out->tileNumber = (packet->dest - dmaBaseAddress) / 0x10 + _vrambank * 0x180;
		out->source = packet->source;
		
		dirtyPacketIndex++;
	}
}

static void SanityCheckOutList(VramPacketData2 *outList)
{
	//verify that list is sorted and not overlapping
	u32 lastEnd = dmaBaseAddress;
	for (int i=0; i < MAX_PACKETS; i++)
	{
		VramPacketData2 *item = &outList[i];
		//end of list?
		if (item->dest == 0)
		{
			break;
		}
		
		u32 start = item->dest;
		u32 end = item->dest + item->length;
		if (start < lastEnd)
		{
			breakpoint();
			//invalidate the outList
			outList[0].dest = 0;
			break;
		}
		lastEnd = end;
	}
}

static void RegisterDmaPackets()
{
	VramPacketData2 *outList;
	if (_vrambank == 0)
	{
		outList = vram_packets_registered_bank0;
	}
	else
	{
		outList = vram_packets_registered_bank1;
	}
	VramPacketData2 *inList = vram_packets_incoming;

	//sanity check outList
	SanityCheckOutList(outList);

	int inCount, outCount;
	inCount = GetPacketListCount(inList);
	outCount = GetPacketListCount(outList);
	
	
	
	
	int outMin = 0;
	
	dirtyPacketIndex = 0;
	//process incoming packets, see if any are already registered in memory or overlap other registered packets
	for (int inIndex = 0; inIndex < inCount; inIndex++)
	{
		VramPacketData2 *in = &inList[inIndex];
		//examine registered packets
		int outIndex;
		for (outIndex = outMin; outIndex < outCount; outIndex++)
		{
			//incoming packet at same location as existing packet:
			//	replace the packet
			//incoming packet overlapping existing packet:
			//	look ahead at subsequent packets, remove overlapping packets
			//	insert the packet
			//incoming packet after existing packet
			//  proceed to next packet
			//incoming packet before existing packet
			//	insert packet into list
			//empty list
			//	insert packet into list
			
			
			VramPacketData2 *out = &outList[outIndex];
			if (out->dest == in->dest && out->length == in->length)
			{
				outMin = outIndex + 1;
				if (out->source == in->source)
				{
					//accept packet, do nothing
				}
				else
				{
					out->source = in->source;
					StoreDirtyPacket(out);
				}
				goto inserted;
			}
			else if (PacketOverlaps(in, out))
			{
				int deleteCount = 0;
				int deleteIndex = outIndex + 1;
				for (int outIndex2 = deleteIndex; outIndex2 < outCount; outIndex2++)
				{
					VramPacketData2 *out2 = &outList[outIndex2];
					if (PacketOverlaps(in, out2))
					{
						deleteCount++;
					}
					else
					{
						break;
					}
				}
				if (deleteCount >= 1)
				{
					RemoveFromPacketList(outList, outCount, deleteIndex, deleteCount);
					outCount -= deleteCount;
				}
				*out = *in;
				StoreDirtyPacket(out);
				
				outMin = outIndex + 1;
				goto inserted;
			}
			else if (in->dest >= out->dest + out->length)
			{
				outMin = outIndex + 1;
			}
			else if (in->dest + in->length <= out->dest)
			{
				InsertIntoPacketList(outList, outCount, outIndex);
				outCount++;
				*out = *in;
				StoreDirtyPacket(out);
				outMin = outIndex + 1;
				goto inserted;
			}
		}
		outList[outIndex] = *in;
		outCount++;
		StoreDirtyPacket(in);
	inserted:
		;
	}
	if (outCount < MAX_PACKETS)
	{
		outList[outCount].dest = 0;
	}
	if (dirtyPacketIndex < MAX_PACKETS)
	{
		vram_packets_dirty[dirtyPacketIndex].byteCount = 0;
	}
}

