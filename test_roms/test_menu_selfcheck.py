#!/usr/bin/env python3
"""Host-native checks on the menu/SRAM harness itself (issue #59).

The suites these cover (test_menu.py, test_sram_writethrough.py) need
devkitARM, a built chroma.gba and the private game ROMs, so they cannot run
on a bare checkout -- which is exactly how their assertions were able to rot
into always-true shapes without anyone noticing.  Everything here is pure
Python and runs anywhere:

  * the ELF-map symbol loader refuses to invent addresses
  * the clock row really is excluded from menu screenshot comparisons
  * a control run and its toggled counterpart share one frame schedule, which
    is what makes their pixel difference attributable to the setting
  * skipped SRAM tests do not report success

Usage:
    python3 test_roms/test_menu_selfcheck.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

import elf_symbols
import test_menu

failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  PASS: {label}")
    else:
        print(f"  FAIL: {label}{(' -- ' + detail) if detail else ''}")
        failures.append(label)


# --------------------------------------------------------------------------
# elf_symbols: no address is ever guessed
# --------------------------------------------------------------------------
def test_symbol_loader():
    print("\nELF symbol loader")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)

        missing = td / "nope.map"
        try:
            elf_symbols.load_symbols(["joycfg"], map_file=missing)
            check("missing map raises", False, "no exception")
        except elf_symbols.SymbolError as exc:
            check("missing map raises", "not found" in str(exc))

        empty = td / "empty.map"
        empty.write_text("no symbol definitions here\n")
        try:
            elf_symbols.load_symbols(["joycfg"], map_file=empty)
            check("unparseable map raises", False, "no exception")
        except elf_symbols.SymbolError as exc:
            check("unparseable map raises", "No symbol definitions" in str(exc))

        good = td / "good.map"
        good.write_text(
            " .bss           0x0000000003005130       0x1 build/ui.o\n"
            "                0x0000000003005130                doubletimer\n"
            "                0x0000000003005130                request_gba_mode\n"
            "                0x00000000030038cc                joycfg\n"
            "                0x0000000002038000                XGB_SRAM\n"
        )
        syms = elf_symbols.load_symbols(["joycfg", "XGB_SRAM"], map_file=good)
        check("parses symbol addresses",
              syms == {"joycfg": 0x030038CC, "XGB_SRAM": 0x02038000},
              str(syms))

        try:
            elf_symbols.load_symbols(["joycfg", "not_a_symbol"], map_file=good)
            check("absent symbol raises", False, "no exception")
        except elf_symbols.SymbolError as exc:
            check("absent symbol raises", "not_a_symbol" in str(exc))

        # A stale hardcoded default is what this replaced, so confirm nothing
        # is silently substituted for a name the map does not define.
        parsed = elf_symbols.parse_map(good.read_text())
        check("colliding labels keep the first definition",
              parsed["doubletimer"] == parsed["request_gba_mode"] == 0x03005130)

        # Linker-computed symbols carry their defining expression on the same
        # line; __eheap_end is one, and XGB_SRAM is derived from it.
        computed = td / "computed.map"
        computed.write_text(
            "                0x0000000002040000                "
            "__eheap_end = (ORIGIN (ewram) + LENGTH (ewram))\n"
        )
        check("parses linker-computed symbols",
              elf_symbols.parse_map(computed.read_text()).get("__eheap_end")
              == 0x02040000)

        equates = td / "equates.h"
        equates.write_text(" MEM_END\t= 0x02040000\n Next = MEM_END\n")
        check("derives XGB_SRAM from MEM_END",
              elf_symbols.xgb_sram_addr(map_file=computed,
                                        equates_file=equates) == 0x02038000)

        # If equates.h and the linker script disagree, neither can be trusted.
        skewed = td / "skewed.h"
        skewed.write_text(" MEM_END\t= 0x02030000\n")
        try:
            elf_symbols.xgb_sram_addr(map_file=computed, equates_file=skewed)
            check("MEM_END/linker mismatch raises", False, "no exception")
        except elf_symbols.SymbolError as exc:
            check("MEM_END/linker mismatch raises", "mismatch" in str(exc))


# --------------------------------------------------------------------------
# Clock row masking (issue #59 item 4)
# --------------------------------------------------------------------------
def test_clock_row_masked():
    print("\nMenu screenshot clock masking")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        w, h = 240, 160

        base = Image.new("RGB", (w, h), (0, 0, 0))
        a = td / "a.png"
        base.save(a)

        # Only the clock row differs: this is what an advanced seconds digit
        # looks like to the comparison.
        clock = base.copy()
        for y in range(test_menu.CLOCK_ROW_PX):
            for x in range(64):
                clock.putpixel((x, y), (255, 255, 255))
        b = td / "b.png"
        clock.save(b)

        raw = test_menu.pixel_diff_pct(a, b)
        masked = test_menu.menu_diff_pct(a, b)
        check("unmasked comparison sees the clock", raw > 0, f"{raw}%")
        check("menu comparison ignores the clock row", masked == 0, f"{masked}%")

        # The thresholds these tests use are small; confirm a clock-only change
        # would have cleared the two smallest ones (0.05% and 0.1%).
        check("clock alone would satisfy the autofire threshold unmasked",
              raw > 0.05, f"{raw}%")

        # Content below the clock row must still register.
        body = base.copy()
        for y in range(test_menu.CLOCK_ROW_PX, test_menu.CLOCK_ROW_PX + 8):
            for x in range(64):
                body.putpixel((x, y), (255, 255, 255))
        c = td / "c.png"
        body.save(c)
        check("menu comparison still sees menu content",
              test_menu.menu_diff_pct(a, c) > 0)

        # Mismatched sizes used to compare a truncated zip() rather than fail.
        small = td / "small.png"
        Image.new("RGB", (120, 80), (0, 0, 0)).save(small)
        try:
            test_menu.pixel_diff_pct(a, small)
            check("size mismatch raises", False, "no exception")
        except ValueError:
            check("size mismatch raises", True)


# --------------------------------------------------------------------------
# Control/experiment schedules must match (issue #59 item 1)
# --------------------------------------------------------------------------
def frames_of(inputs):
    return [int(spec.split(":")[0]) for spec in inputs]


def test_control_schedule_matches():
    print("\nControl vs toggled input schedules")

    toggled, t_end = test_menu.toggle_and_close_menu(1000, toggle=True)
    control, c_end = test_menu.toggle_and_close_menu(1000, toggle=False)

    check("control ends on the same frame as the toggled run", t_end == c_end,
          f"{t_end} vs {c_end}")
    check("control omits exactly the A press",
          [s for s in toggled if not s.endswith(":A")] == control,
          f"{toggled} vs {control}")
    check("the omitted press is the toggle",
          [s for s in toggled if s.endswith(":A")] == ["1000:A"])
    check("both close the menu on identical frames",
          frames_of([s for s in toggled if s.endswith(":B")])
          == frames_of([s for s in control if s.endswith(":B")]))

    # The LCD-hack test varies the number of A presses instead of a boolean,
    # and pads the schedule so both variants reach the screenshot together.
    # Reproduce that arithmetic here so a change to it is caught.
    def lcdhack_end(presses, t=2000):
        _, t = test_menu.navigate_to_submenu_item(t, 4, 1)
        t += presses * test_menu.MENU_GAP
        t += (3 - presses) * test_menu.MENU_GAP
        return t + 2 * test_menu.MENU_GAP + 1000

    check("0-press and 3-press LCD hack runs end together",
          lcdhack_end(0) == lcdhack_end(3),
          f"{lcdhack_end(0)} vs {lcdhack_end(3)}")


# --------------------------------------------------------------------------
# Suite bookkeeping (issue #59 items 3, 6, 7)
# --------------------------------------------------------------------------
def test_suite_bookkeeping():
    print("\nSuite bookkeeping")

    names = [n for n, _ in test_menu.TESTS]
    check("every menu test has a unique label", len(names) == len(set(names)))
    check("menu suite no longer nests the SRAM suite",
          not hasattr(test_menu, "test_sram_persistence"))

    # The three settings whose visual halves measured exactly 0.0% against a
    # matched control keep their state assertions and drop the pixel claim.
    # A threshold creeping back in would be a vacuous assertion again.
    menu_src = (SCRIPT_DIR / "test_menu.py").read_text()
    for marker, label in [
            ("half-vs-full", "double speed"),
            ("hack OFF vs High", "LCD scanline hack"),
            ("autofire-vs-control", "A autofire")]:
        line = next((l for l in menu_src.splitlines() if marker in l), "")
        check(f"{label} diff is reported as a diagnostic, not asserted",
              "not asserted" in line, line.strip())
    check("VSync keeps its visual assertion (it does discriminate)",
          "visual_ok = diff > 5" in menu_src)

    src = (SCRIPT_DIR / "test_sram_writethrough.py").read_text()
    # XGB_SRAM is an assembler equate, so ld never lists it. Asking the map for
    # it is what broke the SRAM suite in CI; it must be derived instead.
    check("SRAM suite derives XGB_SRAM rather than looking it up in the map",
          "xgb_sram_addr()" in src and "load_symbols(['XGB_SRAM'])" not in src)
    check("SRAM skips are not spelled as a pass",
          "print(f\"  SKIP: Game did not write to SRAM\")\n        return True"
          not in src)
    check("SRAM suite defines a SKIP state", "SKIP = " in src)
    check("SRAM suite fails when everything was skipped",
          "every test was skipped" in src)

    runner = (SCRIPT_DIR / "run_all_tests.py").read_text()
    import run_all_tests
    check("slow SRAM suite is no longer capped below the others",
          run_all_tests.TIMEOUT_SRAM > run_all_tests.TIMEOUT_SHORT_ROM
          and run_all_tests.TIMEOUT_MENU >= run_all_tests.TIMEOUT_SRAM,
          f"sram={run_all_tests.TIMEOUT_SRAM} menu={run_all_tests.TIMEOUT_MENU}")
    check("suite runner forwards --diff-dir", "--diff-dir" in runner)

    workflow = (SCRIPT_DIR.parent / ".github/workflows/test.yml").read_text()
    full = workflow.split("test-full:", 1)[-1]
    check("CI runs the visual suite once in test-full",
          "run_tests.py --diff-dir" not in full,
          "run_tests.py is still invoked directly alongside run_all_tests.py")


def test_scripts_are_syntactically_valid():
    print("\nHarness scripts compile")
    for name in ["test_menu.py", "test_sram_writethrough.py",
                 "run_all_tests.py", "run_tests.py", "elf_symbols.py"]:
        proc = subprocess.run(
            [sys.executable, "-m", "py_compile", str(SCRIPT_DIR / name)],
            capture_output=True, text=True)
        check(f"{name} compiles", proc.returncode == 0, proc.stderr.strip())


def main():
    print("=" * 60)
    print("  Menu/SRAM harness self-checks (issue #59)")
    print("=" * 60)

    test_symbol_loader()
    test_clock_row_masked()
    test_control_schedule_matches()
    test_suite_bookkeeping()
    test_scripts_are_syntactically_valid()

    print("\n" + "=" * 60)
    if failures:
        print(f"  {len(failures)} check(s) FAILED:")
        for f in failures:
            print(f"    - {f}")
        return 1
    print("  All harness self-checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
