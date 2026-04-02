#ifndef __DMA_H__
#define __DMA_H__

extern u16 _dma_src;
extern u16 _dma_dest;
extern u8 _vrambank;
extern u8 _doing_hdma;
extern u8 _dma_blocks_remaining;

void UpdateTiles1(u8 *sourceAddress, int byteCount, int vramAddress1);
void UpdateTiles2(u8 *sourceAddress, int byteCount, int vramAddress1);
void UpdateTiles3(u8 *sourceAddress, int byteCount, int vramAddress1);

void DoDma(int byteCountRemaining);

#endif
