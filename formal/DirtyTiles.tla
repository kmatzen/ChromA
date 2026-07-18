---------------------------- MODULE DirtyTiles ----------------------------
(***************************************************************************)
(* Models the DIRTY_TILE_BITS race in ChromA.                              *)
(*                                                                         *)
(* Two execution contexts share DIRTY_TILE_BITS with no synchronisation:   *)
(*                                                                         *)
(*   Producer -- emulated-CPU context.  DoDma() (src/dma.c:97) copies tile *)
(*     data into VRAM and then marks the affected tiles via SetBits()      *)
(*     (src/dma.c:57-81), which is a plain `base[i] |= mask` -- a          *)
(*     non-atomic load / or / store.                                       *)
(*                                                                         *)
(*   Consumer -- GBA VBlank IRQ.  consume_dirty_tiles (src/lcd.s:812)      *)
(*     renders the tiles it observes and then calls ClearDirtyTiles to     *)
(*     zero the bitmap.                                                    *)
(*                                                                         *)
(* GFX_init_irq (src/lcd.s:227-247) leaves IME=1 permanently and jmpintr   *)
(* (src/lcd.s:1559-1568) re-enables IRQ inside the handler, so the         *)
(* producer is preemptible at any instruction boundary -- including        *)
(* between SetBits' load and its store.  Nothing in dma.c uses volatile,   *)
(* a critical section, or a barrier.                                       *)
(*                                                                         *)
(* HDMA drives the consumer on a per-HBlank cadence (src/timeout.s:391),   *)
(* so this interleaving is not exotic.                                     *)
(***************************************************************************)
EXTENDS FiniteSets

CONSTANTS Tiles, NoTile

(***************************************************************************)
(* Candidate fix.  When FALSE, ClearDirtyTiles zeroes the whole bitmap --   *)
(* current behaviour.  When TRUE, it clears only the bits the consumer      *)
(* actually observed and rendered, leaving anything the producer set in     *)
(* the meantime intact.                                                     *)
(***************************************************************************)
CONSTANT ClearOnlyObserved

VARIABLES
    bits,        \* DIRTY_TILE_BITS: tiles currently flagged for conversion
    dirtyData,   \* tiles whose VRAM bytes differ from what has been rendered
                 \* (the outstanding obligation -- NOT a real variable, this
                 \*  is the specification-level ghost we check against)
    ppc, preg, ptile,   \* producer: pc, the value loaded by SetBits, target tile
    cpc, csnap          \* consumer: pc, the bitmap it observed before clearing

vars == <<bits, dirtyData, ppc, preg, ptile, cpc, csnap>>

ASSUME NoTile \notin Tiles

TypeOK ==
    /\ bits      \subseteq Tiles
    /\ dirtyData \subseteq Tiles
    /\ preg      \subseteq Tiles
    /\ csnap     \subseteq Tiles
    /\ ptile     \in Tiles \cup {NoTile}
    /\ ppc       \in {"idle", "store"}
    /\ cpc       \in {"idle", "clear"}

Init ==
    /\ bits      = {}
    /\ dirtyData = {}
    /\ ppc = "idle" /\ preg = {} /\ ptile = NoTile
    /\ cpc = "idle" /\ csnap = {}

(***************************************************************************)
(* Producer.  DoDma has just rewritten tile t's VRAM bytes, creating the    *)
(* obligation to re-render it; SetBits then loads the current bitmap word.  *)
(***************************************************************************)
P_Load ==
    /\ ppc = "idle"
    /\ \E t \in Tiles :
        /\ dirtyData' = dirtyData \cup {t}
        /\ ptile'     = t
        /\ preg'      = bits          \* the ldr half of `base[i] |= mask`
    /\ ppc' = "store"
    /\ UNCHANGED <<bits, cpc, csnap>>

(* The str half.  Writes back a value computed from a possibly stale read. *)
P_Store ==
    /\ ppc = "store"
    /\ bits'  = preg \cup {ptile}
    /\ ppc'   = "idle"
    /\ preg'  = {}
    /\ ptile' = NoTile
    /\ UNCHANGED <<dirtyData, cpc, csnap>>

(***************************************************************************)
(* Consumer.  render_dirty_tiles walks the bitmap, then ClearDirtyTiles     *)
(* zeroes it.  The clear is NOT restricted to what was observed.            *)
(***************************************************************************)
C_Read ==
    /\ cpc = "idle"
    /\ csnap' = bits
    /\ cpc'   = "clear"
    /\ UNCHANGED <<bits, dirtyData, ppc, preg, ptile>>

C_Clear ==
    /\ cpc = "clear"
    /\ dirtyData' = dirtyData \ csnap   \* only what it actually rendered
    /\ bits'      = IF ClearOnlyObserved
                    THEN bits \ csnap   \* candidate fix
                    ELSE {}             \* current behaviour: clears everything
    /\ csnap'     = {}
    /\ cpc'       = "idle"
    /\ UNCHANGED <<ppc, preg, ptile>>

Next == P_Load \/ P_Store \/ C_Read \/ C_Clear

Spec == Init /\ [][Next]_vars /\ WF_vars(Next)

(***************************************************************************)
(* Safety.  A tile whose data changed must still be flagged, or be in the   *)
(* producer's in-flight store.  If it is in neither, the bit was dropped    *)
(* and the tile stays stale on screen until something else dirties it.      *)
(***************************************************************************)
InFlight == IF ppc = "store" THEN {ptile} ELSE {}

NoLostTile == dirtyData \subseteq (bits \cup InFlight)

(* Liveness: every obligation is eventually discharged. *)
AllEventuallyRendered == []( dirtyData /= {} => <>(dirtyData = {}) )
=============================================================================
