# ChromA

[![Build & Test](https://github.com/kmatzen/chroma/actions/workflows/test.yml/badge.svg)](https://github.com/kmatzen/chroma/actions/workflows/test.yml)
[![Latest Build](https://img.shields.io/github/v/release/kmatzen/chroma?label=download&color=brightgreen)](https://github.com/kmatzen/chroma/releases/latest)

A Game Boy / Game Boy Color emulator for Game Boy Advance. Forked from Jagoomba Color by Jaga, which was based on Goomba Color by Dwedit, which was based on Goomba by FluBBa.

### [▶ Try it in your browser](https://kmatzen.github.io/chroma/) — drop a .gb/.gbc ROM to play

## License

This project is licensed under the GNU General Public License v2. See [LICENSE](LICENSE) for the full copyright chain and third-party component licenses.

## Features

- Full GB/GBC CPU emulation (all opcodes, cycle-accurate STAT/DIV)
- Per-scanline rendering with mid-frame register tracking
- STAT IRQ blocking (LYC=LY, mode transitions, VBlank entry)
- GBC color palettes, VRAM banking, double-speed mode, HDMA
- SGB border and palette support
- 10 sprites per scanline limit
- MBC1/2/3/5 with SRAM write-through persistence
- MBC3 software RTC fallback
- Savestate support with RLE compression
- Browser demo via mGBA WASM

## Building

```bash
# Install DevkitPro GBA tools, then:
make
```

Output: `chroma.gba`

## Testing

```bash
# Run all tests locally (26 visual + 26 menu/savestate + RST + SRAM)
python3 test_roms/run_all_tests.py

# Quick mode (skip slow SRAM tests)
python3 test_roms/run_all_tests.py --quick

# Instruction-level trace comparison (20 ROMs)
make clean && make TRACE=1
make -f test_roms/Makefile.test
test_roms/trace_compare rom.gb combined.gba --frames 600 --max-insns 5000
```

CI runs on every PR (custom ROM tests) and on every push to main (full suite with game ROMs). Visual regression reports are published to the [test report page](https://kmatzen.github.io/chroma/test-report.html).

## Test baselines

The `test_roms/baselines/` directory contains screenshot images captured from commercial Game Boy and Game Boy Color games for automated visual regression testing. These screenshots are used solely for the purpose of verifying emulator correctness. All game content depicted in these images is the property of its respective copyright holders and is not licensed under this project's license.

## Acknowledgments

- **Jaga** (EvilJagaGenius) for creating the Jagoomba Color fork
- **Dwedit** (Dan Weiss) for the Goomba Color emulator: https://www.dwedit.org/gba/goombacolor.php
- **FluBBa** (Fredrik Olsson) for the original Goomba emulator: http://goomba.webpersona.com/
- **Minucce** for help with ASM
- **Sterophonick** for code tweaks and EZ-Flash Omega integration
- **EZ-Flash** for releasing modified Goomba Color source
- **Nuvie** for per-game Game Boy type selection
- **Radimerry** for MGS:Ghost Babel elevator fix, Faceball menu fix, SMLDX SRAM fix
- **Therealteamplayer** for default-to-grayscale for GB games

The browser demo uses [mGBA](https://github.com/mgba-emu/mgba) (MPL-2.0) via [@thenick775/mgba-wasm](https://github.com/thenick775/mgba-wasm) (BSD-2-Clause).
