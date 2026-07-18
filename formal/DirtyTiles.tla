---------------------------- MODULE DirtyTiles ----------------------------
(***************************************************************************)
(* DIRTY_TILE_BITS: producer/consumer structure in ChromA.                 *)
(*                                                                         *)
(* CONTEXTS (established by tracing call sites, not assumed):              *)
(*                                                                         *)
(*   Producer -- FOREGROUND (emulated-CPU context).  DoDma() rewrites tile *)
(*     data in VRAM, then SetBits() (src/dma.c:57-81) marks the tiles with *)
(*     a plain `base[i] |= mask` -- a non-atomic load / or / store.        *)
(*     Reached only from FF55_W (src/io.s:790) and tick_hdma               *)
(*     (src/timeout.s:391).  Both foreground.                              *)
(*                                                                         *)
(*   Consumer -- GBA HARDWARE IRQ.  consume_dirty_tiles (src/lcd.s:812)    *)
(*     has exactly one caller, src/lcd.s:1644, inside vblankinterrupt      *)
(*     (src/lcd.s:1589), reached via irqhandler -> jmpintr.                *)
(*                                                                         *)
(* The IRQ preempts foreground; foreground never preempts the IRQ.         *)
(* jmpintr re-enabling IRQ/FIQ lets OTHER HANDLERS nest -- it does not     *)
(* resume the emulated CPU.  So the consumer's walk-and-clear is a single  *)
(* atomic step with respect to the producer, and is modelled as one action.*)
(*                                                                         *)
(* This is the corrected model.  An earlier version of this spec split the *)
(* consumer into separate read and clear actions, which admitted a         *)
(* lost-update trace that the real system cannot exhibit.  Modelling the   *)
(* consumer as interleavable was the error; see formal/README.md.          *)
(*                                                                         *)
(* The one genuine interleaving is the IRQ landing between SetBits' load   *)
(* and its store.  That is what this spec is for.                          *)
(***************************************************************************)
EXTENDS FiniteSets

CONSTANTS Tiles, NoTile

ASSUME NoTile \notin Tiles

VARIABLES
    bits,        \* DIRTY_TILE_BITS: tiles currently flagged for conversion
    dirtyData,   \* ghost: tiles whose VRAM bytes differ from what was
                 \* rendered -- the outstanding obligation
    ppc,         \* producer pc: "idle" or "store" (mid read-modify-write)
    preg,        \* the word SetBits loaded, not yet stored back
    ptile        \* the tile SetBits is in the middle of flagging

vars == <<bits, dirtyData, ppc, preg, ptile>>

TypeOK ==
    /\ bits      \subseteq Tiles
    /\ dirtyData \subseteq Tiles
    /\ preg      \subseteq Tiles
    /\ ptile     \in Tiles \cup {NoTile}
    /\ ppc       \in {"idle", "store"}

Init ==
    /\ bits      = {}
    /\ dirtyData = {}
    /\ ppc = "idle" /\ preg = {} /\ ptile = NoTile

(***************************************************************************)
(* Producer, foreground.  The ldr half of `base[i] |= mask`.  DoDma has     *)
(* already rewritten tile t's bytes, so the obligation exists from here.    *)
(***************************************************************************)
P_Load ==
    /\ ppc = "idle"
    /\ \E t \in Tiles :
        /\ dirtyData' = dirtyData \cup {t}
        /\ ptile'     = t
        /\ preg'      = bits
    /\ ppc' = "store"
    /\ UNCHANGED bits

(* The str half.  Writes back a value computed before any preemption. *)
P_Store ==
    /\ ppc = "store"
    /\ bits'  = preg \cup {ptile}
    /\ ppc'   = "idle"
    /\ preg'  = {}
    /\ ptile' = NoTile
    /\ UNCHANGED dirtyData

(***************************************************************************)
(* Consumer, IRQ.  ONE action: render_dirty_tiles walks the bitmap and      *)
(* ClearDirtyTiles (src/lcd.s:933) zeroes it, with no producer step         *)
(* possible in between.  May fire while ppc = "store" -- that is the        *)
(* mid-RMW preemption.                                                      *)
(***************************************************************************)
C_Vblank ==
    /\ dirtyData' = dirtyData \ bits    \* everything flagged gets rendered
    /\ bits'      = {}
    /\ UNCHANGED <<ppc, preg, ptile>>

Next == P_Load \/ P_Store \/ C_Vblank

Spec == Init /\ [][Next]_vars /\ WF_vars(Next)

InFlight == IF ppc = "store" THEN {ptile} ELSE {}

(***************************************************************************)
(* SAFETY -- expected to HOLD.                                             *)
(* A tile whose data changed is still flagged, or is in the producer's      *)
(* in-flight store.  If this holds, no tile is ever left stale.             *)
(***************************************************************************)
NoLostTile == dirtyData \subseteq (bits \cup InFlight)

(***************************************************************************)
(* EFFICIENCY -- expected to FAIL, and that failure is the real finding.   *)
(* Every flagged tile actually needs rendering.  Mid-RMW preemption breaks  *)
(* this: the producer stores back `old | mask`, resurrecting bits the IRQ   *)
(* just rendered and cleared.  Consequence is redundant conversion work,    *)
(* not incorrect output.                                                    *)
(***************************************************************************)
NoRedundantFlag == bits \subseteq dirtyData
=============================================================================
