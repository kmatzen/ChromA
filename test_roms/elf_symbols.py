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

from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
MAP_FILE = PROJECT_DIR / "build" / "chroma.elf.map"


class SymbolError(RuntimeError):
    """The map file is unusable, or a requested symbol is not in it."""


def parse_map(text):
    """Extract {symbol: address} from GNU ld map output.

    Symbol definitions appear as a lone address/name pair, e.g.
        0x00000000030038cc                joycfg
    First definition wins, matching the order ld emits them in.
    """
    symbols = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        addr, name = parts
        if not addr.startswith("0x"):
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
