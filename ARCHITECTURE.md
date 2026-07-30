# ChromA Architecture

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
Exact figures are printed by `scripts/validate_elf.sh` on every build ("Memory
Validation"), which is the authority; the numbers below drift and are indicative
only.
- **Code (.iwram)**: ~30KB — CPU core, scanline processing, IO handlers
- **BSS (.bss)**: ~1.2KB — gbc_palette, CHR_DECODE table, canaries
- **Stack**: ~0.9KB — grows down from 0x03007FFC
- **WARNING**: Any code added to IWRAM shifts the layout and can break timing-sensitive games

### Emulated GBC Memory
| GBC Address | Mapped To | Notes |
|-------------|-----------|-------|
| 0x0000-0x7FFF | ROM (via memmap_tbl) | Bank-switched by mapper |
| 0x8000-0x9FFF | XGB_VRAM (EWRAM) | Two banks for GBC |
| 0xC000-0xDFFF | XGB_RAM (IWRAM) | Fast access for WRAM |
| 0xE000-0xFDFF | Echo of 0xC000-0xDDFF | See below |
| 0xFF00-0xFF7F | IO handlers (io_write_tbl) | Per-register dispatch |
| 0xFF80-0xFFFE | XGB_HRAM (IWRAM) | High RAM |

`readmem`/`writemem` fold the echo in their handlers, but the *direct memmap
paths* — `push16`/`pop16`/`popAF` (PUSH, POP, CALL, RET, RST) and `encodePC`
(instruction fetch) — index `memmap_tbl` by the top address nibble alone, so
they need the echo built into the table. Entry 14 (0xE000) is the echo of WRAM
bank 0. Entry 15 cannot be: 0xF000-0xFFFF also holds OAM, IO and HRAM, and
SP=0xFFFE plus HRAM-resident code are universal, so entry 15 serves
0xFE00-0xFFFF and those macros range-check 0xF000-0xFDFF against the separate
`echomap` slot (a mirror of entry 13 minus 0x2000, resynced by `_FF70W` on
every SVBK write). Anything else that resolves a guest address through
`memmap_tbl` — `FF46_W`, `dma.c`'s `GetRealAddress`, the game-specific hacks —
still sees entry 15 as OAM/IO/HRAM and does not fold the 0xF000 echo.

The stack macros resolve **each byte's own page**, via the shared
`resolve_page` macro. The two 4K pages either side of a boundary are generally
not adjacent in host memory — 0xCFFF/0xD000 with SVBK≥2 spans XGB_RAM and
GBC_EXRAM, 0xDFFF/0xE000 wraps to the bottom of WRAM, 0x9FFF/0xA000 and
0x7FFF/0x8000 cross into different buffers — so a stack straddling one cannot
share a base between its bytes. `resolve_page` needs only its destination
register as scratch: `and` and `ldr` leave the flags alone, so the echo range
test stays live across the table lookup. Instruction fetch is *not* covered:
`encodePC` resolves once per jump and the fetch pointer then walks forward, so
an instruction whose operands cross a page boundary still reads them through
the page the opcode started in.

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
| `cart.s` | ROM loading, mapper init (MBC0/1/2/3/5 full; MBC7, HuC1/3, MMM01 partial), bank switching |
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
GBC Z80 registers are mapped to dedicated ARM registers for speed. The
authoritative list is the `.req` block in `src/equates.h`:
```
ARM r0-r2 = temp     (scratch)
ARM r3  = gb_flg     (flags; see below)
ARM r4  = gb_a       (accumulator, upper 8 bits)
ARM r5  = gb_bc      (BC pair, upper 16 bits)
ARM r6  = gb_de      (DE pair, upper 16 bits)
ARM r7  = gb_hl      (HL pair, upper 16 bits)
ARM r8  = cycles     (cycle counter + flag bits)
ARM r9  = gb_pc      (program counter — pointer into mapped memory)
ARM r10 = globalptr  (base pointer for IWRAM globals; also gb_optbl)
ARM r11 = gb_sp      (stack pointer, upper 16 bits)
ARM r12 = addy       (scratch register for memory operations)
```

**Only r0-r2 and r12 are scratch.** r3-r11 hold guest state at all times during
interpretation. This matters most in the IO register handlers: `io_read_tbl` and
`io_write_tbl` are entered by a direct `ldr pc,[...]` from the dispatcher with
**no register save**, so using r3 as a temporary inside one silently destroys the
guest's F register. Use `addy` for scratch there — `writemem` already documents
it as clobbered across the whole write path. See issue #95, which was exactly
this mistake in `FF40W_entry`, and `test_roms/test_lcdc_flags.py`, which guards
against its return.

`gb_flg` does not hold the guest F byte in its guest-visible layout. All four
flags live in bits 28-31, in ARM's own NZCV positions with H in the V slot, so
`mrs gb_flg,cpsr` and `msr cpsr_f,gb_flg` move them for free; bits 0-27 are
unused. `encodeFLG`/`decodeFLG` in `gbz80mac.h` convert to and from the packed
F byte the guest sees. A consequence worth knowing when debugging: overwriting
`gb_flg` with any small value or with a pointer leaves bits 28-31 clear, so the
guest reads F back as `$00` — all flags clear — rather than as garbage.

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
- `SINGLE_SPEED` = 456 × CYCLE = 7,296 (cycles per scanline at 4MHz)
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
    At scanline 75: latch `lcdctrl0midframe` (src/timeout.s, line75 hook)
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
- **DMA0**: BG0-BG3 control + scroll registers (6 words of 32 bits = 24 bytes/scanline; control word `0xA6600006`)
- **DMA1**: DISPCNT (one 16-bit halfword = 2 bytes/scanline; control word `0xA2600001`)
- **DMA2**: WIN0H (one 16-bit halfword = 2 bytes/scanline; control word `0xA2600001`)

DISPCNT and WIN0H are 16-bit registers, so a halfword per HBlank is the whole
register — see `do_gba_hdma` in `src/lcd.s`.

These enable per-scanline LCDC changes (scroll, window position, BG enable).

### Per-Scanline Palette (DMA3)
For games that change palettes every scanline (like Hercules GBC):
- **DMA3**: Copies 256 bytes from `pal_dma_buffer` to PALRAM per HBlank
- Buffer filled by `ff69_w_tail` (called from FF69_W on every 32nd palette write)
- Activated when >4 visible-scanline palette writes detected per frame (`src/lcd.s`, `cmp r0,#4` before `pal_hdma_perscanline`)
- See KNOWN_ISSUES.md for limitations

## IO Handling (io.s)

IO registers at 0xFF00-0xFF7F dispatch through `io_write_tbl` / `io_read_tbl`. Key handlers:

| Register | Handler | Notes |
|----------|---------|-------|
| FF00 (JOYP) | `joy0_W/R` | Reads GBA buttons, maps to GBC |
| FF40 (LCDC) | `FF40W_entry` | Screen on/off, tile addressing mode, window/sprite enable |
| FF41 (STAT) | `FF41_R` | LCD mode flags, cycle-position based; bit 7 wired high |
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

The byte FF41 reads back is itself the immediate of the `mov r0,#imm` at
`lcdstat` (and `lcdstat2` for the VBlank reader): the write handlers `strb` into
the instruction stream, and every exit of the `LCD_HACKS` read dispatcher starts
from that value. Bit 7, which is wired high on hardware, therefore lives in the
stored byte rather than being ORed in at each of the dispatcher's many exits.

While the LCD is off, hardware reports mode 0, but the cycle counter keeps
counting. `FF41_repoint_mode_source` (called from `FF40_W`'s tail) patches the
`FF41_modify1` compare to one that can never be taken, so the derived mode bits
are not applied at all and the read falls through with just the stored byte —
whose mode field is cleared at the same time. `updatespeed` re-applies this after
a speed switch, since games switch speed with the LCD off.

## ROM Banking (cart.s)

Mapper detection reads byte 0x147 from the ROM header. Supported mappers:
- **MBC0**: No banking (32KB ROM only)
- **MBC1**: 5-bit ROM bank + 2-bit upper/RAM bank
- **MBC2**: 4-bit ROM bank + 512×4-bit internal RAM
- **MBC3**: 7-bit ROM bank + RTC + 4 RAM banks
- **MBC5**: 9-bit ROM bank + rumble + 16 RAM banks
- **MBC7**: ROM banking only — no accelerometer, no EEPROM save (`MBC7map`/`MBC7RAMB`, src/mappers.s)
- **HuC1/HuC3**: basic banking (HuC3 RTC not emulated)
- **MMM01/MBC4/MBC6**: shared stub — plain 4000-7FFF bank select, no multicart/registers

This list is the canonical one; README.md and COMPATIBILITY.md defer to it, and
`scripts/check_docs.py` fails the build if they diverge from `mappertbl` in
`src/cart.s`.

Bank switching intercepts writes to 0x0000-0x7FFF and updates `memmap_tbl` pointers.

## Build System

### Validation
The build runs two validators before creating the .gba ROM:
1. **Memory constraints** (`scripts/validate_elf.sh`): Checks IWRAM, EWRAM, VRAM1 sizes and stack space
2. **Instruction timing** (`scripts/validate_timing.py`): Verifies all opcode fetch costs against Pan Docs reference

### Test Suite
All tests run headless via `mgba_runner` (custom mGBA wrapper) with `--input`, `--screenshot`, and `--memdump` support.

**Visual regression** (`run_tests.py`): Compiles test ROMs with `goomba_compile.py`, captures screenshots at specific frames, and compares against baseline PNGs. Covers 26 ROMs including CPU instruction tests, game-specific rendering, and SGB border support.

**Menu behavioral tests** (`test_menu.py`): 26 tests covering save states, menu navigation, and all 14 settings. Each setting test verifies actual emulator behavior — not just that menu text pixels changed — using memdump verification of internal state variables and screenshot comparison of gameplay effects across 3 ROMs (SML2, Zelda DX, Kirby DL2).

**SRAM write-through** (`test_sram_writethrough.py`): Multi-session tests verifying save data persists across emulator restarts via `.sav` file reuse.

## Key Design Constraints

1. **IWRAM is at capacity** (~98.7% used). Any code addition shifts the layout, potentially breaking timing-sensitive games. New code should go in `.text` (ROM) or `.vram1` sections.

2. **ARM/GBC cycle ratio** is ~3:1. The GBA ARM CPU needs ~3 cycles to emulate 1 GBC cycle. A full GBC frame takes ~2 GBA frames to process. This prevents 1:1 GBC/GBA frame synchronization.

3. **Per-scanline hooks** in timeout.s must be minimal. The Hercules GBC VBlank handler busy-waits on STAT/LY in tight loops. Even ~70 ARM cycles of hook overhead per scanline disrupts these loops and causes visual artifacts.

4. **DMA channels are fully allocated**: DMA0-2 for per-scanline register updates, DMA3 for per-scanline palette updates. No spare channels available.
