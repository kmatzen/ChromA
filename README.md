# ChromA

A Game Boy / Game Boy Color emulator for Game Boy Advance. Forked from Jagoomba Color by Jaga, which was based on Goomba Color by Dwedit, which was based on Goomba by FluBBa.

## License

This project is licensed under the GNU General Public License v2. See [LICENSE](LICENSE).

## Features

- Full GB/GBC CPU emulation (all opcodes, cycle-accurate STAT/DIV)
- Per-scanline rendering with mid-frame register tracking
- Mode 0 STAT IRQ via GBA HBlank hardware interrupt (zero-drift timing)
- STAT IRQ blocking (LYC=LY, mode transitions)
- GBC color palettes, VRAM banking, double-speed mode, HDMA
- SGB border and palette support
- 10 sprites per scanline limit
- MBC1/2/3/5 with SRAM write-through persistence
- MBC3 software RTC fallback
- Instruction-level CPU trace comparison framework (TRACE=1 build)

## Building

```bash
# Install DevkitPro GBA tools, then:
make
# Rename font.lz77.o to font.o and fontpal.bin.o to fontpal.o
make
```

Output: `chroma.gba`

## Testing

```bash
# Visual regression tests (26 ROMs)
python3 test_roms/run_tests.py

# Instruction-level trace comparison (20 ROMs)
make clean && make TRACE=1
make -f test_roms/Makefile.test
# Then run trace_compare per ROM
```

## Acknowledgments

- **Jaga** (EvilJagaGenius) for creating the Jagoomba Color fork: https://github.com/EvilJagaGenius/jagern
- **Dwedit** (Dan Weiss) for the Goomba Color emulator: https://www.dwedit.org/gba/goombacolor.php
- **FluBBa** (Fredrik Olsson) for the original Goomba emulator: http://goomba.webpersona.com/
- **Minucce** for help with ASM
- **Sterophonick** for code tweaks and EZ-Flash Omega integration
- **EZ-Flash** for releasing modified Goomba Color source
- **Nuvie** for per-game Game Boy type selection
- **Radimerry** for MGS:Ghost Babel elevator fix, Faceball menu fix, SMLDX SRAM fix
- **Therealteamplayer** for default-to-grayscale for GB games
