#!/usr/bin/env python3
"""Generate the game compatibility table from the regression suite's own config.

Issue #138 item 5: COMPATIBILITY.md exists and check_docs.py keeps its numbers
honest, but there was no generated game -> status -> notes table anywhere a
reader would find it.

The table is generated rather than written, and generated from
test_roms/test_config.json specifically, because that file is already the
compatibility database in practice: every game in it is run by CI on each
push, `expected_fail` records whether its captures are pinned, and
`xfail_reason` records why when they are not.  Writing the table by hand would
mean inventing statuses that nothing verifies; deriving it means the table
cannot claim a game works unless CI is actually checking that it does.

Usage:
    python3 scripts/gen_compat_table.py           # rewrite README + demo page
    python3 scripts/gen_compat_table.py --check   # verify they are up to date

--check is what CI runs, so the table cannot drift away from the suite.

An entry counts as a non-game if any of three things is true: it sets
`skip_visual` (the custom probes all do, being read out of .sav rather than
screenshotted), a sibling `<name>.asm` exists (so it is a probe built in this
repo), or it is named in NON_GAME_SUITES below (Blargg's and Mooneye's suites,
the homebrew conformance ROMs).  Everything else is treated as a game.

That default is deliberate but worth knowing: a newly added conformance ROM
that satisfies none of the three will appear in the table as a game until it
is added to NON_GAME_SUITES.  The failure mode is a visible wrong row rather
than a silent omission, which is the way round that gets noticed.
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
CONFIG = PROJECT_DIR / "test_roms" / "test_config.json"
README = PROJECT_DIR / "README.md"
DEMO = PROJECT_DIR / "docs" / "index.html"

BEGIN = "<!-- BEGIN GENERATED COMPATIBILITY TABLE -->"
END = "<!-- END GENERATED COMPATIBILITY TABLE -->"

# Test ROMs and conformance suites: everything here is a probe rather than a
# game, and belongs in the accuracy tables instead.
NON_GAME_SUITES = {
    "cpu_instrs", "instr_timing", "mem_timing", "mem_timing2", "cgb-acid2",
    "01-special", "02-interrupts", "03-op sp,hl", "04-op r,imm", "05-op rp",
    "06-ld r,r", "07-jr,jp,call,ret,rst", "08-misc instrs", "09-op r,r",
    "10-bit ops", "11-op a,(hl)",
}


def is_non_game(name, cfg):
    # The custom probes all ship as <name>.asm beside the config, and all of
    # them set skip_visual because they are read out of .sav rather than
    # screenshotted.  Either signal alone is enough.
    if cfg.get("skip_visual"):
        return True
    if (PROJECT_DIR / "test_roms" / (name + ".asm")).exists():
        return True
    return name in NON_GAME_SUITES


def classify(name, cfg):
    """Return (status, note) for a game entry."""
    note = (cfg.get("description") or "").strip()
    # Trim the leading "Title - " that most descriptions repeat.
    if " - " in note:
        head, tail = note.split(" - ", 1)
        if head.lower().rstrip(" 0123456789()").replace(" ", "") in \
                name.lower().replace(" ", ""):
            note = tail.strip()

    if cfg.get("expected_fail"):
        reason = (cfg.get("xfail_reason") or "").strip()
        if reason:
            reason = reason.replace("PRE-EXISTING, see #37:", "").strip()
            note = f"{note} — capture not pinned: {reason}" if note else reason
        else:
            note = f"{note} — capture not pinned" if note else \
                "capture not pinned"
        return "Runs, capture unpinned", note
    return "Verified", note


def collect():
    with open(CONFIG) as f:
        cfg = json.load(f)
    games = []
    for name, entry in cfg.items():
        if is_non_game(name, entry):
            continue
        status, note = classify(name, entry)
        games.append((name, status, note))
    games.sort(key=lambda g: g[0].lower())
    return games


def render_markdown(games):
    verified = sum(1 for g in games if g[1] == "Verified")
    lines = [
        BEGIN,
        "",
        f"{len(games)} commercial titles run by CI on every push; "
        f"{verified} have their captures pinned pixel-for-pixel against a "
        f"stored baseline. Generated from `test_roms/test_config.json` by "
        f"`scripts/gen_compat_table.py` — do not edit by hand.",
        "",
        "| Game | Status | Notes |",
        "|------|--------|-------|",
    ]
    for name, status, note in games:
        note = note.replace("|", "\\|")
        lines.append(f"| {name} | {status} | {note} |")
    lines += ["", END]
    return "\n".join(lines)


def render_html(games):
    verified = sum(1 for g in games if g[1] == "Verified")
    out = [
        BEGIN,
        '<section class="compat">',
        "  <h2>Game compatibility</h2>",
        f"  <p>{len(games)} commercial titles run by CI on every push; "
        f"{verified} have their captures pinned pixel-for-pixel against a "
        f"stored baseline. Generated from the regression suite&rsquo;s own "
        f"config.</p>",
        '  <table class="compat-table">',
        "    <thead><tr><th>Game</th><th>Status</th><th>Notes</th></tr>"
        "</thead>",
        "    <tbody>",
    ]
    for name, status, note in games:
        def esc(s):
            return (s.replace("&", "&amp;").replace("<", "&lt;")
                     .replace(">", "&gt;"))
        cls = "ok" if status == "Verified" else "warn"
        out.append(f'      <tr><td>{esc(name)}</td>'
                   f'<td class="{cls}">{esc(status)}</td>'
                   f"<td>{esc(note)}</td></tr>")
    out += ["    </tbody>", "  </table>", "</section>", END]
    return "\n".join(out)


def splice(path, block):
    text = path.read_text()
    if BEGIN not in text or END not in text:
        return None
    head = text.split(BEGIN)[0]
    tail = text.split(END, 1)[1]
    return head + block + tail


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify the generated blocks are up to date")
    args = ap.parse_args()

    games = collect()
    if not games:
        print("ERROR: no games classified out of the suite config")
        return 2

    targets = [(README, render_markdown(games)), (DEMO, render_html(games))]

    stale = []
    for path, block in targets:
        new = splice(path, block)
        if new is None:
            print(f"ERROR: {path.name} has no "
                  f"{BEGIN} / {END} markers to fill")
            return 2
        if args.check:
            if new != path.read_text():
                stale.append(path.name)
        else:
            path.write_text(new)

    if args.check:
        if stale:
            print("FAIL: generated compatibility table is out of date in: "
                  + ", ".join(stale))
            print("      run: python3 scripts/gen_compat_table.py")
            return 1
        print(f"OK: compatibility table up to date ({len(games)} games)")
        return 0

    print(f"Wrote compatibility table for {len(games)} games to "
          f"README.md and docs/index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
