# Jagoomba Color Architecture

A Game Boy / Game Boy Color emulator running on Game Boy Advance hardware. Based on Goomba Color by Dwedit, which was based on Goomba by FluBBa.

## Overview

The emulator runs GBC games on GBA by:
1. Emulating the Z80 CPU in ARM assembly (IWRAM for speed)
2. Converting 2bpp GBC tiles to 4bpp GBA tiles on-the-fly
3. Mapping GBC palettes to GBA PALRAM
4. Using GBA HBlank DMA for per-scanline display register updates

## Memory Layout

### GBA Memory Regions
| Region | Address | Size | Usage |
|--------|---------|------|-------|
| IWRAM | 0x03000000 | 32KB | CPU core, hot-path code, GBC WRAM/HRAM, opcode tables |
| EWRAM | 0x02000000 | 256KB | GBC VRAM/SRAM, palette buffers, DMA buffers, ROM cache |
| VRAM | 0x06000000 | 96KB | GBA tiles, tilemaps, UI, border graphics |
| PALRAM | 0x05000000 | 1KB | GBA palettes (GBC palettes mapped to slots 8-15) |
| ROM | 0x08000000+ | varies | Emulator code (.text) + embedded GBC ROM images |

### IWRAM Budget (critical — 32KB total)
- **Code (.iwram)**: ~31KB — CPU core, scanline processing, IO handlers
- **BSS (.bss)**: ~1.2KB — gbc_palette, CHR_DECODE table, canaries
- **Stack**: ~430 bytes — grows down from 0x03007FFC
- **WARNING**: Any code added to IWRAM shifts the layout and can break timing-sensitive games

### Emulated GBC Memory
| GBC Address | Mapped To | Notes |
|-------------|-----------|-------|
| 0x0000-0x7FFF | ROM (via memmap_tbl) | Bank-switched by mapper |
| 0x8000-0x9FFF | XGB_VRAM (EWRAM) | Two banks for GBC |
| 0xC000-0xDFFF | XGB_RAM (IWRAM) | Fast access for WRAM |
| 0xFF00-0xFF7F | IO handlers (io_write_tbl) | Per-register dispatch |
| 0xFF80-0xFFFE | XGB_HRAM (IWRAM) | High RAM |

## Source Files

### Core Emulation
| File | Section | Description |
|------|---------|-------------|
| `gbz80.s` | IWRAM | Z80 CPU fetch/decode/execute loop, opcode handlers |
| `gbz80mac.h` | — | Macros for ALU ops, memory access, flag manipulation |
| `timeout.s` | IWRAM | Scanline state machine (line0 → line153), interrupt timing |
| `lcd.s` | IWRAM + .text | Tile rendering, palette transfer, DMA setup, VCount handlers |
| `io.s` | IWRAM | IO register read/write dispatch (FF00-FFFF) |
| `dma.c` | .vram1 | GBC HDMA packet management, tile dirty tracking |
| `sound.s` | IWRAM | Audio channel emulation |

### ROM & Save
| File | Description |
|------|-------------|
| `cart.s` | ROM loading, mapper init (MBC1-MBC7), bank switching |
| `savestate.c` | Tagged-section state serialization |
| `sram.c` | SRAM management, save/load menu, LZO compression |
| `cache.c` | ROM instant-page caching |

### Support
| File | Description |
|------|-------------|
| `sgb.s` | Super Game Boy border, palette multiplexing |
| `gbpalettes.s` | Default DMG palette data |
| `gamespecific.s` | Per-game quirks and workarounds |
| `speedhack.c` | Instruction pattern detection for speed optimization |
| `main.c` | Entry point, ROM menu, game launch |
| `ui.c` | Settings menu, palette control |

## CPU Emulation (gbz80.s)

### Register Mapping
GBC Z80 registers are mapped to dedicated ARM registers for speed:
```
ARM r4  = gb_a       (accumulator, upper 8 bits)
ARM r5  = gb_flg     (flags: Z, N, H, C)
ARM r6  = gb_bc      (BC pair, upper 16 bits)
ARM r7  = gb_de      (DE pair, upper 16 bits)
ARM r8  = gb_hl      (HL pair, upper 16 bits)
ARM r9  = gb_pc      (program counter — pointer into mapped memory)
ARM r10 = globalptr  (base pointer for IWRAM globals)
ARM r11 = gb_sp      (stack pointer, upper 16 bits)
ARM r12 = addy       (scratch register for memory operations)
ARM r3  = cycles     (cycle counter + flag bits)
```

### Fetch/Execute Cycle
```
fetch N:
    sub cycles, cycles, #N*CYCLE    ; charge N cycles
    ldrb opcode, [gb_pc], #1        ; load opcode, advance PC
    ldr pc, [r10, opcode, lsl#2]    ; jump to handler via op_table
```

The cycle counter decrements. When it reaches 0, the current scanline ends and the timeout handler (timeout.s) runs.

### Cycle Constants
- `CYCLE` = 16 (internal units per GBC clock cycle)
- `SINGLE_SPEED` = 456 × CYCLE = 7,280 (cycles per scanline at 4MHz)
- `DOUBLE_SPEED` = 912 × CYCLE = 14,592 (cycles per scanline at 8MHz)

### Memory Access
Memory reads/writes dispatch through `readmem_tbl` / `writemem_tbl` — 16-entry tables indexed by address bits 12-15. Each entry is a function pointer to the appropriate handler (ROM read, VRAM write, IO handler, etc.).

## Scanline Processing (timeout.s)

The emulator processes GBC scanlines in a state machine:

```
line0x (VBlank start):
    Reset scanline counter
    Refresh input, update speed settings
    Restore CPU state
    → line1_to_71

line1_to_71:
    Process scanlines 1-75
    At scanline 75: mid-frame palette copy (copy_gbc_palette)
    → line72_to_143

line72_to_143:
    Process scanlines 76-143
    → line144

line144 (VBlank trigger):
    Set VBlank interrupt flag
    Render sprites, consume dirty tiles
    Set up GBA display (transfer_palette_, pal_hdma_wrapper)
    Swap double buffers
    → line145_to_end

line145_to_end:
    Process scanlines 145-153
    Increment frame counter
    → line0x (next frame)
```

Each section calls `scanlinehook` which runs the Z80 CPU until the cycle budget for one scanline is exhausted.

### Per-Scanline Hook
Between scanlines, the hook at `noScanlineIRQ` runs. This handles:
- LY==LYC coincidence check
- STAT interrupt triggering
- HBlank interrupt
- Mid-frame palette tracking (currently bypassed for timing — see KNOWN_ISSUES.md)

**Critical constraint**: Any code added to this hook steals ARM cycles from the Z80 emulation. Games with tight timing loops (like Hercules GBC's per-scanline VBlank handler) are extremely sensitive to this overhead.

## Rendering Pipeline (lcd.s)

### Tile Conversion (2bpp → 4bpp)
GBC tiles are 2 bits per pixel (16 bytes per 8×8 tile). GBA requires 4bpp (32 bytes per tile). The `CHR_DECODE` lookup table (1KB, IWRAM) converts one byte of 2bpp data to 4bpp in a single load.

Tile conversion happens via dirty tracking:
1. GBC writes to VRAM mark tiles dirty in `DIRTY_TILE_BITS`
2. At VBlank, `render_dirty_tiles` converts dirty 2bpp tiles to 4bpp in GBA VRAM
3. GBA hardware displays the 4bpp tiles

### Tile Map Conversion
GBC BG map entries (tile number + attributes) are converted to GBA tilemap format:
- Tile number: GBC 8-bit → GBA 10-bit (bank bit adds 256)
- Palette: GBC 3-bit (0-7) → GBA 4-bit (8-15, offset by 8)
- Flip flags: mapped directly

### Palette Transfer
`transfer_palette_` copies `gbc_palette2` (128 bytes) to GBA PALRAM:
- BG palettes 0-7 → GBA palette slots 8-15 (at PALRAM+0x100)
- OBJ palettes 0-7 → GBA palette slots 0-7 (at PALRAM+0x200)
- Optional gamma correction via `gammaconvert`

### Per-Scanline Display (HBlank DMA)
Three GBA DMA channels update registers every HBlank:
- **DMA0**: BG0-BG3 control + scroll registers (24 bytes/scanline)
- **DMA1**: DISPCNT (2 bytes/scanline)
- **DMA2**: WIN0H (2 bytes/scanline)

These enable per-scanline LCDC changes (scroll, window position, BG enable).

### Per-Scanline Palette (DMA3)
For games that change palettes every scanline (like Hercules GBC):
- **DMA3**: Copies 256 bytes from `pal_dma_buffer` to PALRAM per HBlank
- Buffer filled by `ff69_w_tail` (called from FF69_W on every 32nd palette write)
- Activated when >10 visible-scanline palette writes detected per frame
- See KNOWN_ISSUES.md for limitations

## IO Handling (io.s)

IO registers at 0xFF00-0xFF7F dispatch through `io_write_tbl` / `io_read_tbl`. Key handlers:

| Register | Handler | Notes |
|----------|---------|-------|
| FF00 (JOYP) | `joy0_W/R` | Reads GBA buttons, maps to GBC |
| FF40 (LCDC) | `FF40W_entry` | Screen on/off, tile addressing mode, window/sprite enable |
| FF41 (STAT) | `FF41_R` | LCD mode flags, cycle-position based |
| FF44 (LY) | `FF44_R` | Returns current scanline from emulator's counter |
| FF46 (DMA) | `FF46_W` | OAM DMA transfer |
| FF4D (KEY1) | `FF4D_R/W` | GBC double speed switch |
| FF4F (VBK) | `FF4F_W` | VRAM bank select, updates memmap_tbl |
| FF55 (HDMA) | `FF55_W` | GBC HDMA — transfers 16 bytes per HBlank |
| FF68-6B | `FF69_W` etc | GBC palette writes to gbc_palette buffer |
| FF70 (SVBK) | `FF70_W` | WRAM bank select |

### STAT Mode Timing
FF41 returns the LCD mode based on remaining cycles in the current scanline:
- **Mode 2** (OAM search): first 80 dots
- **Mode 3** (transfer): next 172 dots
- **Mode 0** (HBlank): remaining 204 dots
- **Mode 1** (VBlank): scanlines 144-153

Thresholds are adjusted for double-speed mode via self-modifying code (`FF41_modifydata`).

## ROM Banking (cart.s)

Mapper detection reads byte 0x147 from the ROM header. Supported mappers:
- **MBC0**: No banking (32KB ROM only)
- **MBC1**: 5-bit ROM bank + 2-bit upper/RAM bank
- **MBC2**: 4-bit ROM bank + 512×4-bit internal RAM
- **MBC3**: 7-bit ROM bank + RTC + 4 RAM banks
- **MBC5**: 9-bit ROM bank + rumble + 16 RAM banks
- **MBC7**: Accelerometer/tilt sensor

Bank switching intercepts writes to 0x0000-0x7FFF and updates `memmap_tbl` pointers.

## Build System

### Validation
The build runs two validators before creating the .gba ROM:
1. **Memory constraints** (`scripts/validate_elf.sh`): Checks IWRAM, EWRAM, VRAM1 sizes and stack space
2. **Instruction timing** (`scripts/validate_timing.py`): Verifies all opcode fetch costs against Pan Docs reference

### Test Suite
`test_roms/run_tests.py` runs visual regression tests:
- Compiles test ROMs with `goomba_compile.py`
- Runs headless via `mgba_runner` (custom mGBA wrapper)
- Captures screenshots at specific frames
- Compares against baseline PNGs

## Key Design Constraints

1. **IWRAM is at capacity** (~98.7% used). Any code addition shifts the layout, potentially breaking timing-sensitive games. New code should go in `.text` (ROM) or `.vram1` sections.

2. **ARM/GBC cycle ratio** is ~3:1. The GBA ARM CPU needs ~3 cycles to emulate 1 GBC cycle. A full GBC frame takes ~2 GBA frames to process. This prevents 1:1 GBC/GBA frame synchronization.

3. **Per-scanline hooks** in timeout.s must be minimal. The Hercules GBC VBlank handler busy-waits on STAT/LY in tight loops. Even ~70 ARM cycles of hook overhead per scanline disrupts these loops and causes visual artifacts.

4. **DMA channels are fully allocated**: DMA0-2 for per-scanline register updates, DMA3 for per-scanline palette updates. No spare channels available.
