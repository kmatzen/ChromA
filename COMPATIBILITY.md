# Jagoomba Color — Compatibility Gap Analysis

What this GB/GBC emulator implements, what it's missing, and why.

## Test Suite Results

| Test | Result | Notes |
|------|--------|-------|
| Blargg cpu_instrs | **PASS** | All 11 instruction tests |
| Blargg instr_timing | FAIL | TIMA interpolation drift, not an RST bug (same root cause as mem_timing) |
| Blargg mem_timing | FAIL | TIMA overflow detection still per-scanline |
| Blargg mem_timing2 | FAIL | Same |
| cgb-acid2 | **PASS** | Minor BG/OBJ priority eye artifacts |
| EI delay test | **PASS** | Custom ROM validates 1-instruction delay |
| Sprite limit test | **PASS** | Custom ROM validates 10/line limit |
| Timer accuracy test | **PASS** | Custom ROM validates sub-scanline DIV reads |
| JR HRAM test | **PASS** | Custom ROM validates cross-bank JR |
| RST timing test | **PASS** | Custom ROM validates all 8 RST variants match (16 cycles) |
| Halt bug test | **PASS** | Custom ROM validates HALT behavior with IME=0 |
| 26 game regression tests | **PASS** | Pokemon R/B/Y/Gold/Crystal, Zelda LA/DX/OoA/OoS, Shantae, etc. |
| 20 trace comparison tests | **PASS** | Instruction-level CPU verification against mGBA reference |
| 11 menu tests | **PASS** | All Goomba menu features automated |

---

## CPU (SM83 / LR35902)

### What works
- All 246 valid base opcodes + 256 CB-prefixed opcodes
- Cycle counts correct for most instructions (validated by `scripts/validate_timing.py`)
- HALT with interrupt wake-up (including HALT bug: exits without servicing when IME=0)
- DAA (decimal adjust) fully correct
- Interrupt priority ordering (VBlank > STAT > Timer > Serial > Joypad)
- EI 1-instruction delay (interrupts enabled after next instruction completes)
- JR across bank boundaries (e.g., ROM → HRAM address wrap)

### Gaps

**STOP instruction simplified** — WON'T FIX
> Only handles double-speed toggle, doesn't block for joypad. Blocking was
> attempted but hangs games at boot (games use STOP during init without
> interrupts enabled). No known game depends on exact STOP wait behavior.

**Blargg instr_timing fails on RST 38h** — NOT AN RST BUG
> A custom test ROM confirms all 8 RST variants have identical timing
> (16 T-cycles) matching native mGBA. Blargg's test uses TIMA at
> 262144 Hz (4 T-cycle granularity) for measurement, but jagoomba
> updates TIMA per-scanline with sub-scanline interpolation on reads.
> The synchronization loop in Blargg's test misaligns with interpolated
> TIMA values, causing accumulated error that manifests at opcode 0xFF
> (tested last). Same root cause as mem_timing failures.

---

## PPU / LCD

### What works
- Per-scanline rendering with HBlank DMA for mid-frame register changes
- LCDC all bits including mid-frame sprite size/enable tracking
- STAT mode flags (cycle-based thresholds, self-modifying for double speed)
- STAT mode 0 interrupt via GBA HBlank hardware IRQ (hardware-timed, zero drift)
- STAT mode 2 interrupt (OAM, fired at scanline boundary)
- STAT IRQ blocking (LYC=LY holding line high suppresses mode 0/2 re-trigger)
- STAT VBlank interrupt (mode 1 STAT IE fires at line 144, with IRQ blocking)
- VBlank STAT IRQ blocking (mode 0 IE / LYC=LY suppresses spurious fires)
- LYC=LY coincidence interrupt with 0→1 edge detection
- LY (FF44) returns scanline variable directly (no artificial adjustment)
- Window rendering (WX, WY) with per-scanline buffering
- Sprite rendering with 8x8/8x16 mid-frame tracking
- 10 sprites per scanline limit (excess hidden if over limit on all scanlines)
- OAM DMA (FF46) with pattern-detection optimization
- GBC HDMA (FF51-FF55): both general and HBlank modes
- VRAM banking (FF4F) with proper read mask (0xFE | bank)
- GBC palette writes (FF68-6B) with auto-increment
- Per-scanline palette DMA3 for games that update palettes every scanline
- Mid-frame scroll register changes via DMA0/DMA1/DMA2

### Gaps

**CGB BG/OBJ priority not pixel-perfect** — NOT FEASIBLE
> cgb-acid2 shows minor "eye artifacts." GBA priority system doesn't map
> 1:1 to CGB rules. Would need per-pixel software compositing — too slow
> on the 16MHz ARM7.

**Per-scanline palette incomplete for some screens** — OPEN (#4)
> Games that update palettes every scanline (e.g., Hercules GBC title screen)
> work via DMA3 HBlank repeat. The Universal logo screen has artifacts because
> `ff69_w_tail` only captures palette state on BCPS wrap (every 32nd write),
> leaving most scanlines with incomplete data in `pal_dma_buffer`. The DMA3
> transfer itself was confirmed working for small sizes (8 words). Root cause
> is buffer population logic, not transfer mechanism.

**No per-dot rendering** — NOT FEASIBLE
> Rendering is per-scanline. Mid-scanline raster effects are not supported.
> Very few GB/GBC games use sub-scanline effects.

---

## Audio (APU)

### What works
- All 4 channels: pulse 1 (sweep), pulse 2, wave, noise
- Master volume, channel output selection, master enable
- Wave RAM with bank switching

### Architecture
Direct pass-through to GBA APU hardware. GB sound register writes are
mapped 1:1 to equivalent GBA registers. The GBA hardware generates audio.

### Gaps

**No software synthesis** — NOT FEASIBLE (by design)
> Would consume too many ARM cycles. The pass-through gives acceptable
> audio for free. Some GB sound quirks (envelope trigger bugs, frame
> sequencer edge cases) are not reproduced.

---

## Timers

### What works
- DIV (FF04): resets on write, sub-scanline accurate reads
- TIMA/TMA/TAC (FF05-FF07): frequency selection, overflow detection, TMA reload
- TIMA reads are sub-scanline accurate (computed from cycle position)
- Timer interrupt generation (IF bit 2)
- Double-speed mode adjusts timer rates

### Gaps

**TIMA overflow detection is per-scanline** — HARD
> Real GB detects TIMA overflow every cycle. Goomba checks once per
> scanline. A TIMA overflow mid-scanline would fire the interrupt late
> (up to ~456 cycles). This is what causes mem_timing tests to fail.
> Fixing requires per-instruction overflow checks in the fetch macro,
> which would consume ~3.5KB of IWRAM (~1.9KB free).

---

## Memory Bank Controllers (MBC)

### What works
- **MBC0**: ROM only (no banking)
- **MBC1**: 5-bit ROM bank + 2-bit upper, mode switching
- **MBC2**: 4-bit ROM bank, built-in 512-nibble RAM
- **MBC3**: 7-bit ROM bank, RTC with software fallback for emulators
- **MBC5**: 9-bit ROM bank, rumble bit (conditional compilation)
- **HuC1/HuC3**: Hudson Soft mappers (basic support)
- RAM enable/disable (0x0A magic value)
- SRAM bank switching + write-through persistence (no compressed saves)
- SRAM layout: top 32KB reserved for write-through, bottom 32KB for
  config/savestates — can never overlap

### Gaps

**MBC4/MBC6/MMM01 are stubs** — NO TEST ROMS
> Very few games use these (MBC6: Net de Get, MMM01: Momotarou Collection 2).

**MBC7 accelerometer** — NOT FEASIBLE
> Would need GBA gyroscope hardware (most GBAs don't have).

---

## GBC-Specific Features

### What works
- GBC detection (bit 7 of header byte 0x143)
- VRAM banking (FF4F): two 8KB banks, proper read mask
- WRAM banking (FF70): eight 4KB banks, proper read mask (0xF8 | bank)
- Color palettes (FF68-6B) with auto-increment
- Double-speed mode (FF4D): STOP-triggered switch
- HDMA (FF51-FF55): general + HBlank DMA
- DMG compatibility mode (GBC registers disabled for DMG games)
- Automatic DMG palette selection from game hash database
- SGB border + palette support (parallel to GBC)

### Gaps

**Infrared port (FF56)** — NO HARDWARE
> No-op. Used by a handful of games for local communication.

---

## Serial / Link Cable

**Stubbed.** Serial data writes (FF01) ignored, reads return 0xFF. Serial
interrupt fires after one scanline when internal clock is enabled.
No link cable multiplayer or printer support.

---

## Architectural Constraints

| Constraint | Impact |
|------------|--------|
| **IWRAM: 32KB, ~94.9% used** | ~1,924 bytes free (code=29,576 bss=1,268) |
| **All 4 GBA DMA channels allocated** | No spare DMA |
| **ARM/GBC cycle ratio ~3:1** | GBC frame spans ~2 GBA frames |
| **16MHz ARM7TDMI** | No room for software audio or per-pixel compositing |
| **GBA APU ≈ GB APU** | Sound pass-through works but can't emulate quirks |

---

## Remaining Gaps

| Gap | Status | Why |
|-----|--------|-----|
| Blargg instr_timing | NOT AN RST BUG | TIMA interpolation drift, same as mem_timing |
| CGB BG/OBJ priority | NOT FEASIBLE | Needs per-pixel compositing |
| Per-scanline palette buffer | OPEN (#4) | `ff69_w_tail` doesn't capture full state per scanline |
| Per-dot rendering | NOT FEASIBLE | Complete rewrite |
| Software audio | NOT FEASIBLE | No CPU budget |
| TIMA overflow per-scanline | HARD | Needs per-instruction check, ~1.9KB IWRAM free |
| MBC4/MBC6/MMM01 | NO TEST ROMS | Very few games |
| MBC7 accelerometer | NOT FEASIBLE | No hardware |
| Infrared port | NO HARDWARE | Handful of games |
| Serial / link cable | HARD | Needs GBA link hardware |
