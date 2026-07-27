#!/usr/bin/env python3
"""Echo RAM regression test (issue #46).

0xE000-0xFDFF mirrors WRAM 0xC000-0xDDFF.  readmem/writemem fold the echo
through IO_R/IO_W correctly, but the *direct memmap* paths do not go through
those: push16/pop16/popAF (PUSH, POP, CALL, RET, RST) and encodePC (executing
code) index memmap_tbl by the top address nibble alone.  Entry 14 (0xE000) was
initialised to XGB_HRAM-0xFF80, and XGB_HRAM sits immediately after XGB_RAM's
0x2000 bytes, so 0xE000 resolved to XGB_RAM+0x80 -- every stack access and
every instruction fetch in echo RAM landed 0x80 bytes too high in WRAM.

echo_ram_test.gb plants a different value at the correct target and at the
+0x80 target for each path, so the resulting .sav says which one was hit.
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
ROM = SCRIPT_DIR / "echo_ram_test.gb"

FRAMES = 300
GAME_SRAM_SIZE = 0x2000     # 8KB, from the cart's RAM-size header byte

# Result offsets within the write-through region, matching echo_ram_test.asm.
R_PUSH_LO, R_PUSH_HI = 0x00, 0x01      # C000/C001 after PUSH BC at SP=$E002
R_ALIAS_LO, R_ALIAS_HI = 0x02, 0x03    # C080/C081, the +0x80 aliases
R_POP_LO, R_POP_HI = 0x04, 0x05        # C,B after POP BC at SP=$E100
R_EXEC = 0x06                          # written by the stub CALLed at $E200
R_READ = 0x07                          # LD A,($E300) -- the readmem control
R_DONE = 0x0F                          # $5A once every subtest has run


def run() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        gba, sav = tmp / "echo.gba", tmp / "echo.sav"
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
                capture_output=True, text=True, timeout=180,
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
    print("results: " + " ".join(f"{b:02x}" for b in res[:16]))

    # The ROM has to have got all the way to the end, or the assertions below
    # would pass on a cleared region rather than on real results.
    if res[R_DONE] != 0x5A:
        print(f"FAIL: the test ROM did not run to completion "
              f"(marker={res[R_DONE]:#04x}, expected 0x5a)")
        sys.exit(1)

    # The readmem path already folded the echo correctly, before and after the
    # fix.  If this fails, the ROM or the harness is broken, not memmap_tbl.
    if res[R_READ] != 0x77:
        print(f"FAIL: control read LD A,($E300) returned {res[R_READ]:#04x}, "
              f"expected 0x77 -- the ROM itself is not doing what it claims")
        sys.exit(1)

    bad = []

    push = (res[R_PUSH_LO], res[R_PUSH_HI])
    alias = (res[R_ALIAS_LO], res[R_ALIAS_HI])
    if push != (0x34, 0x12):
        detail = (" -- it landed at $C080 instead, 0x80 bytes high"
                  if alias == (0x34, 0x12) else "")
        bad.append(f"PUSH BC with SP=$E002 did not reach WRAM $C000/$C001 "
                   f"(got {push[0]:#04x},{push[1]:#04x}){detail}")
    elif alias != (0x00, 0x00):
        bad.append(f"PUSH BC also wrote $C080/$C081 "
                   f"({alias[0]:#04x},{alias[1]:#04x}), which it must not touch")

    pop = (res[R_POP_LO], res[R_POP_HI])
    if pop != (0xAA, 0xBB):
        detail = (" -- it read $C180/$C181 instead, 0x80 bytes high"
                  if pop == (0xCC, 0xDD) else "")
        bad.append(f"POP BC with SP=$E100 did not read WRAM $C100/$C101 "
                   f"(got {pop[0]:#04x},{pop[1]:#04x}){detail}")

    if res[R_EXEC] != 0x5A:
        detail = (" -- it executed the stub at $C280 instead, 0x80 bytes high"
                  if res[R_EXEC] == 0xA5 else "")
        bad.append(f"CALL $E200 did not execute the code at WRAM $C200 "
                   f"(got {res[R_EXEC]:#04x}){detail}")

    if bad:
        for b in bad:
            print(f"FAIL: {b}")
        print("\nmemmap_tbl entry 14 (0xE000) must be XGB_RAM-0xE000; the "
              "direct memmap paths do not fold echo RAM themselves (#46)")
        sys.exit(1)

    print("\nPASS: PUSH, POP and instruction fetch in echo RAM all resolve to "
          "WRAM bank 0")
    sys.exit(0)


if __name__ == "__main__":
    main()
