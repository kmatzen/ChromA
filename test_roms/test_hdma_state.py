#!/usr/bin/env python3
"""HBlank DMA savestate replay test (issue #51, item 1).

SaveIo captures FF55, but LoadIo replayed only FF51-FF54, so a state saved
while an HBlank DMA was running came back with the transfer silently
cancelled and the game's remaining blocks never arrived.

Replaying FF55 is not just a matter of writing the saved byte back.  FF55
reads bit 7 = 0 while a transfer runs, with the low bits holding remaining-1,
but a *write* with bit 7 clear means something else entirely: it cancels a
running HBlank transfer, or starts an immediate general-purpose DMA.  Only an
active value may be replayed, and it has to be written with bit 7 set.

The ROM makes both halves of that observable without depending on frame
timing.  An HBlank DMA only advances on the HBlank of a visible line with the
LCD on, so it starts a 128-block transfer and immediately turns the LCD off:
the transfer freezes with every block outstanding and FF55 reads 0x7F for the
rest of the run.  It then cancels the transfer when it sees Up rather than at
some frame count -- the runner auto-releases inputs after 15 frames, so once
the state is restored the ROM does not immediately cancel again.  Cancelled,
FF55 reads 0xFF.

Two runs:

  cancel only        no savestate at all.  Ends 0xFF, which is what proves
                     the cancel works -- without it, a final 0x7F in the run
                     below would just mean nothing ever cancelled.
  save/cancel/load   quicksave, then cancel, then quickload.  Ends 0x7F if
                     the active transfer was restored, 0xFF if it was not.

The ROM also mirrors a WRAM tick counter into cart RAM.  A savestate rewinds
WRAM, so a lower count in the second run is what proves a state was really
loaded.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
RUNNER = SCRIPT_DIR / "mgba_runner"
COMPILER = SCRIPT_DIR / "goomba_compile.py"
EMULATOR = PROJECT_DIR / "chroma.gba"
ROM = SCRIPT_DIR / "hdma_state_test.gb"

FRAMES = 2700
SAVE_FRAME = 800
CANCEL_FRAME = 1600
LOAD_FRAME = 2400
GAME_SRAM_SIZE = 0x2000

R_START = 0x00      # FF55 straight after starting the transfer
R_NOW = 0x01        # FF55, re-stamped every loop
R_TICK_LO = 0x02
R_TICK_HI = 0x03
R_DONE = 0x04
R_SAW_UP = 0x05

HDMA_RUNNING = 0x7F   # bit 7 clear = active, 127 = 128 blocks outstanding
HDMA_STOPPED = 0xFF   # bit 7 set = no transfer in progress


def run(inputs) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        gba, sav = tmp / "hd.gba", tmp / "hd.sav"
        r = subprocess.run(
            [sys.executable, str(COMPILER), "-e", str(EMULATOR),
             "-o", str(gba), str(ROM)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"ERROR: compile failed: {r.stderr}")
            sys.exit(2)
        cmd = [str(RUNNER), str(gba), str(FRAMES), "/dev/null",
               "--savefile", str(sav)]
        for inp in inputs:
            cmd += ["--input", inp]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            print("ERROR: runner timed out")
            sys.exit(2)
        if r.returncode != 0:
            print(f"ERROR: runner exited {r.returncode}: {r.stderr[:500]}")
            sys.exit(2)
        data = sav.read_bytes()
    return data[len(data) - GAME_SRAM_SIZE:]


def summarise(label, res):
    ticks = res[R_TICK_LO] | (res[R_TICK_HI] << 8)
    print(f"  {label:16s} FF55 at start={res[R_START]:#04x} "
          f"now={res[R_NOW]:#04x} ticks={ticks} done={res[R_DONE]:#04x}")
    return ticks


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"), (ROM, ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    cancel = run([f"{CANCEL_FRAME}:Up"])
    loaded = run([f"{SAVE_FRAME}:R+Select", f"{CANCEL_FRAME}:Up",
                  f"{LOAD_FRAME}:R+Start"])

    cancel_ticks = summarise("cancel only", cancel)
    load_ticks = summarise("save/cancel/load", loaded)

    for label, res in (("cancel only", cancel), ("save/cancel/load", loaded)):
        if res[R_DONE] != 0x5A:
            print(f"FAIL: the '{label}' run never finished set-up (done marker "
                  f"{res[R_DONE]:#04x}) -- results are not trustworthy")
            sys.exit(1)

    bad = []

    # Control: the transfer really was running before anything else happened.
    # If it was not, nothing below distinguishes a restored transfer from a
    # transfer that was never started -- FF51-FF55 are CGB-only registers, so
    # this also catches the ROM being run as a DMG cart.
    for label, res in (("cancel only", cancel), ("save/cancel/load", loaded)):
        if res[R_START] != HDMA_RUNNING:
            bad.append(f"control: in the '{label}' run FF55 read "
                       f"{res[R_START]:#04x} right after the transfer was "
                       f"started, expected {HDMA_RUNNING:#04x} -- no HBlank "
                       f"DMA was ever running")

    # Control: the cancel works.  Without this a final 0x7F below would be
    # satisfied by a run in which nothing ever cancelled the transfer.
    if cancel[R_SAW_UP] != 0x01:
        bad.append(f"control: the 'cancel only' run never saw Up "
                   f"(marker {cancel[R_SAW_UP]:#04x}), so it never cancelled "
                   f"the transfer and cannot serve as the negative case")
    if cancel[R_NOW] != HDMA_STOPPED:
        bad.append(f"control: after cancelling, the 'cancel only' run reads "
                   f"FF55={cancel[R_NOW]:#04x}, expected {HDMA_STOPPED:#04x}")

    # Control: a state really was restored.  The tick counter lives in WRAM,
    # so a load rewinds it.
    print(f"  rewind control: cancel-only={cancel_ticks} "
          f"save/cancel/load={load_ticks}")
    if load_ticks >= cancel_ticks:
        bad.append(f"control: the tick counter ended at {load_ticks} with the "
                   f"quicksave/quickload keys and {cancel_ticks} without -- a "
                   f"load should have rewound it, so no state was restored")

    if loaded[R_NOW] != HDMA_RUNNING:
        detail = ""
        if loaded[R_NOW] == HDMA_STOPPED:
            detail = (" -- the transfer that was running when the state was "
                      "saved was not restored, so FF55 still reads as "
                      "cancelled")
        bad.append(f"after the quickload FF55 reads {loaded[R_NOW]:#04x}, "
                   f"expected {HDMA_RUNNING:#04x}{detail}")

    if bad:
        for b in bad:
            print(f"FAIL: {b}")
        sys.exit(1)

    print("\nPASS: an HBlank DMA that was running when the state was saved is "
          "running again after it is loaded")
    sys.exit(0)


if __name__ == "__main__":
    main()
