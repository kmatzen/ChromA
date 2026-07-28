#!/usr/bin/env python3
"""Joypad interrupt / FF00 refresh regression test (issue #43).

Two related holes in the FF00 emulation:

  1. joy0serial -- the byte joy0_R hands back -- was recomputed only when the
     game WROTE FF00, so a game that sets the select bits once and then just
     polls saw frozen input forever.
  2. Nothing in the tree ever set IF bit 4, so the joypad interrupt never
     fired.  A game that HALTs with IE=0x10 waiting on input hung outright.

joypad_irq_test.gb runs three phases with an A press inside each: a polling
loop that never rewrites FF00 (the stale case), a polling loop that does (the
control, which worked before and after), and a HALT that only a joypad
interrupt can wake.
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
ROM = SCRIPT_DIR / "joypad_irq_test.gb"

FRAMES = 900
# One press inside each of the ROM's three phases.  The ROM counts its own
# phases off LY and reports the frame it reached (R_FRAME_LO/HI), so a
# misalignment shows up as a diagnostic rather than a mystery failure.
INPUTS = ["120:A", "420:A", "700:A"]
GAME_SRAM_SIZE = 0x2000

R_IRQ_COUNT = 0x00      # joypad interrupts taken (handler at $0060)
R_ACC_STALE = 0x01      # buttons seen while polling without rewriting FF00
R_ACC_FRESH = 0x02      # buttons seen while rewriting FF00 (control)
R_LOOP1_DONE = 0x03
R_LOOP2_DONE = 0x05
R_HALT = 0x06           # $01 entering HALT, $5A once woken
R_LAST_RAW = 0x08
R_FRAME_LO = 0x09
R_FRAME_HI = 0x0A
R_DONE = 0x0F

BTN_A = 0x01            # FF00 bit 0 with the button line selected


def run() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        gba, sav = tmp / "joy.gba", tmp / "joy.sav"
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
        for i in INPUTS:
            cmd += ["--input", i]
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


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"), (ROM, ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    res = run()
    frames = res[R_FRAME_LO] | (res[R_FRAME_HI] << 8)
    print("results: " + " ".join(f"{b:02x}" for b in res[:16]))
    print(f"  joypad IRQs={res[R_IRQ_COUNT]} stale-poll={res[R_ACC_STALE]:#04x} "
          f"control-poll={res[R_ACC_FRESH]:#04x} last FF00={res[R_LAST_RAW]:#04x} "
          f"frames counted={frames}")

    # The control has to work, or nothing below means anything: it says the
    # press reached the emulated joypad at all and landed inside a phase.
    if res[R_LOOP1_DONE] != 0x5A or res[R_LOOP2_DONE] != 0x5A:
        print(f"FAIL: the ROM did not finish both polling loops "
              f"(loop1={res[R_LOOP1_DONE]:#04x}, loop2={res[R_LOOP2_DONE]:#04x})")
        sys.exit(1)
    if res[R_ACC_FRESH] & BTN_A == 0:
        print(f"FAIL: control loop never saw A pressed even though it rewrote "
              f"FF00 before every read (got {res[R_ACC_FRESH]:#04x}) -- the "
              f"press did not reach the emulated joypad, so this run cannot "
              f"tell us anything about #43")
        sys.exit(1)

    bad = []

    if res[R_ACC_STALE] & BTN_A == 0:
        bad.append(f"a game that selects the button line once and then polls "
                   f"never sees the press (got {res[R_ACC_STALE]:#04x}) -- "
                   f"joy0serial is only recomputed on an FF00 write")

    if res[R_IRQ_COUNT] == 0:
        bad.append("no joypad interrupt was ever taken -- nothing sets IF "
                   "bit 4, so IE=0x10 handlers never run")

    if res[R_HALT] != 0x5A:
        bad.append(f"HALT with IE=0x10 was never woken "
                   f"(marker={res[R_HALT]:#04x}) -- a game waiting on input "
                   f"this way hangs outright")

    if res[R_DONE] != 0x5A and not bad:
        bad.append(f"the ROM did not reach its final marker "
                   f"({res[R_DONE]:#04x})")

    if bad:
        for b in bad:
            print(f"FAIL: {b}")
        sys.exit(1)

    print("\nPASS: polled input tracks the joypad, and the joypad interrupt "
          "fires and wakes HALT")
    sys.exit(0)


if __name__ == "__main__":
    main()
