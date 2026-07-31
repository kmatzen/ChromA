#!/usr/bin/env python3
"""Does an MBC3 clock-set survive the latch? (issue #49)

test_mbc3_rtc.py checks that the RTC registers accept writes and read back,
deliberately with no latch in between.  That is only half of a clock-set: the
latch is what the game does next, and ChromA derives the time from its frame
counter, so a write that is merely stored into mapperdata used to be
recomputed away by the very next latch.  The registers accepted the write and
the value snapped back one latch later -- the symptom issue #49 describes.

The probe runs the whole flow: halt, write every field, release halt, latch,
read back.  It then checks that the halt bit stops the counters and that they
move again once it is cleared.

The clock-set readback is checked against mGBA's own Game Boy core too: it is
a property of the mapper rather than of any particular clock source, and mGBA
agrees field for field (0 / 30 / 12 / 20 / 0).

The two behavioural checks -- a halted clock does not tick, a running one does
-- are asserted for ChromA only.  mGBA's RTC runs off the host wall clock, and
a headless 1400-frame run finishes in a fraction of a second, so its counters
barely move whether it honours the halt bit or not; its halted reading came
out 0->0 on one run and 0->1 on the next, which reflects a wall-clock second
boundary and not halt behaviour.  ChromA's clock is driven by the emulated
frame count, where 240 frames is exactly 4.02 seconds, so both checks are
meaningful there.  mGBA's numbers are printed rather than asserted.

Run: python3 test_roms/test_mbc3_rtc_latch.py
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
ROM = SCRIPT_DIR / "mbc3_rtc_latch_test.gb"

FRAMES = 1400          # two 240-frame waits plus room for the rest
GAME_SRAM_SIZE = 0x2000

# result offsets, matching the header comment in mbc3_rtc_latch_test.asm
R_SEC, R_MIN, R_HRS, R_DAYL, R_DH = 0x00, 0x01, 0x02, 0x03, 0x04
R_HALT_SEC1, R_HALT_SEC2, R_HALT_DH = 0x05, 0x06, 0x07
R_RUN_SEC1, R_RUN_SEC2 = 0x08, 0x09
R_DONE = 0x0F

# what the probe wrote, and so what the latch has to give back
SET_FIELDS = [
    (R_SEC, "seconds", 0),
    (R_MIN, "minutes", 30),
    (R_HRS, "hours", 12),
    (R_DAYL, "day low", 20),
    (R_DH, "DH", 0),
]

DH_HALT = 0x40

# 240 frames is 4.02 s of emulated time.  Allow a wide band: the probe spends
# frames on the surrounding register traffic too, and the point is that the
# clock moves at all, not that it moves by exactly four.
RUN_ADVANCE_MIN = 2
RUN_ADVANCE_MAX = 12


def run(wrap: bool) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        sav = tmp / "rtc.sav"
        if wrap:
            target = tmp / "rtc.gba"
            r = subprocess.run(
                [sys.executable, str(COMPILER), "-e", str(EMULATOR),
                 "-o", str(target), str(ROM)],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                print(f"ERROR: compile failed: {r.stderr}")
                sys.exit(2)
        else:
            target = ROM
        try:
            r = subprocess.run(
                [str(RUNNER), str(target), str(FRAMES), "/dev/null",
                 "--savefile", str(sav)],
                capture_output=True, text=True, timeout=600,
            )
        except subprocess.TimeoutExpired:
            print("ERROR: runner timed out")
            sys.exit(2)
        if r.returncode != 0:
            print(f"ERROR: runner exited {r.returncode}: {r.stderr[:500]}")
            sys.exit(2)
        data = sav.read_bytes()
    if wrap:
        # Goomba's save format puts the running game's SRAM last.
        return data[len(data) - GAME_SRAM_SIZE:]
    # mGBA writes cart SRAM from byte 0 and, for an MBC3+RTC cart, appends a
    # 48-byte RTC footer -- so the results are at the front here, not the tail.
    return data[:GAME_SRAM_SIZE]


def report(label: str, res: bytes) -> None:
    print(f"  {label}:")
    for off, name, want in SET_FIELDS:
        got = res[off]
        mark = "" if got == want else "   <-- expected %d" % want
        print(f"    {name:9s} after clock-set + latch: {got:3d}{mark}")
    print(f"    halted   seconds {res[R_HALT_SEC1]:3d} -> "
          f"{res[R_HALT_SEC2]:3d}  (DH {res[R_HALT_DH]:#04x})")
    print(f"    running  seconds {res[R_RUN_SEC1]:3d} -> "
          f"{res[R_RUN_SEC2]:3d}")


def check_shared(label: str, res: bytes, bad: list) -> None:
    """Assertions that hold for any MBC3 regardless of what drives its clock:
    the clock-set survives the latch, and DH carries the halt bit back."""
    for off, name, want in SET_FIELDS:
        if res[off] != want:
            bad.append(
                f"{label}: {name} read back {res[off]} after the latch, "
                f"expected {want} -- the clock-set did not survive latching")

    if not res[R_HALT_DH] & DH_HALT:
        bad.append(f"{label}: DH read {res[R_HALT_DH]:#04x} while the clock "
                   f"was halted, halt bit (0x40) not set")


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"), (ROM, ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    ref = run(wrap=False)
    got = run(wrap=True)

    report("mGBA native GB core", ref)
    report("ChromA", got)

    bad = []
    if ref[R_DONE] != 0x5A:
        bad.append("the probe did not finish under mGBA -- the reference is "
                   "not usable, so nothing here can be judged")
    if got[R_DONE] != 0x5A:
        bad.append("the probe did not finish under ChromA")

    if not bad:
        check_shared("mGBA", ref, bad)
        check_shared("ChromA", got, bad)

        # The two behavioural checks below are ChromA-only, because mGBA's RTC
        # runs off the host wall clock: a headless 1400-frame run finishes in
        # a fraction of a second, so mGBA's counters barely move whether it
        # honours the halt bit or not.  Its halted reading came out 0->0 on
        # one run and 0->1 on the next, which is a wall-clock second boundary
        # rather than any statement about halt -- asserting on it would be
        # asserting on how fast this machine happens to be.  ChromA's clock is
        # driven by the emulated frame count, so both checks are exact there.
        halt_advance = (got[R_HALT_SEC2] - got[R_HALT_SEC1]) % 60
        run_advance = (got[R_RUN_SEC2] - got[R_RUN_SEC1]) % 60
        print(f"  ChromA over 240 frames: halted +{halt_advance} s, "
              f"running +{run_advance} s")
        print(f"  mGBA (wall-clock driven, informational): halted "
              f"+{(ref[R_HALT_SEC2] - ref[R_HALT_SEC1]) % 60} s, running "
              f"+{(ref[R_RUN_SEC2] - ref[R_RUN_SEC1]) % 60} s")

        if halt_advance != 0:
            bad.append(
                f"ChromA: a halted clock advanced {halt_advance} s over 240 "
                f"frames -- the halt bit (DH bit 6) is being ignored")

        if not RUN_ADVANCE_MIN <= run_advance <= RUN_ADVANCE_MAX:
            bad.append(
                f"ChromA advanced {run_advance} s over 240 frames of running "
                f"clock, expected {RUN_ADVANCE_MIN}-{RUN_ADVANCE_MAX} "
                f"(240 frames is 4.02 s) -- either the clock did not restart "
                f"after halt or it is not tracking the frame count")

    if bad:
        print()
        for b in bad:
            print("FAIL: " + b)
        sys.exit(1)

    print()
    print("PASS: an MBC3 clock-set survives the latch, and the halt bit "
          "stops and restarts the counters")


if __name__ == "__main__":
    main()
