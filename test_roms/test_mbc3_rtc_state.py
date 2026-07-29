#!/usr/bin/env python3
"""MBC3 RTC-select rehydration test (issue #49, item 4).

Writing 8-C to 4000-5FFF on an MBC3 maps an RTC register over A000-BFFF
instead of a RAM bank, and that selection lives in mapperdata+4.  A savestate
records the byte, but AfterLoadState always called RamSelect, which maps SRAM
unconditionally -- so a state taken while an RTC register was selected came
back with cart RAM mapped there, and stayed that way until the game happened
to reselect.  Pokemon G/S/C read the clock exactly this way.

Telling the two mappings apart needs a byte that differs between them.  Cart
RAM holds a sentinel of 0xE7 at A100; the RTC seconds register holds a live
binary count of 0-59, so it can never be 0xE7.  Reading A100 says which is
mapped.

Three runs, sharing one ROM:

  rtc kept       no savestate, no bank switch.  Reads the clock -- the
                 positive control for "an RTC register is mapped".
  ram selected   no savestate; switches to RAM bank 0 first.  Reads 0xE7 --
                 the negative control, and what a failed rehydration looks
                 like.
  save/ram/load  quicksave with the RTC selected, switch to RAM bank 0,
                 quickload.  Must read the clock again, not the sentinel.

The ROM cannot write its results while an RTC register is selected -- every
store to A000-BFFF would go to the clock -- so it samples A100 on a keypress,
then switches back to a RAM bank and only then starts writing.  The frame
counter lives in WRAM, so a lower count in the third run proves a state was
really restored.
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
ROM = SCRIPT_DIR / "mbc3_rtc_state_test.gb"

FRAMES = 3000
SAVE_FRAME = 800
BANK_FRAME = 1600
LOAD_FRAME = 2400
SAMPLE_FRAME = 2600
GAME_SRAM_SIZE = 0x2000

R_SAMPLE = 0x00
R_PHASE = 0x01
R_FRAME_LO = 0x02
R_FRAME_HI = 0x03
R_DONE = 0x04

SENTINEL = 0xE7      # what cart RAM holds at A100
MAX_SECONDS = 59     # RTC seconds is a binary 0-59 count, so it is never 0xE7
PHASE_SAMPLED = 0x03


def run(inputs) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        gba, sav = tmp / "rs.gba", tmp / "rs.sav"
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
    frames = res[R_FRAME_LO] | (res[R_FRAME_HI] << 8)
    print(f"  {label:14s} A100 reads {res[R_SAMPLE]:#04x}  phase="
          f"{res[R_PHASE]:#04x} frames={frames}")
    return frames


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"), (ROM, ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    kept = run([f"{SAMPLE_FRAME}:Down"])
    ram = run([f"{BANK_FRAME}:Up", f"{SAMPLE_FRAME}:Down"])
    loaded = run([f"{SAVE_FRAME}:R+Select", f"{BANK_FRAME}:Up",
                  f"{LOAD_FRAME}:R+Start", f"{SAMPLE_FRAME}:Down"])

    kept_frames = summarise("rtc kept", kept)
    summarise("ram selected", ram)
    load_frames = summarise("save/ram/load", loaded)

    runs = (("rtc kept", kept), ("ram selected", ram),
            ("save/ram/load", loaded))
    for label, res in runs:
        if res[R_DONE] != 0x5A:
            print(f"FAIL: the '{label}' run never finished set-up "
                  f"(done marker {res[R_DONE]:#04x})")
            sys.exit(1)
        if res[R_PHASE] != PHASE_SAMPLED:
            print(f"FAIL: the '{label}' run never reached the sampling phase "
                  f"(phase {res[R_PHASE]:#04x}) -- it never saw Down, so its "
                  f"reading is meaningless")
            sys.exit(1)

    bad = []

    # Positive control: with an RTC register selected and no savestate in the
    # picture, A100 must read the clock.  A live, non-zero count also rules out
    # a handler that was never installed, which would read a flat 0.
    if kept[R_SAMPLE] > MAX_SECONDS or kept[R_SAMPLE] == 0:
        bad.append(f"control: with the RTC selected and no savestate, A100 "
                   f"read {kept[R_SAMPLE]:#04x}; expected a running seconds "
                   f"count in 1..{MAX_SECONDS}. The clock is not mapped even "
                   f"before a load is involved, so nothing below means "
                   f"anything")

    # Negative control: this is what a failed rehydration looks like, and it
    # establishes that the sentinel is reachable at all.
    if ram[R_SAMPLE] != SENTINEL:
        bad.append(f"control: after switching to RAM bank 0, A100 read "
                   f"{ram[R_SAMPLE]:#04x}, expected the sentinel "
                   f"{SENTINEL:#04x}")

    # Control: a state really was restored.
    print(f"  rewind control: rtc-kept={kept_frames} "
          f"save/ram/load={load_frames}")
    if load_frames >= kept_frames:
        bad.append(f"control: the frame counter ended at {load_frames} with "
                   f"the quicksave/quickload keys and {kept_frames} without -- "
                   f"a load should have rewound it, so no state was restored")

    if loaded[R_SAMPLE] > MAX_SECONDS:
        detail = ""
        if loaded[R_SAMPLE] == SENTINEL:
            detail = (" -- that is the cart RAM sentinel: the state was saved "
                      "with an RTC register selected, but the load mapped SRAM "
                      "over it")
        bad.append(f"after the quickload A100 read {loaded[R_SAMPLE]:#04x}, "
                   f"expected a seconds count in 0..{MAX_SECONDS}{detail}")

    if bad:
        for b in bad:
            print(f"FAIL: {b}")
        sys.exit(1)

    print("\nPASS: an MBC3 state saved with an RTC register selected comes "
          "back with that register mapped, not cart RAM")
    sys.exit(0)


if __name__ == "__main__":
    main()
