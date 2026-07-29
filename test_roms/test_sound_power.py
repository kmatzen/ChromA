#!/usr/bin/env python3
"""APU power-off shadow test (issue #55, item 2).

chroma keeps `sound_shadow`, a 9-byte copy of the halves of NR11/NR13/NR14,
NR21/NR23/NR24 and NR31/NR33/NR34 that hardware will not read back.  SaveIo
copies it into a savestate verbatim, because those bits cannot be recovered
from the GBA registers.  Writing 0 to NR52 bit 7 powers the APU down and
resets every PSG register to zero -- but nothing cleared the shadow, so a
state saved after a power-cycle carried write-only values the APU no longer
held, and loading it put them back.

The power-cycle on its own is not observable: LoadIo replays FF10-FF3F in
ascending order, so if the APU was still off at save time the NR52 write at
FF26 wipes everything replayed before it.  Powering back on afterwards is what
makes it visible, and it is also what real games do -- "NR52=0 then NR52=$80"
is the standard APU init.

The ROM writes duty 11 to NR11, power-cycles the APU, and then free-runs.  It
is run twice: once with R+Select (quicksave) and R+Start (quickload), once
with no input at all.  The no-input run is the baseline, and the frame counter
is the control -- it lives in WRAM, so a savestate load rewinds it.  A lower
count in the quickload run is what proves a state was really restored, which
stops the NR11 assertion from passing for the trivial reason that nothing was
ever loaded.

After the load NR11 reads 0x3F if the shadow was cleared along with the APU,
and 0xFF (the stale 0xC0 duty, or'd with the 0x3F of write-only length bits)
if it came back.
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
ROM = SCRIPT_DIR / "sound_power_test.gb"

FRAMES = 2700
SAVE_FRAME = 1200
LOAD_FRAME = 2400
GAME_SRAM_SIZE = 0x2000

R_BEFORE = 0x00     # NR11 straight after the power-cycle
R_AFTER = 0x01      # NR11 re-stamped every frame
R_COUNT_LO = 0x02
R_COUNT_HI = 0x03
R_DONE = 0x04

NR11_CLEARED = 0x3F   # duty 00, length bits write-only
NR11_STALE = 0xFF     # the 0xC0 duty resurrected


def run(inputs) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        gba, sav = tmp / "pw.gba", tmp / "pw.sav"
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
    count = res[R_COUNT_LO] | (res[R_COUNT_HI] << 8)
    print(f"  {label:9s} NR11 before={res[R_BEFORE]:#04x} "
          f"after={res[R_AFTER]:#04x} frames={count} done={res[R_DONE]:#04x}")
    return count


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"), (ROM, ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    baseline = run([])
    loaded = run([f"{SAVE_FRAME}:R+Select", f"{LOAD_FRAME}:R+Start"])

    base_count = summarise("baseline", baseline)
    load_count = summarise("quickload", loaded)

    bad = []

    for label, res in (("baseline", baseline), ("quickload", loaded)):
        if res[R_DONE] != 0x5A:
            print(f"FAIL: the {label} run never finished set-up (done marker "
                  f"{res[R_DONE]:#04x}) -- results are not trustworthy")
            sys.exit(1)

    # Control 1: the power-cycle really does clear the register, so the
    # read-back the ROM records before any save is the value a correct load
    # has to reproduce.  If this is already 0xFF the APU is not being powered
    # down at all and the rest of the test means nothing.
    for label, res in (("baseline", baseline), ("quickload", loaded)):
        if res[R_BEFORE] != NR11_CLEARED:
            bad.append(f"control: in the {label} run NR11 read "
                       f"{res[R_BEFORE]:#04x} straight after the power-cycle, "
                       f"expected {NR11_CLEARED:#04x} -- powering the APU off "
                       f"is not clearing the register")

    # Control 2: proof that a savestate was actually restored.  The counter is
    # in WRAM, so a load rewinds it; without this, a correct-looking NR11
    # read-back could just mean the quicksave/quickload keys did nothing.
    print(f"  rewind control: baseline={base_count} quickload={load_count}")
    if load_count >= base_count:
        bad.append(f"control: the frame counter ended at {load_count} with the "
                   f"quicksave/quickload keys and {base_count} without -- a "
                   f"load should have rewound it, so no state was restored and "
                   f"the NR11 result below proves nothing")

    if loaded[R_AFTER] != NR11_CLEARED:
        detail = ""
        if loaded[R_AFTER] == NR11_STALE:
            detail = (" -- this is the 0xC0 duty written before the "
                      "power-cycle, restored from a shadow the power-off "
                      "never cleared")
        bad.append(f"after the quickload NR11 reads {loaded[R_AFTER]:#04x}, "
                   f"expected {NR11_CLEARED:#04x}{detail}")

    if baseline[R_AFTER] != NR11_CLEARED:
        bad.append(f"the baseline run's NR11 drifted to "
                   f"{baseline[R_AFTER]:#04x} with no savestate involved, "
                   f"expected {NR11_CLEARED:#04x}")

    if bad:
        for b in bad:
            print(f"FAIL: {b}")
        sys.exit(1)

    print("\nPASS: powering the APU off clears the write-only register shadow, "
          "so a state saved afterwards does not restore stale values")
    sys.exit(0)


if __name__ == "__main__":
    main()
