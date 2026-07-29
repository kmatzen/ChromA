#!/usr/bin/env python3
"""Truncated savestate test (issue #51, item 4).

loadstate2() called rle_decompress() and threw the return value away.
rle_decompress stops early on truncated or corrupt input and reports how much
it actually produced, so a short decompression left the tail of the buffer
holding stale EWRAM -- and LoadState() then walked that as if it were chunk
tags.  Its bounds checks stop it overrunning, but it applies each chunk as it
goes and only bails at the first tag it cannot parse, so the chunks decoded
from the valid prefix are already live by then.  The load reports failure
while the emulator has quietly been left with somebody else's RAM.

Nothing in the record guards against this: `checksum` is a checksum of the
*ROM*, identifying which game the state belongs to, not of the payload.

The test takes a genuine savestate and rewrites its compressed stream so it
decompresses short, truncating at a point chosen to land just after the WRAM
chunk -- so a partial load is guaranteed to have applied WRAM before it gives
up.  The stream keeps its original length (the record's size fields are
cross-checked before decompression), with the tail replaced by 0x00 control
bytes: each is a one-byte literal run, so the padding consumes two input
bytes for every byte of output and the total falls short.

The ROM mirrors a WRAM tick counter into cart RAM, so "was WRAM applied" is
directly readable:

  valid state      quickload of the untouched state.  The counter is rewound,
                   which is the positive control -- it proves the quickload
                   path works, so a non-rewind below means the corrupt state
                   was rejected rather than that the keys did nothing.
  corrupt state    quickload of the truncated state.  The counter must NOT be
                   rewound: the length check has to reject the state before
                   LoadState sees it.
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
ROM = SCRIPT_DIR / "hdma_state_test.gb"

MAKE_FRAMES = 1200
SAVE_FRAME = 800
LOAD_FRAMES = 2700
LOAD_FRAME = 1200
GAME_SRAM_SIZE = 0x2000

R_TICK_LO = 0x02
R_TICK_HI = 0x03
R_DONE = 0x04

ROM_TITLE = b"HDMAST"
STATEHEADER_LEN = 48        # size,type,uncompressed_size,framecount,checksum,title[32]
WRAM_TAG = b"RAM "


def rle_decompress(src, max_out):
    """Mirror of src/rle.c, plus a record of (input_pos, output_len) after
    every token so the caller can pick a truncation point by output offset."""
    out = bytearray()
    marks = []
    sp = 0
    while sp < len(src) and len(out) < max_out:
        ctrl = src[sp]
        sp += 1
        if ctrl & 0x80:
            count = (ctrl - 0x80) + 3
            if sp >= len(src):
                break
            val = src[sp]
            sp += 1
            while count > 0 and len(out) < max_out:
                out.append(val)
                count -= 1
        else:
            count = ctrl + 1
            while count > 0 and sp < len(src) and len(out) < max_out:
                out.append(src[sp])
                sp += 1
                count -= 1
        marks.append((sp, len(out)))
    return bytes(out), marks


def find_state(sav):
    """Locate the STATESAVE record and return (offset, uncompressed, compressed)."""
    i = sav.find(ROM_TITLE)
    if i < 0:
        return None
    rec = i - 16                      # title sits 16 bytes into the header
    if rec < 0:
        return None
    size, typ = struct.unpack_from("<HH", sav, rec)
    if typ != 0:                      # STATESAVE
        return None
    unc, comp = struct.unpack_from("<II", sav, rec + STATEHEADER_LEN)
    return rec, unc, comp


def end_of_wram_chunk(blob):
    """Walk the chunk list and return the offset just past the WRAM chunk."""
    ptr = 0
    while ptr + 8 <= len(blob):
        tag = blob[ptr:ptr + 4]
        length = struct.unpack_from("<I", blob, ptr + 4)[0]
        nxt = ptr + 8 + (((length - 1) | 3) + 1)
        if tag == WRAM_TAG:
            return nxt
        if nxt <= ptr or nxt > len(blob):
            return None
        ptr = nxt
    return None


def corrupt(sav):
    """Return (corrupted_sav, description) or (None, reason)."""
    found = find_state(sav)
    if not found:
        return None, "no STATESAVE record found in the .sav"
    rec, unc, comp = found
    start = rec + STATEHEADER_LEN + 8
    stream = sav[start:start + comp]

    blob, marks = rle_decompress(stream, unc)
    if len(blob) != unc:
        return None, (f"the reference state does not even decompress fully "
                      f"({len(blob)} of {unc} bytes) -- the .sav is not what "
                      f"this test assumes")

    cut = end_of_wram_chunk(blob)
    if cut is None:
        return None, "could not find the WRAM chunk in the decompressed state"

    keep = None
    for in_pos, out_len in marks:
        if out_len >= cut:
            keep = in_pos
            break
    if keep is None or keep >= comp:
        return None, "the WRAM chunk ends too close to the end of the stream"

    out = bytearray(sav)
    for i in range(start + keep, start + comp):
        out[i] = 0x00                 # one-byte literal run: 2 in, 1 out
    return bytes(out), (f"kept {keep} of {comp} compressed bytes "
                        f"(WRAM chunk ends at uncompressed offset {cut} "
                        f"of {unc})")


def run(frames, inputs, sav_in=None):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        gba, sav = tmp / "hd.gba", tmp / "hd.sav"
        r = subprocess.run(
            [sys.executable, str(COMPILER), "-e", str(EMULATOR),
             "-o", str(gba), str(ROM)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"ERROR: compile failed: {r.stderr}")
            sys.exit(2)
        if sav_in is not None:
            sav.write_bytes(sav_in)
        cmd = [str(RUNNER), str(gba), str(frames), "/dev/null",
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
        return sav.read_bytes()


def ticks(sav):
    res = sav[len(sav) - GAME_SRAM_SIZE:]
    return res[R_TICK_LO] | (res[R_TICK_HI] << 8), res[R_DONE]


def main():
    for path, what in ((RUNNER, "mgba_runner"), (EMULATOR, "chroma.gba"),
                       (COMPILER, "goomba_compile.py"), (ROM, ROM.name)):
        if not path.exists():
            print(f"ERROR: {what} not found at {path}")
            sys.exit(2)

    reference = run(MAKE_FRAMES, [f"{SAVE_FRAME}:R+Select"])
    broken, note = corrupt(reference)
    if broken is None:
        print(f"ERROR: could not build the corrupt state: {note}")
        sys.exit(2)
    print(f"  truncation: {note}")

    good = run(LOAD_FRAMES, [f"{LOAD_FRAME}:R+Start"], sav_in=reference)
    bad_sav = run(LOAD_FRAMES, [f"{LOAD_FRAME}:R+Start"], sav_in=broken)

    good_ticks, good_done = ticks(good)
    bad_ticks, bad_done = ticks(bad_sav)
    print(f"  valid state    ticks={good_ticks} done={good_done:#04x}")
    print(f"  corrupt state  ticks={bad_ticks} done={bad_done:#04x}")

    bad = []
    for label, done in (("valid", good_done), ("corrupt", bad_done)):
        if done != 0x5A:
            print(f"FAIL: the '{label} state' run never finished set-up "
                  f"(done marker {done:#04x})")
            sys.exit(1)

    # Positive control: loading the untouched state must rewind the counter.
    # Without this, the corrupt run's un-rewound counter could simply mean the
    # quickload key never did anything.
    no_load, _ = ticks(run(LOAD_FRAMES, [], sav_in=reference))
    print(f"  no-load control ticks={no_load}")
    if good_ticks >= no_load:
        bad.append(f"control: loading the untouched state left the counter at "
                   f"{good_ticks}, no lower than the {no_load} of a run that "
                   f"never loaded -- the quickload did nothing, so the corrupt "
                   f"case below proves nothing")

    # Judge the corrupt run by how far it was rewound, not by whether it
    # merely beat the valid load's count.  A partial load rewinds WRAM almost
    # exactly as far as a full one, so "bad_ticks > good_ticks" is satisfied by
    # a difference of a handful of ticks and passes on a build with the bug.
    valid_rewind = no_load - good_ticks
    corrupt_rewind = no_load - bad_ticks
    print(f"  rewind: valid={valid_rewind} corrupt={corrupt_rewind}")
    if valid_rewind <= 0:
        bad.append(f"control: the valid load did not rewind the counter at all "
                   f"({good_ticks} vs {no_load}), so there is no scale to "
                   f"judge the corrupt run against")
    elif corrupt_rewind > valid_rewind // 4:
        bad.append(f"the truncated state was applied: the counter was rewound "
                   f"by {corrupt_rewind} ticks, against {valid_rewind} for a "
                   f"full load -- LoadState reached the WRAM chunk decoded "
                   f"from the valid prefix and applied it, so a partial state "
                   f"went live even though the load reports failure")

    if bad:
        for b in bad:
            print(f"FAIL: {b}")
        sys.exit(1)

    print("\nPASS: a savestate that does not decompress to its full length is "
          "rejected before any of it is applied")
    sys.exit(0)


if __name__ == "__main__":
    main()
