#!/usr/bin/env python3
"""Resolve emulator symbol addresses from build/chroma.elf.map.

The behavioural tests poke emulator globals directly (via mgba_runner's
--memdump), so every address they use has to track the current build.  They
used to carry a hardcoded default per symbol and fall back to it whenever the
map file was missing -- which silently turned a layout change into a test that
dumps unrelated memory and reports a behavioural result about it.  The CI
workflow comment records the outcome: 12 of 13 defaults were wrong at once.

There is no safe default for an address, so there are none here: if the map is
absent or a symbol is missing from it, that is an error.  CI downloads
build/chroma.elf.map as an artifact before running these suites (see the
"Download ELF map" step in .github/workflows/test.yml); locally it is produced
by `make`.
"""

import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
MAP_FILE = PROJECT_DIR / "build" / "chroma.elf.map"
EQUATES_FILE = PROJECT_DIR / "src" / "equates.h"

# XGB_SRAM is an assembler equate, not a symbol the linker places:
#   src/equates.h:  MEM_END = 0x02040000
#                   Next    = MEM_END
#                   XGB_SRAM = Next-0x8000
# ld only lists what it allocates, so XGB_SRAM never appears in the map no
# matter that cart.s declares it .global -- looking for it there just fails.
# Derive it the way the assembly does, and cross-check MEM_END against the
# ewram region the linker actually built so the two cannot drift silently.
XGB_SRAM_OFFSET_BELOW_MEM_END = 0x8000
EWRAM_END_SYMBOL = "__eheap_end"


class SymbolError(RuntimeError):
    """The map file is unusable, or a requested symbol is not in it."""


_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_map(text):
    """Extract {symbol: address} from GNU ld map output.

    Symbol definitions appear as an address followed by a name, e.g.
        0x00000000030038cc                joycfg
    Linker-computed symbols carry their expression too, which still counts:
        0x0000000002040000                __eheap_end = (ORIGIN (ewram) + ...)
    First definition wins, matching the order ld emits them in.
    """
    symbols = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        addr, name = parts[0], parts[1]
        if not addr.startswith("0x") or not _IDENT.match(name):
            continue
        try:
            value = int(addr, 16)
        except ValueError:
            continue
        symbols.setdefault(name, value)
    return symbols


def load_symbols(names, map_file=None):
    """Return {name: address} for every requested symbol, or raise.

    Raises SymbolError if the map file is missing/empty or any name is absent,
    rather than substituting a default that may no longer be correct.
    """
    path = Path(map_file) if map_file is not None else MAP_FILE
    if not path.exists():
        raise SymbolError(
            f"ELF map not found at {path}.\n"
            "  These tests read emulator globals at addresses taken from the\n"
            "  map, so they cannot run without it. Build with `make` (which\n"
            "  writes build/chroma.elf.map), or download the chroma.elf.map\n"
            "  CI artifact into build/."
        )

    symbols = parse_map(path.read_text())
    if not symbols:
        raise SymbolError(
            f"No symbol definitions parsed from {path} -- the map format "
            "changed, or the file is truncated."
        )

    resolved = {}
    missing = []
    for name in names:
        if name in symbols:
            resolved[name] = symbols[name]
        else:
            missing.append(name)
    if missing:
        raise SymbolError(
            f"Symbols absent from {path}: {', '.join(sorted(missing))}.\n"
            f"  ({len(symbols)} symbols were parsed, so the map itself looks "
            "readable -- these were most likely renamed or optimised out.)"
        )
    return resolved


def parse_mem_end(equates_file=None):
    """Read MEM_END from src/equates.h, the assembly's own definition."""
    path = Path(equates_file) if equates_file is not None else EQUATES_FILE
    if not path.exists():
        raise SymbolError(f"equates file not found at {path}")
    m = re.search(r"^\s*MEM_END\s*=\s*(0x[0-9A-Fa-f]+)", path.read_text(),
                  re.MULTILINE)
    if not m:
        raise SymbolError(
            f"No 'MEM_END = 0x...' definition found in {path} -- the equate "
            "was renamed or its formatting changed."
        )
    return int(m.group(1), 16)


def xgb_sram_addr(map_file=None, equates_file=None):
    """Address of XGB_SRAM, derived and cross-checked against the build.

    Raises SymbolError if equates.h and the linker script disagree about where
    EWRAM ends, since then neither value can be trusted as the base.
    """
    mem_end = parse_mem_end(equates_file)
    ewram_end = load_symbols([EWRAM_END_SYMBOL], map_file=map_file)[EWRAM_END_SYMBOL]
    if mem_end != ewram_end:
        raise SymbolError(
            f"MEM_END in equates.h is 0x{mem_end:08X} but the linker puts the "
            f"end of EWRAM ({EWRAM_END_SYMBOL}) at 0x{ewram_end:08X}.\n"
            "  XGB_SRAM is derived from MEM_END, so this mismatch means the "
            "tests would read the wrong region. Reconcile the two."
        )
    return mem_end - XGB_SRAM_OFFSET_BELOW_MEM_END
