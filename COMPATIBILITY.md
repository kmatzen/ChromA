# Jagoomba Color — Compatibility Gap Analysis

What this GB/GBC emulator implements, what it's missing, and why.

## Test Suite Results

| Test | Result | Notes |
|------|--------|-------|
| Blargg cpu_instrs | **PASS** | All 11 instruction tests |
| Blargg instr_timing | FAIL | RST 38h timing (cause unclear) |
| Blargg mem_timing | FAIL | TIMA overflow detection still per-scanline |
| Blargg mem_timing2 | FAIL | Same |
| cgb-acid2 | **PASS** | Minor BG/OBJ priority eye artifacts |
| EI delay test | **PASS** | Custom ROM validates 1-instruction delay |
| Sprite limit test | **PASS** | Custom ROM validates 10/line limit |
| Timer accuracy test | **PASS** | Custom ROM validates sub-scanline DIV reads |
| JR HRAM test | **PASS** | Custom ROM validates cross-bank JR |
| 16 game regression tests | **PASS** | Crystal, Shantae, Zelda DX, Kirby, etc. |

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

**RST 38h timing** — UNCLEAR
> Blargg's instr_timing test fails on RST 38h. The instruction uses
> `fetch 16` which matches documentation. No test ROM available to
> investigate. May be a cycle-counting methodology difference.

---

## PPU / LCD

### What works
- Per-scanline rendering with HBlank DMA for mid-frame register changes
- LCDC all bits including mid-frame sprite size/enable tracking
- STAT mode flags (cycle-based thresholds, self-modifying for double speed)
- LYC=LY coincidence interrupt with 0→1 edge detection
- LY (FF44) sub-scanline correction (+1 when near scanline boundary)
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

**STAT mode 0/2 interrupts disabled** — UNCLEAR
> HBlank and OAM mode-change interrupt code is disabled (`#if 0` in lcd.s).
> Only LYC=LY and VBlank STAT interrupts are active. Most games use VBlank
> and LYC, not mode 0/2 interrupts.

**Per-scanline palette flicker** — NOT FEASIBLE
> Games that update palettes every scanline (e.g., Hercules GBC) get
> half-stale data because a GBC frame spans ~2 GBA frames. 11 mitigation
> strategies attempted. Root cause is the fundamental 3:1 ARM/GBC cycle ratio.

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
> which would consume ~3.5KB of IWRAM (only ~800 bytes free).

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
| **IWRAM: 32KB, ~97.5% used** | ~800 bytes free for new code |
| **All 4 GBA DMA channels allocated** | No spare DMA |
| **ARM/GBC cycle ratio ~3:1** | GBC frame spans ~2 GBA frames |
| **16MHz ARM7TDMI** | No room for software audio or per-pixel compositing |
| **GBA APU ≈ GB APU** | Sound pass-through works but can't emulate quirks |

---

## Remaining Gaps

| Gap | Status | Why |
|-----|--------|-----|
| RST 38h timing | UNCLEAR | No test ROM, may not be a real bug |
| CGB BG/OBJ priority | NOT FEASIBLE | Needs per-pixel compositing |
| STAT mode 0/2 interrupts | UNCLEAR | Disabled intentionally, low impact |
| Per-scanline palette desync | NOT FEASIBLE | Fundamental cycle ratio |
| Per-dot rendering | NOT FEASIBLE | Complete rewrite |
| Software audio | NOT FEASIBLE | No CPU budget |
| TIMA overflow per-scanline | HARD | Needs per-instruction check, no IWRAM |
| MBC4/MBC6/MMM01 | NO TEST ROMS | Very few games |
| MBC7 accelerometer | NOT FEASIBLE | No hardware |
| Infrared port | NO HARDWARE | Handful of games |
| Serial / link cable | HARD | Needs GBA link hardware |
