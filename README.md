# ChromA

[![Build & Test](https://github.com/kmatzen/chroma/actions/workflows/test.yml/badge.svg)](https://github.com/kmatzen/chroma/actions/workflows/test.yml)
[![Latest Build](https://img.shields.io/github/v/release/kmatzen/chroma?include_prereleases&label=download&color=brightgreen)](https://github.com/kmatzen/chroma/releases/latest)

A Game Boy / Game Boy Color emulator for Game Boy Advance. Forked from Jagoomba Color by Jaga, which was based on Goomba Color by Dwedit, which was based on Goomba by FluBBa.

### [▶ Try it in your browser](https://kmatzen.com/ChromA/) — drop a .gb/.gbc ROM to play

## Documentation

| Document | What it covers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the emulator is put together: register mapping, the scanline state machine, memory layout, mappers |
| [COMPATIBILITY.md](COMPATIBILITY.md) | What is emulated, what is approximated, and what is not feasible — with the reason for each |
| [KNOWN_ISSUES.md](KNOWN_ISSUES.md) | Open rendering artifacts and the analysis behind them |
| [PROFILING.md](PROFILING.md) | Cycle budgets and where the time goes |
| [Tutorial](https://kmatzen.com/ChromA/tutorial.html) | An illustrated walkthrough of how a GB emulator on GBA hardware works |
| [formal/](formal/) | TLA+ models of the dirty-tile protocol |

The drift-prone figures in these documents (cycle constants, thresholds, mapper
lists, test counts) are checked against the source by
`python3 scripts/check_docs.py`, which runs in CI.

## FAQ

**My in-game saves disappear when I reload the browser demo.**
They no longer should — saves are keyed to the ROM's content hash and persisted
in browser storage. Use the Export .sav button to keep a copy outside the
browser, since clearing site data still erases it.

**The demo page reloads itself once when I first open it.**
It installs a cross-origin-isolation service worker (needed for the WASM
threads mGBA uses) and reloads to pick it up. It happens once per browser.

**How do I open the emulator's own menu (savestates, palettes, settings)?**
Press L+R together — `A` and `S` on the demo page's keyboard mapping.

**Which cartridge mappers work?**
MBC0/1/2/3/5 are fully supported. MBC7 is ROM-banking only (no tilt sensor),
HuC1/HuC3 have basic banking, and MMM01/MBC4/MBC6 share a stub. See
[ARCHITECTURE.md](ARCHITECTURE.md#rom-banking-carts) for the canonical list.

**Audio clicks or sounds slightly wrong.**
Sound is a direct pass-through to the GBA's own PSG hardware rather than
software synthesis, so a handful of DMG-specific quirks follow GBA silicon.
[COMPATIBILITY.md](COMPATIBILITY.md#sound) explains which ones and why.

## License

This project is licensed under the GNU General Public License v2. See [LICENSE](LICENSE) for the full copyright chain and third-party component licenses.

## Features

- Full GB/GBC CPU emulation (all opcodes, cycle-accurate STAT/DIV)
- Per-scanline rendering with mid-frame register tracking
- STAT IRQ blocking (LYC=LY, mode transitions, VBlank entry)
- GBC color palettes, VRAM banking, double-speed mode, HDMA
- SGB border and palette support
- 10 sprites per scanline limit
- MBC1/2/3/5 with SRAM write-through persistence (MBC7/HuC1/HuC3/MMM01 partial — see [ARCHITECTURE.md](ARCHITECTURE.md#rom-banking-carts) for the canonical list)
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
# Run all tests locally (28 visual + 25 menu/behavioral + RST + SRAM)
python3 test_roms/run_all_tests.py

# Quick mode (skip slow SRAM tests)
python3 test_roms/run_all_tests.py --quick

# Hardware-accuracy test ROMs (Mooneye Test Suite + Blargg)
python3 test_roms/fetch_accuracy_roms.py     # one-off, ~3.7 MB pinned download
python3 test_roms/run_accuracy_tests.py
python3 test_roms/run_accuracy_tests.py --list

# Instruction-level trace comparison
make clean && make TRACE=1
make -f test_roms/Makefile.test
# combined.gba = chroma.gba with the guest ROM appended:
python3 test_roms/goomba_compile.py -e chroma.gba -o combined.gba rom.gb
test_roms/trace_compare rom.gb combined.gba --frames 600 --max-insns 5000
```

CI runs on every PR (custom ROM tests) and on every push to main (full suite with game ROMs). Visual regression reports are published to the [test report page](https://kmatzen.com/ChromA/test-report.html).

### Hardware-accuracy suite

`run_accuracy_tests.py` runs the [Mooneye Test Suite](https://github.com/Gekkio/mooneye-test-suite) and [Blargg's test ROMs](https://github.com/retrio/gb-test-roms) from a pinned, SHA-256-verified [gameboy-test-roms](https://github.com/c-sp/gameboy-test-roms) release. These ROMs are freely redistributable, so the suite runs in the public CI job and gates every PR.

Each ROM is rendered twice: once natively on mGBA's own Game Boy core (the reference, committed under `test_roms/baselines/accuracy/`) and once wrapped in `chroma.gba`, then compared pixel-for-pixel over the 160x144 LCD area. Because the reference never comes from ChromA, `--rebaseline` cannot turn current broken output into the new truth.

Current state: **20 pass, 29 expected-fail, 7 not covered**. The expected failures are the open accuracy bugs (#41, #44, #52, #53, #56, #106); they report XFAIL and do not fail the build, but a fix flips one to XPASS, which does — so progress has to be recorded in `accuracy_config.json` rather than going unnoticed. The 7 uncovered ROMs are ones mGBA itself does not pass, so it cannot supply a correct reference; they are listed with reasons under `unusable` and reported on every run.

## Test baselines

The `test_roms/baselines/` directory contains screenshot images captured from commercial Game Boy and Game Boy Color games for automated visual regression testing. These screenshots are used solely for the purpose of verifying emulator correctness. All game content depicted in these images is the property of its respective copyright holders and is not licensed under this project's license.

## Acknowledgments

- **Jaga** (EvilJagaGenius) for creating the Jagoomba Color fork
- **Dwedit** (Dan Weiss) for the Goomba Color emulator: https://www.dwedit.org/gba/goombacolor.php
- **FluBBa** (Fredrik Olsson) for the original Goomba emulator ([archived homepage](https://web.archive.org/web/*/goomba.webpersona.com))
- **Minucce** for help with ASM
- **Sterophonick** for code tweaks and EZ-Flash Omega integration
- **EZ-Flash** for releasing modified Goomba Color source
- **Nuvie** for per-game Game Boy type selection
- **Radimerry** for MGS:Ghost Babel elevator fix, Faceball menu fix, SMLDX SRAM fix
- **Therealteamplayer** for default-to-grayscale for GB games

The browser demo uses [mGBA](https://github.com/mgba-emu/mgba) (MPL-2.0) built to WebAssembly by [@thenick775](https://github.com/thenick775) as part of [gbajs3](https://github.com/thenick775/gbajs3) (BSD-2-Clause).
