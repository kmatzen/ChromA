# ChromA — VBlank Frame Profiling

Per-frame timing measured by reading VCOUNT at key points during
the VBlank handler. The GBA has 68 VBlank scanlines (160-227) for
all rendering work. If the handler exceeds this, frames are dropped.

## Method

`profile_mark(slot)` reads `REG_VCOUNT` and stores it. Called at:
- Slot 0: VBlank handler entry
- Slot 1: After `display_frame` (palette transfer, BG wait, BG render)
- Slot 2: After sprite processing (sprite_limit + OAMfinish + restore)
- Slot 3: After tile consumption (consume_recent_tiles + consume_dirty_tiles)

## Results (April 2026)

| Phase | Crystalis | Crystal | Shantae | SML2 |
|-------|-----------|---------|---------|------|
| display_frame | 4 scanlines | 4 scanlines | 4 scanlines | 6 scanlines |
| **sprites** | **9 scanlines** | **9 scanlines** | **19 scanlines** | **15 scanlines** |
| tiles | 1 scanline | 1 scanline | 1 scanline | 2 scanlines |
| **Total** | **14/68 (21%)** | **14/68 (21%)** | **24/68 (35%)** | **23/68 (34%)** |

## Observations

- **Sprite processing dominates**: 65-83% of total VBlank work.
  This includes `sprite_limit_save` (scanning 40 OAM entries × 144
  scanlines), `OAMfinish` (converting 40 GB sprites to GBA OAM),
  and `sprite_limit_restore` (restoring Y values).

- **No game overruns the VBlank budget**. Worst case is Shantae at
  35% (24/68 scanlines). There's comfortable headroom.

- **display_frame** takes 4-6 scanlines, mostly from `transfer_palette_`
  and the VCOUNT wait (busy-waits for scanline 164 to avoid tearing).

- **Tile consumption** is negligible (1-2 scanlines) because most tiles
  are cached between frames.

## TIMA overflow: why mid-scanline detection crashes

Multiple approaches were attempted and all crash Crystalis in mGBA GUI:

1. **nexttimeout redirect + cycle stealing**: `nexttimeout_alt` is shared
   by EI delay, the IRQ hack, and the scanline IRQ delayed path. If any
   of these fire during the stolen-cycles window, they clobber
   `nexttimeout_alt` and the restore chain breaks → PC jumps to garbage.

2. **Per-fetch CYC_TIMA flag**: Still uses nexttimeout for the timeout
   path, same clobber issue.

The root cause is the single-`nexttimeout_alt` architecture. Fixing this
would require either multiple independent timeout channels or a
fundamentally different timer interrupt mechanism.

## Mid-scanline timing via GBA HBlank IRQ

The GBA HBlank hardware interrupt was successfully used for mode 0 STAT
IRQ timing (PR #49). This fires at the exact GBA HBlank boundary with
zero drift. The handler saves/restores r0-r3 on the IRQ stack (since
r3=gb_flg is live during GB execution) and checks lcdstat for mode 0
STAT IE conditions.

A two-phase scanline timeout split was also attempted (PR #48, closed)
but broke Hercules GBC per-scanline palette DMA. The extra timeout
handler overhead (~50 ARM instructions/scanline × 144 scanlines) drifted
GB/GBA scanline alignment by ~6 GBA scanlines. The HBlank IRQ approach
avoids this by using hardware timing instead of software timeouts.

## Instruction-level trace comparison

The TRACE=1 build instruments the fetch macro to record GB CPU state
(PC, AF, BC, DE, HL, SP) per instruction into a 10K-entry EWRAM ring
buffer. The `trace_compare` tool compares this against mGBA's native
GB core stepped instruction-by-instruction.

Results across 20 ROMs: all pass. ~73% of instructions match exactly.
The remaining ~27% are LY (FF44) reads that return different values due
to different frame-start positions (jagoombacolor starts at LY=0, mGBA
at LY≈145). The tool handles these via I/O patching and state resyncs.

All STAT mode bits, DIV, and other I/O registers match cycle-accurately
between jagoombacolor and mGBA — zero patches needed for those registers.
