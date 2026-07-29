#!/usr/bin/env python3
"""Sound post-boot state and wave RAM bank test (issue #55, items 4 and 3).

Item 4 -- post-boot register values.  A cart started without a boot ROM has to
find the sound registers in the state the DMG boot ROM leaves behind.
Sound_reset wrote zero to every PSG register and said so in its own comments
("should read 0xF3BF").  Once the read-back masks landed (item 1), all but two
of the post-boot values fell out of a zeroed register anyway, because they are
made up entirely of write-only and unused bits.  The two that do not are
NR11's duty (boot leaves 10, so it reads 0xBF rather than 0x3F) and NR12's
envelope (0xF3 rather than 0x00).

Item 3 -- wave RAM writes while channel 3 plays.  The GBA keeps two wave
banks: SOUND3CNT_L bit 6 selects the one that plays and 0x04000090-9F exposes
the other.  chroma flips that bit along with NR30 bit 7, so wave data written
while the channel is off lands in the bank that starts playing when it is
switched on -- the double buffer Alleyway relies on.  The GB has one buffer,
so a write made while the channel is *playing* has to reach the live bank too,
and it did not; it went to the idle one.  CGB games that stream wave data
without toggling NR30 kept hearing the previous waveform.

The ROM orders the bank probe so the two banks hold different bytes, which is
what makes the failure visible: it fills the idle bank with 0x00, switches
channel 3 on so that bank goes live, streams 0xA5 through the window while it
plays, then switches channel 3 off so the window swings back to the bank that
was playing and reads it.  0xA5 only appears there if the streaming write
reached the live bank.
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
ROM = SCRIPT_DIR / "sound_state_test.gb"

FRAMES = 600
GAME_SRAM_SIZE = 0x2000

# Post-boot values, from the Pan Docs "Hardware Registers" table.  These are
# what the register reads *after* the DMG boot ROM has run, which is the state
# a directly-booted cart has to be handed.
POST_BOOT = [
    ("NR10", 0x80),
    ("NR11", 0xBF),   # duty 10 from the boot ROM, length write-only
    ("NR12", 0xF3),   # fully readable, so this one has to be set for real
    ("NR13", 0xFF),   # write-only
    ("NR14", 0xBF),
    ("NR21", 0x3F),
    ("NR22", 0x00),
    ("NR23", 0xFF),   # write-only
    ("NR24", 0xBF),
    ("NR30", 0x7F),
    ("NR31", 0xFF),   # write-only
    ("NR32", 0x9F),
    ("NR33", 0xFF),   # write-only
    ("NR34", 0xBF),
    ("NR41", 0xFF),   # write-only
    ("NR42", 0x00),
    ("NR43", 0x00),
    ("NR44", 0xBF),
    ("NR50", 0x77),
    ("NR51", 0xF3),
    # Pan Docs lists 0xF1 here: bit 0 reports channel 1 still running from the
    # boot ROM's start-up chime.  chroma has no boot ROM and never triggers a
    # channel, and NR52's low nibble is hardware status the GBA computes from
    # its own channel state -- it cannot be written.  Expect 0xF0, and treat
    # the missing bit as a documented deviation rather than pretend otherwise.
    ("NR52", 0xF0),
]

R_WAVE_PLAYING_AND = 0x20
R_WAVE_PLAYING_OR = 0x21
R_WAVE_BUFFER_AND = 0x22
R_WAVE_BUFFER_OR = 0x23
R_DONE = 0x3F

STREAMED = 0xA5     # written while channel 3 is playing
BUFFERED = 0x5A     # written while channel 3 is off, then switched on


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
    print("results: " + " ".join(f"{b:02x}" for b in res[:0x24]))

    if res[R_DONE] != 0x5A:
        print(f"FAIL: the ROM did not run to completion (done marker "
              f"{res[R_DONE]:#04x}) -- results below are not trustworthy")
        sys.exit(1)

    bad = []

    print("  post-boot register state:")
    for i, (name, want) in enumerate(POST_BOOT):
        got = res[i]
        flag = "" if got == want else "   <-- wrong"
        print(f"    {name}: read {got:#04x}  expect {want:#04x}{flag}")
        if got != want:
            bad.append(f"{name} reads {got:#04x} at boot, expected "
                       f"{want:#04x} -- Sound_reset does not leave the "
                       f"register in its post-boot state")

    # The double-buffer control comes first: it is the behaviour that already
    # worked, so if it broke, the streaming result below is being produced by
    # a fix that just moved the bug to the other bank.
    buf_and, buf_or = res[R_WAVE_BUFFER_AND], res[R_WAVE_BUFFER_OR]
    print(f"  off/on double buffer: and={buf_and:#04x} or={buf_or:#04x} "
          f"expect {BUFFERED:#04x}")
    if buf_and != BUFFERED or buf_or != BUFFERED:
        bad.append(f"control: wave data written with channel 3 off read back "
                   f"and={buf_and:#04x} or={buf_or:#04x}, expected "
                   f"{BUFFERED:#04x} both ways -- the NR30 bank flip that "
                   f"Alleyway depends on regressed")

    play_and, play_or = res[R_WAVE_PLAYING_AND], res[R_WAVE_PLAYING_OR]
    print(f"  streamed while playing: and={play_and:#04x} or={play_or:#04x} "
          f"expect {STREAMED:#04x}")
    if play_and != STREAMED or play_or != STREAMED:
        detail = ""
        if play_and == 0x00 and play_or == 0x00:
            detail = (" -- the bank that was playing still holds the 0x00 it "
                      "was filled with, so the write went to the idle bank")
        bad.append(f"wave data streamed while channel 3 was playing read back "
                   f"and={play_and:#04x} or={play_or:#04x}, expected "
                   f"{STREAMED:#04x} both ways{detail}")

    if bad:
        for b in bad:
            print(f"FAIL: {b}")
        sys.exit(1)

    print("\nPASS: sound registers come up in their post-boot state, and wave "
          "RAM writes reach the playing bank without breaking the off/on "
          "double buffer")
    sys.exit(0)


if __name__ == "__main__":
    main()
