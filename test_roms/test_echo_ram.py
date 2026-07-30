#!/usr/bin/env python3
"""Echo RAM regression test (issue #46).

0xE000-0xFDFF mirrors WRAM 0xC000-0xDDFF.  readmem/writemem fold the echo
through IO_R/IO_W correctly, but the *direct memmap* paths do not go through
those: push16/pop16/popAF (PUSH, POP, CALL, RET, RST) and encodePC (executing
code) index memmap_tbl by the top address nibble alone.  Entries 14 and 15
(0xE000/0xF000) were initialised to XGB_HRAM-0xFF80, and XGB_HRAM sits
immediately after XGB_RAM's 0x2000 bytes, so 0xE000 resolved to XGB_RAM+0x80
and 0xF000 to XGB_RAM+0x1080 -- every stack access and every instruction fetch
in echo RAM landed 0x80 bytes too high in WRAM.

Entry 14 could simply be repointed.  Entry 15 could not: 0xF000-0xFFFF also
holds OAM, IO and HRAM, and SP=0xFFFE and HRAM-resident code are universal, so
that entry has to keep serving 0xFE00-0xFFFF.  The direct paths instead
range-check 0xF000-0xFDFF and take the echo base from `echomap`.  So this test
also pins the 0xFE00 boundary and the HRAM cases: a range test that is one
page short loses the top of the echo, and one that is too wide moves every
game's stack out of HRAM and into WRAM.

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

R_FPUSH_LO, R_FPUSH_HI = 0x08, 0x09    # D000/D001 after PUSH BC at SP=$F002
R_FALIAS_LO, R_FALIAS_HI = 0x0A, 0x0B  # D080/D081, the +0x80 aliases
R_FPOP_LO, R_FPOP_HI = 0x0C, 0x0D      # C,B after POP BC at SP=$F100
R_FEXEC = 0x0E                         # written by the stub CALLed at $F200
R_DONE = 0x0F                          # $5A once every subtest has run
R_FREAD = 0x10                         # LD A,($F300) -- readmem control

R_TOP_LO, R_TOP_HI = 0x11, 0x12        # DDFE/DDFF after PUSH BC at SP=$FE00
R_TOPALIAS_LO, R_TOPALIAS_HI = 0x13, 0x14   # DE7E/DE7F, the +0x80 aliases
R_POPAF = 0x15                         # A after POP AF at SP=$F400

R_HPUSH_LO, R_HPUSH_HI = 0x16, 0x17    # FFFC/FFFD after PUSH BC at SP=$FFFE
R_HPOP_LO, R_HPOP_HI = 0x18, 0x19      # C,B after POP BC at SP=$FFFC
R_HEXEC = 0x1A                         # written by the stub CALLed at $FF90


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
    print("results: " + " ".join(f"{b:02x}" for b in res[:0x1B]))

    # The ROM has to have got all the way to the end, or the assertions below
    # would pass on a cleared region rather than on real results.  It also
    # cannot get here if executing from HRAM broke: that derails PC into
    # cleared WRAM and the marker is never written.
    if res[R_DONE] != 0x5A:
        print(f"FAIL: the test ROM did not run to completion "
              f"(marker={res[R_DONE]:#04x}, expected 0x5a) -- if the earlier "
              f"results look right, suspect CALL $FF90 (HRAM execution)")
        sys.exit(1)

    # The readmem path already folded the echo correctly, before and after the
    # fix.  If these fail, the ROM or the harness is broken, not memmap_tbl.
    for off, want, src in ((R_READ, 0x77, "$E300"), (R_FREAD, 0x88, "$F300")):
        if res[off] != want:
            print(f"FAIL: control read LD A,({src}) returned {res[off]:#04x}, "
                  f"expected {want:#04x} -- the ROM itself is not doing what "
                  f"it claims")
            sys.exit(1)

    bad = []

    def check_push(name, addr, alias_addr, lo, hi, alo, ahi, want):
        got = (res[lo], res[hi])
        alias = (res[alo], res[ahi])
        if got != want:
            detail = (f" -- it landed at {alias_addr} instead, 0x80 bytes high"
                      if alias == want else "")
            bad.append(f"{name} did not reach WRAM {addr} "
                       f"(got {got[0]:#04x},{got[1]:#04x}){detail}")
        elif alias != (0x00, 0x00):
            bad.append(f"{name} also wrote {alias_addr} "
                       f"({alias[0]:#04x},{alias[1]:#04x}), which it must "
                       f"not touch")

    def check_pop(name, addr, alias_addr, lo, hi, want, alias_want):
        got = (res[lo], res[hi])
        if got != want:
            detail = (f" -- it read {alias_addr} instead, 0x80 bytes high"
                      if got == alias_want else "")
            bad.append(f"{name} did not read WRAM {addr} "
                       f"(got {got[0]:#04x},{got[1]:#04x}){detail}")

    # --- E000-EFFF: memmap_tbl entry 14 ---
    check_push("PUSH BC with SP=$E002", "$C000/$C001", "$C080/$C081",
               R_PUSH_LO, R_PUSH_HI, R_ALIAS_LO, R_ALIAS_HI, (0x34, 0x12))
    check_pop("POP BC with SP=$E100", "$C100/$C101", "$C180/$C181",
              R_POP_LO, R_POP_HI, (0xAA, 0xBB), (0xCC, 0xDD))
    if res[R_EXEC] != 0x5A:
        detail = (" -- it executed the stub at $C280 instead, 0x80 bytes high"
                  if res[R_EXEC] == 0xA5 else "")
        bad.append(f"CALL $E200 did not execute the code at WRAM $C200 "
                   f"(got {res[R_EXEC]:#04x}){detail}")

    # --- F000-FDFF: the echomap range ---
    check_push("PUSH BC with SP=$F002", "$D000/$D001", "$D080/$D081",
               R_FPUSH_LO, R_FPUSH_HI, R_FALIAS_LO, R_FALIAS_HI, (0x78, 0x56))
    check_pop("POP BC with SP=$F100", "$D100/$D101", "$D180/$D181",
              R_FPOP_LO, R_FPOP_HI, (0xAA, 0xBB), (0xCC, 0xDD))
    if res[R_FEXEC] != 0x5A:
        detail = (" -- it executed the stub at $D280 instead, 0x80 bytes high"
                  if res[R_FEXEC] == 0xA5 else "")
        bad.append(f"CALL $F200 did not execute the code at WRAM $D200 "
                   f"(got {res[R_FEXEC]:#04x}){detail}")

    # The last two echo bytes: a range test that stops a page early sends
    # these to the alias, one that is right keeps them in WRAM.
    check_push("PUSH BC with SP=$FE00", "$DDFE/$DDFF", "$DE7E/$DE7F",
               R_TOP_LO, R_TOP_HI, R_TOPALIAS_LO, R_TOPALIAS_HI, (0xBC, 0x9A))

    if res[R_POPAF] != 0x3C:
        detail = (" -- it read $D481 instead, 0x80 bytes high"
                  if res[R_POPAF] == 0xA5 else "")
        bad.append(f"POP AF with SP=$F400 did not read A from WRAM $D401 "
                   f"(got {res[R_POPAF]:#04x}){detail}")

    # --- FE00-FFFF must stay out of the echo ---
    hpush = (res[R_HPUSH_LO], res[R_HPUSH_HI])
    if hpush != (0x21, 0x43):
        bad.append(f"PUSH BC with SP=$FFFE did not reach HRAM $FFFC/$FFFD "
                   f"(got {hpush[0]:#04x},{hpush[1]:#04x}) -- the echo range "
                   f"test is too wide and the stack has moved into WRAM")
    hpop = (res[R_HPOP_LO], res[R_HPOP_HI])
    if hpop != (0x21, 0x43):
        bad.append(f"POP BC with SP=$FFFC did not read HRAM $FFFC/$FFFD "
                   f"(got {hpop[0]:#04x},{hpop[1]:#04x})")
    if res[R_HEXEC] != 0x5A:
        bad.append(f"CALL $FF90 did not execute the stub in HRAM "
                   f"(got {res[R_HEXEC]:#04x})")

    if bad:
        for b in bad:
            print(f"FAIL: {b}")
        print("\nmemmap_tbl entry 14 (0xE000) must be XGB_RAM-0xE000 and the "
              "direct memmap paths must resolve 0xF000-0xFDFF through echomap "
              "while leaving 0xFE00-0xFFFF to entry 15 -- they do not fold "
              "echo RAM themselves (#46)")
        sys.exit(1)

    print("\nPASS: PUSH, POP, POP AF and instruction fetch resolve to WRAM "
          "across 0xE000-0xFDFF, and 0xFE00-0xFFFF still reaches HRAM")
    sys.exit(0)


if __name__ == "__main__":
    main()
