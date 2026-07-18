# Formal specs

TLA+ models of ChromA's concurrent state machines. These verify *designs*, not
the assembly — see "What this does not prove" below.

## Running

Needs Java and [`tla2tools.jar`](https://github.com/tlaplus/tlaplus/releases/latest/download/tla2tools.jar).

```sh
# current behaviour -- expect an invariant violation
java -cp tla2tools.jar tlc2.TLC -deadlock -config DirtyTiles.cfg DirtyTiles.tla

# candidate fix -- expect "no error has been found"
java -cp tla2tools.jar tlc2.TLC -deadlock -config DirtyTilesFixed.cfg DirtyTiles.tla
```

## DirtyTiles.tla

Models the `DIRTY_TILE_BITS` race between two unsynchronised contexts:

- **Producer** — emulated-CPU context. `DoDma()` (`src/dma.c:97`) rewrites tile
  data in VRAM, then `SetBits()` (`src/dma.c:57-81`) marks the tiles with a
  plain `base[i] |= mask` — a non-atomic load / or / store.
- **Consumer** — GBA VBlank IRQ. `consume_dirty_tiles` (`src/lcd.s:812`) renders
  what it observes, then `ClearDirtyTiles` (`src/lcd.s:933`) zeroes the whole
  bitmap with `memset32(DIRTY_TILE_BITS, 0, 48)`.

`GFX_init_irq` (`src/lcd.s:227-247`) leaves IME=1 permanently and `jmpintr`
(`src/lcd.s:1559-1568`) re-enables IRQ inside the handler, so the producer is
preemptible at any instruction boundary. Nothing in `dma.c` uses `volatile`, a
critical section, or a barrier. HDMA drives the consumer per-HBlank
(`src/timeout.s:391`), so the interleaving is routine, not exotic.

### Invariant

`NoLostTile` — a tile whose VRAM bytes changed is still flagged in `bits`, or is
in the producer's in-flight store. If neither, the bit was dropped and the tile
stays stale on screen until something else dirties it.

### Result

TLC violates `NoLostTile` in 5 states:

```
State 2: P_Load   -- DoDma dirties t1; SetBits loaded bits={} but has not stored
State 3: C_Read   -- VBlank preempts, observes bits={} -> nothing to render
State 4: P_Store  -- producer completes its store: bits={t1}
State 5: C_Clear  -- ClearDirtyTiles zeroes everything; t1 was never rendered
```

The IRQ lands *inside* `SetBits`' load/store window. The consumer then clears a
bit it never observed.

With `ClearOnlyObserved = TRUE` (consumer clears only what it rendered) the
invariant holds exhaustively: 100 distinct states for 2 tiles, 611 for 3.

## What this does not prove

The model shows the *design* "clear only what you observed" is sound. It does
not show any particular implementation is. On ARM7TDMI there are no atomics
(no LDREX/STREX), so realising it needs one of:

- **Snapshot-and-swap** — swap the bitmap to a shadow buffer with IRQs masked
  for the swap only, render from the shadow, never clear the live one. Costs 48
  bytes and a short critical section.
- **IME masking** around both `SetBits`' RMW and `ClearDirtyTiles`. Simpler, but
  adds cycles to a hot path, and ARCHITECTURE.md is emphatic about the
  per-scanline budget.

Note that clearing each word as the walker consumes it is *not* a fix — a
producer setting a bit between that read and write still loses it. It only
narrows the window.

The model also abstracts the bitmap as a set of tiles rather than 48 words of
packed bits, and treats `render_dirty_tiles` as taking one snapshot, whereas the
real walker reads the bitmap incrementally while rendering. Both abstractions
make the real code *more* interleaved, not less, so the violation stands.
