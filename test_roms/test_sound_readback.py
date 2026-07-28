#!/usr/bin/env python3
"""Sound register read-back mask test (issue #55, item 1).

Every GB sound register has write-only or unused bits, and hardware reads
those back as 1.  chroma's _FFxxR handlers returned the GBA PSG register
value unchanged, and the GBA reads 0 for its write-only bits, so the whole
register file read back too low -- Blargg's dmg_sound "registers" test fails,
and the common read-modify-write idiom

    ldh a, [rNR51] / or SOME_BIT / ldh [rNR51], a

silently clears bits the game never touched.

The ROM powers the APU on, writes a known value to every NRxx, and dumps the
raw read-back.  No channel is triggered, so nothing sampled here depends on
envelope, sweep or length timing.

Two controls make a blanket "return 0xFF" fix fail:
  - the unused registers FF15/FF1F/FF27-FF2F must read 0xFF (they already did)
  - wave RAM FF30-FF3F is fully readable and must read back exactly the 0xA5
    that was written, not 0xFF
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
ROM = SCRIPT_DIR / "sound_readback_test.gb"

FRAMES = 600
GAME_SRAM_SIZE = 0x2000

# (name, value the ROM wrote, expected read-back).  The expected value is
# (written & readable_bits) | unused_bits, i.e. what hardware returns.
EXPECTED = [
    ("NR10", 0x35, 0xB5),   # bit 7 unused
    ("NR11", 0x80, 0xBF),   # length write-only, duty readable
    ("NR12", 0xF0, 0xF0),   # fully readable
    ("NR13", 0x55, 0xFF),   # write-only
    ("NR14", 0x00, 0xBF),   # only bit 6 readable
    ("NR21", 0x40, 0x7F),
    ("NR22", 0xF0, 0xF0),
    ("NR23", 0x55, 0xFF),
    ("NR24", 0x00, 0xBF),
    ("NR30", 0x00, 0x7F),   # only bit 7 readable
    ("NR31", 0x55, 0xFF),   # write-only
    ("NR32", 0x20, 0xBF),   # only bits 6-5 readable
    ("NR33", 0x55, 0xFF),   # write-only
    ("NR34", 0x00, 0xBF),
    ("NR41", 0x15, 0xFF),   # write-only
    ("NR42", 0xF0, 0xF0),
    ("NR43", 0x55, 0x55),   # fully readable
    ("NR44", 0x00, 0xBF),
    ("NR50", 0x77, 0x77),   # fully readable
    ("NR51", 0xF3, 0xF3),   # fully readable
    ("NR52", 0x80, 0xF0),   # bits 6-4 unused; no channel triggered
]

R_UNUSED_AND = 0x15
R_UNUSED_OR = 0x16
R_WAVE_AND = 0x17
R_WAVE_OR = 0x18
R_DONE = 0x1F

WAVE_FILL = 0xA5


def run() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        gba, sav = tmp / "snd.gba", tmp / "snd.sav"
        r = subprocess.run(
            [sys.executable, str(COMPILER), "-e", str(EMULATOR),
             "-o", str(gba), str(ROM)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"ERROR: compile failed: {r.stderr}")
            sys.exit(2)
        try:
            r = subprocess.run(
                [str(RUNNER), str(gba), str(FRAMES), "/dev/null",
                 "--savefile", str(sav)],
                capture_output=True, text=True, timeout=300,
            )
        except subprocess.TimeoutExpired:
            print("ERROR: runner timed out")
            sys.exit(2)
        if r.returncode != 0:
            print(f"ERROR: runner exited {r.returncode}: {r.stderr[:500]}")
            sys.exit(2)
        data = sav.read_bytes()
    return data[len(data) - GAME_SRAM_SIZE:]


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"), (ROM, ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    res = run()
    print("results: " + " ".join(f"{b:02x}" for b in res[:32]))

    bad = []

    if res[R_DONE] != 0x5A:
        print(f"FAIL: the ROM did not run to completion "
              f"(done marker {res[R_DONE]:#04x}) -- results below are not "
              f"trustworthy")
        sys.exit(1)

    # Controls first.  If either of these is wrong the register comparison
    # below cannot be interpreted: a handler that returns 0xFF unconditionally
    # would "pass" many of the write-only registers for the wrong reason.
    if res[R_UNUSED_AND] != 0xFF or res[R_UNUSED_OR] != 0xFF:
        bad.append(f"control: the unused registers FF15/FF1F/FF27-FF2F read "
                   f"and={res[R_UNUSED_AND]:#04x} or={res[R_UNUSED_OR]:#04x}, "
                   f"expected 0xff/0xff -- unmapped I/O must read 0xff")
    if res[R_WAVE_AND] != WAVE_FILL or res[R_WAVE_OR] != WAVE_FILL:
        bad.append(f"control: wave RAM FF30-FF3F read "
                   f"and={res[R_WAVE_AND]:#04x} or={res[R_WAVE_OR]:#04x}, "
                   f"expected {WAVE_FILL:#04x} both ways -- wave RAM is fully "
                   f"readable and must not be masked")

    print("  register read-back:")
    for i, (name, wrote, want) in enumerate(EXPECTED):
        got = res[i]
        flag = "" if got == want else "   <-- wrong"
        print(f"    {name}: wrote {wrote:#04x}  read {got:#04x}  "
              f"expect {want:#04x}{flag}")
        if got == want:
            continue
        missing = want & ~got & 0xFF
        if missing:
            bad.append(f"{name} read {got:#04x}, expected {want:#04x} -- "
                       f"bits {missing:#04x} are write-only or unused and must "
                       f"read back as 1")
        else:
            bad.append(f"{name} read {got:#04x}, expected {want:#04x} -- "
                       f"readable bits were not preserved")

    if bad:
        for b in bad:
            print(f"FAIL: {b}")
        sys.exit(1)

    print("\nPASS: every sound register's write-only and unused bits read "
          "back as 1, and readable bits are preserved")
    sys.exit(0)


if __name__ == "__main__":
    main()
