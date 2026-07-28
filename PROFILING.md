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

The GBA HBlank hardware interrupt was tested for mode 0 STAT
IRQ timing (PR #49, later reverted in PR #53). It fired at the exact GBA HBlank boundary with
zero drift. The handler saves/restores r0-r3 on the IRQ stack (since
r3=gb_flg is live during GB execution). However, the 228 IRQ entries
per frame added ~17,000 ARM cycles of overhead, which corrupted
Crystalis rendering. The approach was reverted — mode 0 STAT IRQ
returned to scanline-boundary timing.

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

~73% of instructions match exactly. The remaining ~27% are LY (FF44)
reads that return different values due to different frame-start
positions (ChromA starts at LY=0, mGBA at LY≈145). The tool handles
these via I/O patching and state resyncs.

An earlier version of this section read "Results across 20 ROMs: all
pass." That claim was not evidence of anything: every divergence case
in the comparison loop force-synced the reference core to ChromA's
state and continued, so the tool returned 0 unconditionally and would
have reported "all pass" against an arbitrarily broken emulator. It now
budgets those resyncs and fails when they are exceeded (see #58).

Resyncs are reported in three buckets, which behave very differently:

- **code-path** (PC diverged, SP agreed) is the noisy bucket. Commercial
  ROMs boot into a VBlank poll loop, and a patched LY read routinely
  sends the two cores down different branches — POKEMON RED resyncs this
  way 2.3% of the time on a good build.
- **register-only** (PC and SP agreed, a value did not) is the
  meaningful one: it means ChromA computed something different, and the
  I/O patch list does not explain it. Good builds produce 0–1 of these
  on every ROM measured.
- **call-stack** (SP diverged) means the traces are no longer running
  the same program. A few occur legitimately from interrupt-timing
  differences (POKEMON PINBALL hits 2).

Not every ROM is comparable. `ei_delay_test` and
`ei_dispatch_window_test` spend most of their run resynced (the latter
92% of instructions), and `invalid_opcode_test` diverges by design,
since undefined-opcode behaviour is not something mGBA and ChromA agree
on. These exceed the default budgets on a *good* build — which is the
tool correctly reporting that it could not verify much, rather than the
old silent PASS. Use `--max-resync-rate` / `--max-window-resyncs` /
`--max-state-resyncs` to set a threshold appropriate to the ROM.

All STAT mode bits, DIV, and other I/O registers match cycle-accurately
between ChromA and mGBA — zero patches needed for those registers.
