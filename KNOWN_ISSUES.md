# Known Issues

## Per-scanline palette rendering (Hercules GBC title screen)

**Status**: Root cause identified, DMA3 implementation attempted but caused regressions

**Affected games**: Hercules: The Legendary Journeys (GBC), and potentially any GBC game using per-scanline palette updates (common for title screens, cutscenes, gradient effects).

### Symptom

The Hercules GBC title screen shows a dark, low-color approximation instead of the full-color character portrait visible on real hardware. The BG tiles are correct but all scanlines display the same palette instead of unique per-scanline palettes.

### Root cause

The game's VBlank handler at ROM `0x0DA2` rewrites all 8 BG palettes (32 bytes via FF69/BCPD) during every HBlank for scanlines 0-142. This produces 143 unique palette states per frame, creating a full-color image from 2bpp tiles. The emulator's palette split mechanism (VCount interrupt chaining) only supports up to 8 mid-frame palette changes.

### Why simple fixes don't work

- **Increasing to 144 VCount splits**: Causes black screen from interrupt overhead (~11% of GBA frame time) and regressions in other games due to VBlank palette setup being incorrectly captured as mid-frame splits.
- **The `pal_split_count_screen` init bug**: The screen count was zeroed at each frame start, preventing VCount activation. Fixing this caused regressions because the split detection was too aggressive (capturing normal VBlank palette changes as splits).

### Proposed fix: HBlank DMA via GBA DMA channel 3

GBA DMA3 is unused during display and could be configured for HBlank-repeat palette updates:

1. **Detection**: When `pal_split_count` exceeds a threshold (e.g., >16), switch to DMA3 mode instead of VCount chaining
2. **Buffer**: Build a 144 x 256 byte buffer in EWRAM during GBC frame processing, capturing palette state at each scanline boundary
3. **DMA3 setup**: In `pal_hdma_wrapper`, configure DMA3: source=buffer, dest=`PALETTE_BASE+0x100`, count=128 halfwords, mode=HBlank repeat
4. **Cleanup**: Disable DMA3 at end of visible area in `end_gba_hdma`

Estimated overhead: ~17% of GBA frame time when active (buffer conversion + DMA).

### Key constraints

- Must distinguish per-scanline mode (>16 splits) from normal 1-8 splits
- Must exclude VBlank scanlines (144-153) from capture to avoid false positives
- Buffer must be double-buffered
- Gamma correction must be applied to the buffer when `_gammavalue != 0`

### Implementation attempt notes

A DMA3 implementation was attempted with:
- 36KB per-scanline PALRAM buffer in EWRAM (144 × 256 bytes)
- Per-scanline capture in the scanline hook (expanding gbc_palette to PALRAM format)
- DMA3 HBlank repeat setup when >16 palette dirty events detected per frame
- Separate `end_gba_hdma_dma3` handler to stop DMA3 at end of visible area

Issues encountered:
- **`pal_split_count_screen` init bug**: The VBlank init zeros `pal_split_count_screen`, which prevents the existing VCount handler from ever activating. Removing the zero causes massive regressions because ALL games have palette changes during VBlank that get captured as false mid-frame splits.
- **Scanline hook ordering**: Adding the DMA capture code and dirty_count tracking to the scanline hook broke register usage or control flow in a way that caused Crystal and other games to show only gray. The exact cause needs more investigation.
- **Mode detection threshold**: Even with visible-area-only dirty counting (scanlines 8-143), the threshold for DMA3 activation needs careful tuning to avoid false positives.

The core challenge is that the scanline hook is in the critical path — any register clobber or control flow change affects all games. The DMA3 code path should be developed on a feature branch with per-change regression testing.

### ROM analysis details

- VBlank dispatch: FFB7=0x0B -> table at `0x0C5C` -> handler `0x0DA2`
- Display config table at `0x2D8C`: both CC5E=0 and CC5E=1 entries write the same BG map (`80,81,82...`); the visual difference comes entirely from per-scanline palette data
- Palette data source: WRAM `0xC900`, loaded by `0x2CD8`, read via POP during the VBlank handler
- Handler timing: BCPS=0x80 (auto-increment), writes 32 bytes/scanline to FF69, checks `bit 1,[FF41]` for HBlank and `[FF44]==0x8E` for end of visible area
- The palette copy (5800 bytes to `0xC900`) intentionally overwrites game state at `0xCC5E`
