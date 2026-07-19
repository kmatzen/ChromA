# Formal specs

TLA+ models of ChromA's shared-state structure. These verify *designs*, not the
assembly — see "What this does not prove".

## Running

Needs Java and [`tla2tools.jar`](https://github.com/tlaplus/tlaplus/releases/latest/download/tla2tools.jar).

```sh
# safety -- expect "no error has been found"
java -cp tla2tools.jar tlc2.TLC -deadlock -config DirtyTiles.cfg DirtyTiles.tla

# efficiency -- expect NoRedundantFlag violated (this is the finding)
java -cp tla2tools.jar tlc2.TLC -deadlock -config Redundant.cfg DirtyTiles.tla
```

## DirtyTiles.tla

Models `DIRTY_TILE_BITS`, shared between:

- **Producer — foreground (emulated-CPU context).** `DoDma()` rewrites tile data
  in VRAM, then `SetBits()` (`src/dma.c:57-81`) marks the tiles with a plain
  `base[i] |= mask` — a non-atomic load / or / store. Reached only from
  `FF55_W` (`src/io.s:790`) and `tick_hdma` (`src/timeout.s:391`).
- **Consumer — GBA hardware IRQ.** `consume_dirty_tiles` (`src/lcd.s:812`) has
  exactly one caller, `src/lcd.s:1644`, inside `vblankinterrupt`
  (`src/lcd.s:1589`), reached via `irqhandler` → `jmpintr`.

The IRQ preempts foreground; foreground never preempts the IRQ. `jmpintr`
re-enabling IRQ/FIQ lets *other handlers* nest — it does not resume the emulated
CPU. So the consumer's walk-and-clear is **atomic with respect to the producer**
and is modelled as a single action.

The one genuine interleaving is the IRQ landing between `SetBits`' load and its
store.

### Results

| Property | Meaning | Result |
|---|---|---|
| `NoLostTile` | a changed tile is still flagged, or in the in-flight store | **holds** (27 states / 2 tiles, 357 / 4) |
| `NoRedundantFlag` | every flagged tile actually needs rendering | **violated** |

`NoLostTile` holding is the important result: **no tile is ever left stale.**

`NoRedundantFlag` fails as follows — the producer loads the bitmap, the IRQ
renders and clears it, then the producer stores back `old | mask`, resurrecting
bits that were just rendered:

```
State 4: P_Load    -- SetBits loads bits={t1}; dirtyData={t1}
State 5: C_Vblank  -- IRQ renders and clears: bits={}, dirtyData={}
State 6: P_Store   -- stores preg|{ptile} = {t1}: t1 re-flagged, nothing to do
```

The consequence is **redundant tile conversion, not incorrect output**. Given how
tight the per-scanline cycle budget is (see KNOWN_ISSUES.md), a fix would
plausibly cost more than the wasted work — this is documented, not actioned.

## Correction: an earlier version of this spec was wrong

The first version of `DirtyTiles.tla` split the consumer into separate `C_Read`
and `C_Clear` actions and found a 5-state "lost tile" trace. **That trace was an
artefact of the model, not a real defect.**

The error was assuming producer and consumer interleave freely. They do not: the
consumer runs only in IRQ context, the producer only in foreground, and the IRQ
cannot be interrupted by the emulated CPU. Modelling the consumer's read and
clear as separately schedulable admitted an interleaving the hardware cannot
produce.

The same mistake invalidated a companion claim about `vram_packets_registered_*`
being raced between `RegisterDmaPackets` and `store_dirty_packets`. Tracing the
callers: `RegisterDmaPackets` runs from `DoDma` (`src/dma.c:146`, foreground),
and `store_dirty_packets` from `newframe_vblank` (`src/lcd.s:3346`), whose only
caller is `src/timeout.s:220` — the *emulated* VBlank in the foreground scanline
state machine, not the hardware IRQ. Both foreground, therefore sequential. No
race.

**Lesson worth keeping:** establish which context each side runs in by tracing
call sites *before* writing the model. A spec inherits every assumption you put
into it, and model checking cannot tell you the structure is wrong — it will
happily produce a confident counterexample to a premise you invented.

## What this does not prove

- The model abstracts the bitmap as a set of tiles, not 48 bytes of packed bits
  split into two 24-byte per-VRAM-bank halves (`src/lcd.s:4873`).
- It treats `render_dirty_tiles` as rendering everything flagged in one step. The
  real walker (`GetNextTileAndLength_dirty`, `src/lcd.s:945+`) reads the bitmap
  incrementally — but since no producer step can interleave, that is a faithful
  abstraction here.
- It says nothing about `dirty_map_words`, `vram_packets_dirty`, or
  `RECENT_TILES`, which have their own lifecycles.
