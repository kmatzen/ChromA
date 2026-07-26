#!/usr/bin/env python3
"""Cross-game SRAM ownership regression test (issue #48).

There is only one write-through region in GBA cart SRAM, so only one GB
game's battery save can live in it at a time.  get_saved_sram() used to hand
that region to whatever game booted, without ever comparing the config's
sram_owner field against checksum_this() -- register_sram_owner() and
no_sram_owner() had zero call sites.  Play game A, boot game B on the same
cart, and B was handed A's save bytes and destroyed them on its first write.

This drives two purpose-built 8KB-SRAM carts (sram_owner_test_a/b.gb) that
differ only in an ID tag and a signature byte, across one shared .sav:

    run 1: boot A   -> A stamps its signature into the region
    run 2: boot B   -> B must NOT see A's signature; A's save is archived
    run 3: boot A   -> A must see its OWN signature again, restored

Each ROM copies the 16 bytes it inherited at A000 to A100 before overwriting
them, so the .sav records what each boot was handed.

Checks after each run:
  * the booting game's signature is in the region (proves the ROM ran and
    write-through reached GBA SRAM)
  * the echo shows what that boot inherited
  * the config record's sram_checksum names the game that just booted
  * the savestate heap holds an SRAMSAVE archive for the displaced game
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
ROM_A = SCRIPT_DIR / "sram_owner_test_a.gb"
ROM_B = SCRIPT_DIR / "sram_owner_test_b.gb"

FRAMES = 300
GAME_SRAM_SIZE = 0x2000     # 8KB, from the carts' RAM-size header byte
SIG_OFF = 0x0000            # where each ROM stamps its signature
ECHO_OFF = 0x0100           # where each ROM copies what it inherited
SIG_LEN = 16

SIG_A = bytes([0xA1]) * SIG_LEN
SIG_B = bytes([0xB2]) * SIG_LEN

STATESAVE, SRAMSAVE, CONFIGSAVE = 0, 1, 2
HEADER_LEN = 48             # sizeof(stateheader)
SH_CHECKSUM_OFF = 12        # stateheader.checksum (offset 8 is framecount)
CFG_OWNER_OFF = 8           # configdata.sram_checksum (same struct, remapped)


def checksum_this(rom: bytes) -> int:
    """Mirror of checksum_this() in src/sram.c: 4 bytes every 128."""
    total = 0
    for i in range(128):
        o = i * 128
        total = (total + int.from_bytes(rom[o:o + 4], "little")) & 0xFFFFFFFF
    return total


def compile_rom(rom_path: Path, out_path: Path) -> bool:
    r = subprocess.run(
        [sys.executable, str(COMPILER), "-e", str(EMULATOR),
         "-o", str(out_path), str(rom_path)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"ERROR: compile failed: {r.stderr}")
        return False
    return True


def run(gba: Path, sav: Path) -> bytes:
    """Boot `gba` against `sav` and return the resulting SRAM image."""
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
    return sav.read_bytes()


def walk_heap(data: bytes):
    """Yield (type, checksum, size) for each record in the savestate heap.

    The heap starts with a 4-byte magic and is a run of stateheader-prefixed
    records terminated by a zero size.
    """
    off = 4
    while off + HEADER_LEN <= len(data):
        size = int.from_bytes(data[off:off + 2], "little")
        if size == 0:
            return
        rtype = int.from_bytes(data[off + 2:off + 4], "little")
        checksum = int.from_bytes(
            data[off + SH_CHECKSUM_OFF:off + SH_CHECKSUM_OFF + 4], "little")
        yield rtype, checksum, size, off
        off += size


def config_owner(data: bytes):
    for rtype, _checksum, _size, off in walk_heap(data):
        if rtype == CONFIGSAVE:
            return int.from_bytes(
                data[off + CFG_OWNER_OFF:off + CFG_OWNER_OFF + 4], "little")
    return None


def sram_archives(data: bytes):
    return {c for t, c, _s, _o in walk_heap(data) if t == SRAMSAVE}


def region(data: bytes):
    base = len(data) - GAME_SRAM_SIZE
    sig = data[base + SIG_OFF:base + SIG_OFF + SIG_LEN]
    echo = data[base + ECHO_OFF:base + ECHO_OFF + SIG_LEN]
    return sig, echo


def describe(name, data, ck_a, ck_b):
    sig, echo = region(data)
    owner = config_owner(data)
    names = {ck_a: "A", ck_b: "B", 0: "none", None: "no config"}
    print(f"  {name}: signature={sig[:4].hex()}... echo={echo[:4].hex()}... "
          f"owner={names.get(owner, hex(owner) if owner else owner)} "
          f"archives={sorted(names.get(c, hex(c)) for c in sram_archives(data))}")
    return sig, echo, owner


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"),
                       (ROM_A, ROM_A.name), (ROM_B, ROM_B.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    ck_a = checksum_this(ROM_A.read_bytes())
    ck_b = checksum_this(ROM_B.read_bytes())
    if ck_a == ck_b:
        print("ERROR: the two test ROMs have the same checksum_this() value; "
              "the emulator cannot tell them apart")
        sys.exit(2)
    print(f"checksums: A={ck_a:#010x} B={ck_b:#010x}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        gba_a, gba_b, sav = tmp / "a.gba", tmp / "b.gba", tmp / "shared.sav"
        if not compile_rom(ROM_A, gba_a) or not compile_rom(ROM_B, gba_b):
            sys.exit(2)

        print("\nrun 1: boot A on a fresh save")
        d1 = run(gba_a, sav)
        sig1, echo1, owner1 = describe("run 1", d1, ck_a, ck_b)
        arch1 = sram_archives(d1)

        print("run 2: boot B on the same save")
        d2 = run(gba_b, sav)
        sig2, echo2, owner2 = describe("run 2", d2, ck_a, ck_b)
        arch2 = sram_archives(d2)

        print("run 3: boot A again on the same save")
        d3 = run(gba_a, sav)
        sig3, echo3, owner3 = describe("run 3", d3, ck_a, ck_b)
        arch3 = sram_archives(d3)

    bad = []

    # Sanity: each ROM ran and its writes reached GBA cart SRAM.
    if sig1 != SIG_A:
        bad.append("run 1: A's signature is not in the write-through region "
                   "-- the ROM did not run or write-through is broken")
    if sig2 != SIG_B:
        bad.append("run 2: B's signature is not in the write-through region")
    if sig3 != SIG_A:
        bad.append("run 3: A's signature is not in the write-through region")

    # The bug: B is handed A's save and destroys it.
    if echo2 == SIG_A:
        bad.append("run 2: B inherited A's save data -- the write-through "
                   "region was handed over without an ownership check (#48)")

    # The fix: A's save was archived on the way out and restored on return.
    if echo3 == SIG_B:
        bad.append("run 3: A inherited B's save data -- ownership handoff "
                   "did not happen on the way back")
    elif echo3 != SIG_A:
        bad.append(f"run 3: A did not get its own save back "
                   f"(echo={echo3[:4].hex()}..., expected {SIG_A[:4].hex()}...) "
                   f"-- the SRAMSAVE archive was not restored")

    # The displaced save must actually be archived, keyed by its own ROM
    # checksum -- and reclaimed once its owner takes it back.
    if arch1:
        bad.append(f"run 1: unexpected SRAMSAVE archive on a fresh save "
                   f"({[hex(c) for c in sorted(arch1)]})")
    if ck_a not in arch2:
        bad.append("run 2: A's displaced save was not archived as an SRAMSAVE "
                   "record -- it is gone for good")
    if ck_b not in arch3:
        bad.append("run 3: B's displaced save was not archived as an SRAMSAVE "
                   "record -- it is gone for good")
    if ck_a in arch3:
        bad.append("run 3: A's archive was left behind after being restored, "
                   "so the heap space is never reclaimed")

    # Ownership must be recorded, and must follow whoever booted last.
    for label, owner, expect, who in (("run 1", owner1, ck_a, "A"),
                                      ("run 2", owner2, ck_b, "B"),
                                      ("run 3", owner3, ck_a, "A")):
        if owner is None:
            bad.append(f"{label}: no config record was written, so ownership "
                       f"cannot survive a power cycle")
        elif owner != expect:
            bad.append(f"{label}: config sram_checksum is {owner:#010x}, "
                       f"expected {expect:#010x} (game {who})")

    if bad:
        for b in bad:
            print(f"FAIL: {b}")
        sys.exit(1)

    print("\nPASS: the write-through region is handed over by owner checksum; "
          "displaced saves are archived and restored")
    sys.exit(0)


if __name__ == "__main__":
    main()
