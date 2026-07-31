#!/usr/bin/env python3
"""The software RTC survives a power cycle (issue #49 item 5).

The MBC3 software clock used to restart at 10:00:00 on every power-on, so a
game's in-game clock ran *backwards* between sessions.  There is no wall clock
to recover on a cart with no RTC hardware -- time genuinely does not pass while
the machine is off -- but the clock can at least carry on from where it
stopped instead of jumping back.

The epoch now rides in the config record's `reserved4`, which the template only
used for its three-character "CFG" tag, so the record keeps its size and layout
and stays readable by the other Goomba-family forks that share the format.  A
magic distinguishes a clock ChromA wrote from their zeroes.

`writeconfig()` runs when the player leaves the game -- `restart()` and
`exit_()` in ui.c -- which is the closest thing a GBA has to a shutdown hook,
so that is when the clock is captured.  This test drives the menu to Restart
for exactly that reason: an ordinary menu close (B) does not write the config
and would not persist anything, which is what my first attempt measured.

Three runs, because the claim needs a control:

    1. fresh save            -> 10:00:00     (the boot epoch)
    2. play, then Restart    -> record holds an epoch later than 10:00:00
    3. boot run 2's save     -> that later time, not 10:00:00

Without run 1 the third reading proves nothing; without run 3 the second only
shows a number was written.

Run: python3 test_roms/test_rtc_persist.py
"""

import struct
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
RUNNER = SCRIPT_DIR / "mgba_runner"
COMPILER = SCRIPT_DIR / "goomba_compile.py"
EMULATOR = PROJECT_DIR / "chroma.gba"
ROM = SCRIPT_DIR / "mbc3_rtc_persist_test.gb"

GAME_SRAM_SIZE = 0x2000
BOOT_SECONDS = 10 * 3600          # the clock's power-on epoch, 10:00:00
EPOCH_MAGIC = b"RTC1"

MENU_GAP = 120
RESTART_ITEM = 9                  # Down x9 from the top of the menu

# The restored clock is read a few frames into the next boot, so allow a
# little drift -- but far less than the ~60 s the session advances it by.
MATCH_TOLERANCE = 5


def hms(total):
    return f"{total // 3600 % 24:02d}:{total // 60 % 60:02d}:{total % 60:02d}"


def compile_rom(out):
    r = subprocess.run(
        [sys.executable, str(COMPILER), "-e", str(EMULATOR),
         "-o", str(out), str(ROM)],
        capture_output=True, text=True)
    if r.returncode != 0:
        print(f"ERROR: compile failed: {r.stderr[:300]}")
        sys.exit(2)


def run(gba, sav, frames, inputs=()):
    cmd = [str(RUNNER), str(gba), str(frames), "/dev/null"]
    for spec in inputs:
        cmd += ["--input", spec]
    cmd += ["--savefile", str(sav)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        print("ERROR: runner timed out")
        sys.exit(2)
    if r.returncode != 0:
        print(f"ERROR: runner exited {r.returncode}: {r.stderr[:300]}")
        sys.exit(2)
    data = sav.read_bytes()
    game = data[-GAME_SRAM_SIZE:]
    # seconds/minutes/hours are binary across the bus (the clk_* readers
    # decode ChromA's internal BCD), so the probe's bytes are usable directly.
    clock = game[2] * 3600 + game[1] * 60 + game[0]
    idx = data.find(EPOCH_MAGIC)
    epoch = struct.unpack("<I", data[idx + 4:idx + 8])[0] if idx >= 0 else None
    return clock, epoch, game[0x0F]


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"), (ROM, ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    bad = []
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        gba = td / "p.gba"
        compile_rom(gba)

        # 1. Control: a fresh save must boot at exactly 10:00:00, so a later
        #    reading in run 3 can only have come from the persisted record.
        fresh_clock, _, done = run(gba, td / "fresh.sav", 1500)
        print(f"  fresh save            -> {hms(fresh_clock)}")
        if done != 0x5A:
            bad.append("the probe did not finish on a fresh save")
        elif fresh_clock != BOOT_SECONDS:
            bad.append(f"a fresh save booted at {hms(fresh_clock)}, expected "
                       f"{hms(BOOT_SECONDS)} -- the control is wrong, so "
                       f"nothing below can be judged")

        # 2. Play for a while, then leave the game via Restart, which is what
        #    calls writeconfig().  A plain menu close does not.
        sav = td / "session.sav"
        t = 4000
        inputs = [f"{t}:L+R"]
        t += 200
        inputs += [f"{t + i * MENU_GAP}:Down" for i in range(RESTART_ITEM)]
        t += RESTART_ITEM * MENU_GAP + 140
        inputs += [f"{t}:A"]
        _, epoch, done = run(gba, sav, 14000, inputs)
        if epoch is None:
            bad.append("no RTC epoch was written to the config record at all "
                       "-- writeconfig() did not store one")
        else:
            print(f"  after play + Restart  -> record holds {hms(epoch)}")
            if epoch <= BOOT_SECONDS:
                bad.append(
                    f"the persisted epoch is {hms(epoch)}, not later than the "
                    f"boot time {hms(BOOT_SECONDS)} -- the clock at the moment "
                    f"the player left was captured as though no time had "
                    f"passed.  Check that writeconfig() reads the live clock "
                    f"rather than running before the cart is up")

        # 3. Power-cycle onto that save: the clock must resume, not reset.
        if not bad:
            resumed, _, done = run(gba, sav, 1500)
            print(f"  power cycle onto it   -> {hms(resumed)}")
            if done != 0x5A:
                bad.append("the probe did not finish after the power cycle")
            elif resumed == BOOT_SECONDS:
                bad.append(
                    f"the clock came back at {hms(BOOT_SECONDS)} -- the epoch "
                    f"was persisted but not restored.  readconfig() runs "
                    f"before the boot loadcart(), so it hands the value to "
                    f"rtc_restore_epoch and rtc_reset consumes it; check that "
                    f"rtc_reset is not simply overwriting it")
            elif abs(resumed - epoch) > MATCH_TOLERANCE:
                bad.append(
                    f"the clock came back at {hms(resumed)} but the record "
                    f"held {hms(epoch)} (tolerance {MATCH_TOLERANCE}s)")

    if bad:
        print()
        for b in bad:
            print("FAIL: " + b)
        sys.exit(1)

    print()
    print("PASS: the software RTC resumes where it stopped instead of "
          "restarting at 10:00:00")


if __name__ == "__main__":
    main()
