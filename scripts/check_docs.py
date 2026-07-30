#!/usr/bin/env python3
"""Check the drift-prone numbers in the docs against the source they describe.

Issue #64 was a list of documentation claims that had each been true once and
then quietly stopped being true: a register table naming the wrong ARM
registers, a cycle constant off by 16, a palette threshold that had been
retuned from 10 to 4, a mapper list promising accelerometer support that does
not exist, and hand-maintained IWRAM figures nobody re-measured.  Fixing the
text alone would buy a few months.  What keeps it fixed is deriving each of
those numbers from the source at CI time and failing when they disagree.

Every check below reads the authority (assembly source, JSON config, the ELF
map) and compares it with what the docs say.  Host-native: no toolchain, no
emulator, no ROM.  It is deliberately tolerant about *prose* -- it only pins
the specific figures and lists that have drifted.

Run: python3 scripts/check_docs.py
"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures = []
checks = 0


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def check(desc, ok, detail=""):
    global checks
    checks += 1
    if ok:
        print("  ok   %s" % desc)
    else:
        print("  FAIL %s" % desc)
        if detail:
            print("       %s" % detail)
        failures.append(desc)


# ---------------------------------------------------------------- cycle constants
def check_cycle_constants():
    equates = read("src/equates.h")
    m = re.search(r"^\s*CYC_SHIFT\s*=\s*(\d+)", equates, re.M)
    if not m:
        check("CYC_SHIFT found in src/equates.h", False)
        return
    cycle = 1 << int(m.group(1))
    arch = read("ARCHITECTURE.md")

    check("ARCHITECTURE CYCLE = %d" % cycle,
          re.search(r"`CYCLE`\s*=\s*%d\b" % cycle, arch) is not None,
          "src/equates.h has CYC_SHIFT=%s so CYCLE=%d" % (m.group(1), cycle))

    for name, lines in (("SINGLE_SPEED", 456), ("DOUBLE_SPEED", 912)):
        expect = lines * cycle
        m2 = re.search(r"`%s`\s*=\s*%d\s*×\s*CYCLE\s*=\s*([\d,]+)" % (name, lines), arch)
        if not m2:
            check("ARCHITECTURE documents %s" % name, False)
            continue
        got = int(m2.group(1).replace(",", ""))
        check("ARCHITECTURE %s = %d" % (name, expect), got == expect,
              "doc says %d, source gives %d x %d = %d" % (got, lines, cycle, expect))


# ------------------------------------------------------- per-scanline palette threshold
def check_palette_threshold():
    lcd = read("src/lcd.s")
    # The dispatch is: cmp r0,#N / ... / bgt pal_hdma_perscanline
    idx = lcd.find("pal_hdma_perscanline")
    if idx < 0:
        check("pal_hdma_perscanline found in src/lcd.s", False)
        return
    window = lcd[max(0, idx - 800):idx]
    m = re.findall(r"cmp\s+r0,\s*#(\d+)", window)
    if not m:
        check("threshold compare found before pal_hdma_perscanline", False)
        return
    threshold = int(m[-1])
    for doc in ("ARCHITECTURE.md", "KNOWN_ISSUES.md"):
        text = read(doc)
        bad = re.findall(r"[>≤]\s*(\d+)\s*(?:FF69\s+)?(?:visible-scanline|palette|mid-frame)", text)
        wrong = [b for b in bad if int(b) != threshold]
        check("%s per-scanline palette threshold = %d" % (doc, threshold), not wrong,
              "doc mentions %s, src/lcd.s compares against %d" % (sorted(set(wrong)), threshold))


# ------------------------------------------------------------------- opcode count
def check_opcode_count():
    # The SM83 has 11 unused base encodings.  This is a property of the ISA, not
    # of this codebase, so the list is the authority and the doc must match it.
    illegal = ["D3", "DB", "DD", "E3", "E4", "EB", "EC", "F4", "FC", "FD", "ED"]
    expect = 256 - len(illegal)
    compat = read("COMPATIBILITY.md")
    m = re.search(r"All (\d+) valid base opcodes", compat)
    check("COMPATIBILITY valid base opcode count = %d" % expect,
          m is not None and int(m.group(1)) == expect,
          "doc says %s" % (m.group(1) if m else "nothing"))


# ------------------------------------------------------------------- mapper list
def check_mappers():
    cart = read("src/cart.s")
    m = re.search(r"^mappertbl:(.*?)^mbcflagstbl:", cart, re.M | re.S)
    if not m:
        check("mappertbl found in src/cart.s", False)
        return
    inits = set()
    for line in m.group(1).splitlines():
        line = line.split("@")[0].strip()
        mm = re.match(r"\.word\s+(-?\w+)\s*,\s*(\w+init)", line)
        if mm:
            inits.add(mm.group(2))

    # Which families the source can actually instantiate.
    families = set()
    for init in inits:
        fam = re.match(r"(mbc\d|huc\d|mmm01)init", init)
        if fam:
            families.add(fam.group(1).upper())

    arch = read("ARCHITECTURE.md")
    section = arch.split("## ROM Banking")[-1]
    for fam in sorted(families):
        pretty = fam.replace("MBC", "MBC").replace("HUC", "HuC")
        present = pretty in section or fam in section
        check("ARCHITECTURE mapper list mentions %s" % pretty, present,
              "src/cart.s has %sinit but ARCHITECTURE's ROM Banking section does not mention it" % fam.lower())

    # MBC7 has no accelerometer/EEPROM code; the docs must not claim it does.
    # Only affirmative claims count -- "MBC7 is ROM-banking only (no tilt
    # sensor)" is the correct statement and mentions the same words.
    mappers = read("src/mappers.s")
    has_accel = re.search(r"accel|tilt|eeprom", mappers, re.I) is not None
    negated = re.compile(r"\b(no|not|without|never|lacks?)\b", re.I)
    for doc in ("ARCHITECTURE.md", "COMPATIBILITY.md", "README.md"):
        claims = []
        for line in read(doc).splitlines():
            if "MBC7" not in line:
                continue
            if not re.search(r"accelerometer|tilt|eeprom", line, re.I):
                continue
            if negated.search(line):
                continue          # documents the absence, which is correct
            if re.search(r"NOT FEASIBLE|NO TEST ROMS", line):
                continue          # a gap entry, not a support claim
            claims.append(line.strip())
        check("%s does not claim MBC7 accelerometer support" % doc,
              has_accel or not claims,
              "src/mappers.s implements no accelerometer/EEPROM; doc says: %s" % claims)


# --------------------------------------------------------------------- test counts
def check_test_counts():
    cfg = json.loads(read("test_roms/test_config.json"))
    visual = [k for k, v in cfg.items() if not v.get("skip_visual")]
    menu = len(re.findall(r"^def test_", read("test_roms/test_menu.py"), re.M))
    readme = read("README.md")

    m = re.search(r"\((\d+) visual \+ (\d+) menu/behavioral", readme)
    if not m:
        check("README documents the test counts", False)
        return
    check("README visual test count = %d" % len(visual),
          int(m.group(1)) == len(visual),
          "README says %s, test_config.json has %d entries without skip_visual"
          % (m.group(1), len(visual)))
    check("README menu test count = %d" % menu,
          int(m.group(2)) == menu,
          "README says %s, test_menu.py defines %d test functions" % (m.group(2), menu))

    acc = json.loads(read("test_roms/accuracy_config.json"))
    n_tests = len(acc["tests"])
    n_unusable = len(acc["unusable"])
    xfail = sum(1 for t in acc["tests"].values() if t.get("expected_fail"))
    m = re.search(r"\*\*(\d+) pass, (\d+) expected-fail, (\d+) not covered\*\*", readme)
    if not m:
        check("README documents the accuracy suite tally", False)
        return
    check("README accuracy tally matches accuracy_config.json",
          int(m.group(1)) == n_tests - xfail and int(m.group(2)) == xfail
          and int(m.group(3)) == n_unusable,
          "README says %s pass / %s xfail / %s uncovered; config has %d / %d / %d"
          % (m.group(1), m.group(2), m.group(3), n_tests - xfail, xfail, n_unusable))


# ------------------------------------------------------------------- line references
def check_no_line_refs():
    # Line numbers in prose rot on the next edit.  formal/README.md was the
    # worst offender (#64); keep it symbol-referenced.
    for doc in ("formal/README.md",):
        text = read(doc)
        refs = re.findall(r"src/\w+\.[sch]:\d+", text)
        check("%s uses symbol names, not line numbers" % doc, not refs,
              "found %s" % sorted(set(refs)))


# ----------------------------------------------------------------------- branding
def check_branding():
    # The fork's own name should appear in user-visible strings; "Goomba Color"
    # on the bad-ROM screen is visible in the browser demo (#64, #62).
    main_c = read("src/main.c")
    strings = re.findall(r'drawtext\s*\([^,]+,\s*"([^"]*)"', main_c)
    bad = [s for s in strings if "Goomba" in s]
    check("src/main.c UI strings are not Goomba-branded", not bad,
          "found %s" % bad)


# ------------------------------------------------------------------- the tutorial
def check_tutorial():
    """docs/tutorial.html is published teaching material, so wrong facts in it
    are worse than wrong facts in an internal note (#63).  Two things there are
    mechanically checkable: the register map it draws, and the symbol names it
    quotes."""
    equates = read("src/equates.h")
    regs = dict(re.findall(r"^\s*(\w+)\s*\.req\s*(r\d+)", equates, re.M))
    tut = read("docs/tutorial.html")

    # The interactive register diagram: 'PC': { arm: 'r9', ... }
    diagram = dict(re.findall(r"^\s*(\w+):\s*\{\s*arm:\s*'(r\d+)'", tut, re.M))
    expect = {
        "AF": regs.get("gb_a"), "BC": regs.get("gb_bc"), "DE": regs.get("gb_de"),
        "HL": regs.get("gb_hl"), "SP": regs.get("gb_sp"), "PC": regs.get("gb_pc"),
        "CYC": regs.get("cycles"),
    }
    for name, want in expect.items():
        got = diagram.get(name)
        check("tutorial register diagram %s = %s" % (name, want),
              want is not None and got == want,
              "tutorial says %s, src/equates.h says %s" % (got, want))

    # The fetch-execute sample used r6/r12/r9 for PC/table/cycles; the real
    # macro uses gb_pc/gb_optbl/cycles.  Require it to name them symbolically,
    # which is both correct and immune to a future renumbering.
    sample = re.search(r"the `fetch` macro.*?</pre>", tut, re.S)
    check("tutorial fetch sample names gb_pc/gb_optbl/cycles",
          sample is not None
          and all(n in sample.group(0) for n in ("gb_pc", "gb_optbl", "cycles")),
          "the sample should quote src/gbz80mac.h's `fetch`, not invented registers")

    # Every XGB_* buffer the tutorial names must exist in the source.
    src = "".join(read(os.path.join("src", f)) for f in sorted(os.listdir(os.path.join(ROOT, "src")))
                  if f.endswith((".s", ".h", ".c")))
    named = set(re.findall(r"\bXGB_\w+", tut))
    missing = sorted(n for n in named if n not in src)
    check("tutorial only names buffers that exist in src/", not missing,
          "no such symbol: %s" % missing)


def main():
    print("=== Documentation Consistency ===")
    check_cycle_constants()
    check_palette_threshold()
    check_opcode_count()
    check_mappers()
    check_test_counts()
    check_tutorial()
    check_no_line_refs()
    check_branding()
    print()
    if failures:
        print("%d of %d documentation checks FAILED:" % (len(failures), checks))
        for f in failures:
            print("  - %s" % f)
        print()
        print("The docs describe the source; when they disagree the source wins.")
        print("Update the doc (or the source, if the doc was describing intent).")
        return 1
    print("All %d documentation checks OK" % checks)
    return 0


if __name__ == "__main__":
    sys.exit(main())
