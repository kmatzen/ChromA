# Known Issues

## Per-scanline palette rendering (Hercules GBC title screen)

**Status**: Mostly working — no flicker, residual vertical banding

### Current State

DMA3 is always armed during active display. For most games it performs a 1-word PALRAM self-refresh per HBlank (harmless no-op). When per-scanline palette writes are detected (>10 FF69 writes during visible scanlines), DMA3 switches to 64-word mode replaying a per-scanline buffer filled by `ff69_w_tail`. Games with a few mid-frame palette changes (≤10) use VCount interrupts to patch PALRAM at split boundaries.

One artifact remains on the Hercules title screen:

1. **Half-palette vertical banding**: The game writes 32 bytes per scanline (palettes 0-3 only). Tiles using palettes 4-7 don't participate in the per-scanline gradient effect, causing visible vertical bands where those tile columns show static colors instead of the gradient.

### Why DMA3 can't use 64 words for all games

GBA DMA has no source-reload option. With fixed source + 64 words, DMA reads the same 4 bytes and smears them across all 64 destination words — corrupting palettes 9-15. The per-scanline buffer (36KB) works because the source increments through unique data per scanline. Filling that buffer at VBlank costs ~27K cycles (DMA from PALRAM), which is too expensive for the VBlank budget. The 1-word self-refresh avoids both problems.

### How it works

The game's VBlank handler at ROM address `0x0DA2`:
1. Sets BCPS to 0x80 (auto-increment from index 0)
2. Waits for LY=0 (busy-loop on FF44)
3. For each scanline 0-142: waits for HBlank (STAT bit 1), writes 32 bytes to FF69
4. Checks LY=0x8E (142) to stop

The emulator captures these writes:
- `FF69_W` in IWRAM writes to `gbc_palette` and sets `pal_dirty`
- Every 32nd write (BCPS index & 0x1F == 0), branches to `ff69_w_tail` in `.text`
- The tail checks if per-scanline mode is active (>10 visible-scanline triggers)
- If active, expands `gbc_palette` to the DMA buffer at `buffer[scanline * 256]`
- `pal_hdma_wrapper` sets up DMA3 to replay the buffer during GBA display

### Timing analysis

Per-scanline handler cycle budget (double speed, 912 cycles/scanline):
```
STAT wait (Mode 2+3):  ~504 cycles  (21 iterations × 24 cycles)
Palette writes:         ~436 cycles  (16 write pairs + 15 POPs)
LY check + branch:       ~32 cycles
LD HL setup:              ~24 cycles
Total:                   ~996 cycles  → 84-cycle overrun per scanline
```

The handler self-corrects: after the first overrun, subsequent iterations start mid-scanline and wait less for HBlank, oscillating between 84-96 cycle overrun. This is acceptable — the drift is ~1 scanline offset, not cumulative.

### Why the per-scanline hook was removed

The original scanline hook in `timeout.s` ran ~30 instructions per scanline when palette changes were detected. This stole ~70 ARM cycles per scanline from the GBC CPU budget. The handler's 84-cycle overrun margin is tight — adding 70 cycles pushed it to 154 cycles, causing the handler to fail and producing heavy flicker.

The hook was replaced with `b checkTimerIRQ` (zero overhead). Palette detection is now done entirely from `FF69_W`'s tail function in `.text`, which only runs every 32nd palette write (~142 times per frame instead of every scanline).

### Root causes of remaining flicker

1. **GBC/GBA frame desync**: The GBA ARM CPU needs ~3 cycles to emulate 1 GBC cycle. A full GBC frame (154 scanlines × 912 cycles = 140,448 GBC cycles) requires ~420,000-560,000 ARM cycles, but the GBA only has 280,896 ARM cycles per frame. The GBC frame spans ~2 GBA frames, causing the VBlank handler's palette writes to be split across GBA display periods.

2. **No LCD persistence**: Real GBC LCD has slow response time that masks frame-to-frame palette changes. The GBA display refreshes completely each frame, making the half-frame palette splits visible.

3. **Half-palette capture**: Each DMA buffer fill captures `gbc_palette` when only 4 of 8 palettes have been updated for the current scanline. The remaining 4 palettes have the previous scanline's data.

### What was tried and didn't work

- **Hold timer for DMA3 activation**: Kept DMA3 active for N frames after detection. Broke gameplay because stale palette data persisted during non-title-screen scenes.
- **Flat buffer fill from pal_hdma_wrapper**: Filled all 144 entries with the final gbc_palette state. Wrong colors (no per-scanline variation).
- **Dual scanline fill (current + previous)**: Filled both scanline entries at the 64-byte boundary. Caused visual streaks from the double-write overhead.
- **Double-buffered DMA**: Two 36KB buffers, swap at frame start. Didn't help because the issue is write timing, not read/write contention.
- **STAT timing adjustment**: Extended HBlank by 42 dots to eliminate the 84-cycle overrun. Made things worse — the handler's self-correction mechanism was already compensating.
- **Decay-based DMA3 persistence**: Slowly decayed activation counter instead of clearing. Didn't fix the core frame desync issue.
- **Per-scanline hook with reduced instructions**: Even 9 instructions per scanline (vs the original ~30) caused heavy flicker. Budget is 0-5 instructions max.

### ROM analysis details

- VBlank dispatch: FFB7=0x0B → table at `0x0C5C` → handler `0x0DA2`
- Display config table at `0x2D8C`: both CC5E=0 and CC5E=1 entries write the same BG map (`80,81,82...`); the visual difference comes entirely from per-scanline palette data
- Palette data source: WRAM `0xC900`, loaded by `0x2CD8`, read via POP during the VBlank handler
- Handler timing: BCPS=0x80 (auto-increment), writes 32 bytes/scanline to FF69, checks `bit 1,[FF41]` for HBlank and `[FF44]==0x8E` for end of visible area
- The palette copy (5800 bytes to `0xC900`) intentionally overwrites game state at `0xCC5E`

### Instruction timing fixes found during investigation

Pre-existing bugs fixed during this investigation:
- **LD BC/DE/HL/SP,nn** (opcodes 01,11,21,31): Were charging 16 cycles instead of correct 12
- **JR n** (opcode 18): Was charging 8 cycles instead of correct 12 (missing branch penalty)
- **ADD SP,n** (opcode E8): Was charging 12 cycles instead of correct 16

These are now validated automatically by `scripts/validate_timing.py` during every build.
