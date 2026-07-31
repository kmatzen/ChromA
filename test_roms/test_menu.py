#!/usr/bin/env python3
"""Automated tests for all ChromA menu features.

Tests save states, menu navigation, persistence, display settings,
and all accessible menu items.

Usage:
    python3 test_roms/test_menu.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path
from PIL import Image

from elf_symbols import SymbolError, load_symbols

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
RUNNER = SCRIPT_DIR / "mgba_runner"
COMPILER = SCRIPT_DIR / "goomba_compile.py"
EMULATOR = PROJECT_DIR / "chroma.gba"
SML2_ROM = SCRIPT_DIR / "Super Mario Land 2 - 6 Golden Coins (USA, Europe) (Rev 2).gb"
ZELDA_DX_ROM = SCRIPT_DIR / "Legend of Zelda, The - Link's Awakening DX (USA, Europe) (Rev 2) (SGB Enhanced) (GB Compatible).gbc"
KIRBY_DL2_ROM = SCRIPT_DIR / "Kirby's Dream Land 2 (USA, Europe) (SGB Enhanced).gb"

# Menu runs ~1 iteration per 2-3 mGBA frames.
# Use 120-frame gaps between inputs to ensure each registers exactly once.
MENU_GAP = 120

# test_autofire_behavior: how long A is held in gameplay, which frames inside
# that hold are sampled, and how much the autofire and control runs must differ
# at each sample.  See the comments in that test for the measured numbers.
AF_HOLD = 300
AF_SAMPLES = (90, 290)
AF_MIN_DIFF = 0.2

# Emulator memory addresses, resolved from build/chroma.elf.map.  There are
# deliberately no hardcoded fallbacks: an address that silently goes stale
# makes every behavioural assertion below a statement about unrelated memory.
# See elf_symbols.py.
_SYMBOLS = [
    'joycfg', 'fpsenabled', 'novblankwait', 'sleeptime', 'autostate',
    'doubletimer', 'g_lcdhack', 'palettebank', 'gammavalue',
    'sgb_palette_number', 'request_gba_mode', 'request_gb_type', 'auto_border',
]


def _load_addresses():
    """Resolve every symbol these tests poke, or fail loudly."""
    addrs = load_symbols(_SYMBOLS)
    # doubletimer and request_gba_mode are adjacent .byte labels in the
    # assembly (doubletimer: .byte 2; request_gba_mode: .byte 0).  ld reports
    # both at the same address, so the second has to be derived.  Assert the
    # collision is exactly the one we know about: if ld ever starts reporting
    # distinct addresses, take them at face value instead of adding 1 to a
    # value that is already correct.
    if addrs['request_gba_mode'] == addrs['doubletimer']:
        addrs['request_gba_mode'] = addrs['doubletimer'] + 1
    return addrs


# Resolution is deferred rather than fatal at import, so the helpers in this
# module stay importable (test_menu_selfcheck.py exercises them without a
# build). main() turns an unresolved map into a hard exit before any test runs.
_ADDR_ERROR = None
try:
    _ADDRS = _load_addresses()
except SymbolError as exc:
    _ADDR_ERROR = exc
    _ADDRS = dict.fromkeys(_SYMBOLS)

ADDR_JOYCFG = _ADDRS['joycfg']
ADDR_FPSENABLED = _ADDRS['fpsenabled']
ADDR_NOVBLANKWAIT = _ADDRS['novblankwait']
ADDR_SLEEPTIME = _ADDRS['sleeptime']
ADDR_AUTOSTATE = _ADDRS['autostate']
ADDR_DOUBLETIMER = _ADDRS['doubletimer']
ADDR_G_LCDHACK = _ADDRS['g_lcdhack']
ADDR_PALETTEBANK = _ADDRS['palettebank']
ADDR_GAMMAVALUE = _ADDRS['gammavalue']
ADDR_SGB_PALNUM = _ADDRS['sgb_palette_number']
ADDR_REQUEST_GBA = _ADDRS['request_gba_mode']
ADDR_REQUEST_GB_TYPE = _ADDRS['request_gb_type']
ADDR_AUTO_BORDER = _ADDRS['auto_border']


class RunnerError(RuntimeError):
    """mgba_runner exited non-zero, so its outputs do not exist."""


def run(gba, frames, inputs, screenshots=None, savefile=None, memdumps=None):
    """Run the emulator once. Raises RunnerError if the run did not complete.

    Every caller used to discard this result. When a run failed, its
    screenshots and memory dumps were simply never written, and the first
    Image.open/read_u8 that touched one raised a bare FileNotFoundError --
    which, with no isolation in main(), aborted the entire suite at that
    point and left every later test unreported. Raising a typed error lets
    main() attribute the failure to one test and keep going.
    """
    cmd = [str(RUNNER), str(gba), str(frames), "/dev/null"]
    for inp in inputs:
        cmd.extend(["--input", inp])
    for ss in (screenshots or []):
        cmd.extend(["--screenshot", ss])
    if savefile:
        cmd.extend(["--savefile", str(savefile)])
    for md in (memdumps or []):
        cmd.extend(["--memdump", md])
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RunnerError(
            f"mgba_runner exited {proc.returncode} for {frames} frames: "
            f"{proc.stderr.strip()[:400]}"
        )
    return True


# The menu draws the real-time clock on text row 0 (drawclock() in src/ui.c
# calls drawtext(0, ...)), and src/main.c probes the GBA RTC at boot.  When
# mGBA's GPIO autodetect enables the RTC, every menu screenshot embeds the
# host wall clock, so a comparison against a stored baseline -- or against a
# screenshot taken a second earlier in the same suite -- fails purely because
# the seconds digit advanced.  Text rows are 8px tall, so masking the first
# row removes the clock without touching any menu content.
CLOCK_ROW_PX = 8


def menu_diff_pct(a, b):
    """Compare two menu screenshots, masking the clock row."""
    return pixel_diff_pct(a, b, skip_top_px=CLOCK_ROW_PX)


def pixel_diff_pct(a, b, skip_top_px=0):
    """Percent of pixels that differ.

    Gameplay screenshots compare the full frame; use menu_diff_pct() when
    either side is a menu screenshot, so the wall clock on row 0 does not
    contribute to the difference.
    """
    ia = Image.open(a).convert("RGB")
    ib = Image.open(b).convert("RGB")
    if ia.size != ib.size:
        raise ValueError(f"size mismatch: {ia.size} vs {ib.size}")
    w, h = ia.size
    if skip_top_px:
        box = (0, min(skip_top_px, h), w, h)
        ia, ib = ia.crop(box), ib.crop(box)
        if ia.size[1] == 0:
            raise ValueError("skip_top_px removed the whole image")
    d = sum(1 for pa, pb in zip(ia.getdata(), ib.getdata()) if pa != pb)
    return d / (ia.size[0] * ia.size[1]) * 100


def pixels_nonblack(path):
    img = Image.open(path).convert("RGB")
    return sum(1 for p in img.getdata() if any(c > 10 for c in p))


def compile_sml2(output):
    return subprocess.run(
        [sys.executable, str(COMPILER), "-e", str(EMULATOR),
         "-o", str(output), str(SML2_ROM)],
        capture_output=True, text=True
    ).returncode == 0


def compile_rom(rom_path, output):
    """Compile any GB/GBC ROM with the emulator."""
    return subprocess.run(
        [sys.executable, str(COMPILER), "-e", str(EMULATOR),
         "-o", str(output), str(rom_path)],
        capture_output=True, text=True
    ).returncode == 0


def read_u8(path):
    """Read a 1-byte memory dump file."""
    with open(path, "rb") as f:
        return f.read(1)[0]


def read_u32_le(path):
    """Read a 4-byte little-endian memory dump file."""
    with open(path, "rb") as f:
        data = f.read(4)
    return int.from_bytes(data, "little")


def avg_brightness(path):
    """Compute mean pixel brightness (0-255) across all channels."""
    img = Image.open(path).convert("RGB")
    pixels = list(img.getdata())
    return sum(r + g + b for r, g, b in pixels) / (len(pixels) * 3)


def memdump_arg(addr, length, filepath):
    """Format a --memdump argument string."""
    return f"0x{addr:08X}:{length}:{filepath}"


def menu_down(n, start_frame):
    """Generate Down×n inputs with proper spacing."""
    return [f"{start_frame + i * MENU_GAP}:Down" for i in range(n)]


def navigate_to_submenu_item(t, submenu_downs, item_downs):
    """Build inputs to open menu, enter a submenu, and navigate to an item.

    Returns (inputs, t) where t is the current frame after navigation.
    """
    inputs = [f"{t}:L+R"]
    t += 300
    inputs += menu_down(submenu_downs, t)
    t += submenu_downs * MENU_GAP
    inputs += [f"{t}:A"]  # enter submenu
    t += 300
    if item_downs > 0:
        inputs += menu_down(item_downs, t)
        t += item_downs * MENU_GAP
    return inputs, t


def toggle_and_close_menu(t, toggle=True):
    """Press A to toggle a setting, then B twice to close submenu and menu.

    With toggle=False the A press is omitted and everything else -- the frame
    schedule, the navigation, the total run length -- is unchanged. That is
    the control run for the behavioural tests below: the only difference
    between it and the real run is whether the setting actually got flipped,
    so any pixel difference between the two is attributable to the setting
    rather than to the game having animated in the meantime.

    Returns (inputs, t).
    """
    inputs = [f"{t}:A"] if toggle else []
    t += MENU_GAP
    inputs += [f"{t}:B"]  # back to main menu
    t += MENU_GAP
    inputs += [f"{t}:B"]  # close menu
    t += 300
    return inputs, t


def test_quicksave_roundtrip(tmpdir):
    """R+Select saves, R+Start restores game state."""
    print("Test: Quicksave/quickload round-trip")
    gba, sav = tmpdir / "t.gba", tmpdir / "t.sav"
    if not compile_sml2(gba):
        return False
    sp, mv, ld = str(tmpdir / "sp.bmp"), str(tmpdir / "mv.bmp"), str(tmpdir / "ld.bmp")
    run(gba, 8000,
        ["600:Start", "900:Start", "2600:R+Select",
         "3000:Right", "3200:Right", "3400:Right",
         "3600:Right", "3800:Right", "4000:Right",
         "4400:R+Start"],
        screenshots=[f"2400:{sp}", f"4200:{mv}", f"6000:{ld}"], savefile=sav)
    d_sp, d_mv = pixel_diff_pct(sp, ld), pixel_diff_pct(mv, ld)
    passed = d_sp < d_mv
    print(f"  Save={d_sp:.1f}% Moved={d_mv:.1f}% {'PASS' if passed else 'FAIL'}")
    return passed


def test_quicksave_persistence(tmpdir):
    """Save state persists to .sav file across restarts."""
    print("Test: Quicksave persistence")
    gba, sav = tmpdir / "t.gba", tmpdir / "t.sav"
    if not compile_sml2(gba):
        return False
    sp = str(tmpdir / "sp.bmp")
    run(gba, 4000, ["600:Start", "900:Start", "2600:R+Select"],
        screenshots=[f"2400:{sp}"], savefile=sav)
    rl = str(tmpdir / "rl.bmp")
    run(gba, 4000, ["600:Start", "900:Start", "2000:R+Start"],
        screenshots=[f"3000:{rl}"], savefile=sav)
    d = pixel_diff_pct(sp, rl)
    passed = d < 15.0
    print(f"  Reload vs save: {d:.1f}% {'PASS' if passed else 'FAIL'}")
    return passed


def test_menu_open_close(tmpdir):
    """L+R opens menu, B closes, game resumes without reset."""
    print("Test: Menu open/close")
    gba = tmpdir / "t.gba"
    if not compile_sml2(gba):
        return False
    b, m, a = str(tmpdir / "b.bmp"), str(tmpdir / "m.bmp"), str(tmpdir / "a.bmp")
    run(gba, 3600, ["600:Start", "900:Start", "2000:L+R", "2400:B"],
        screenshots=[f"1800:{b}", f"2200:{m}", f"3000:{a}"])
    menu_ok = menu_diff_pct(b, m) > 5
    resume_ok = pixel_diff_pct(b, a) < 30
    print(f"  Menu visible={menu_ok} Resume={resume_ok} {'PASS' if menu_ok and resume_ok else 'FAIL'}")
    return menu_ok and resume_ok


def test_menu_save_load_state(tmpdir):
    """Menu Save State and Load State via slot picker."""
    print("Test: Menu save/load state")
    gba, sav = tmpdir / "t.gba", tmpdir / "t.sav"
    if not compile_sml2(gba):
        return False

    title = str(tmpdir / "title.bmp")
    game = str(tmpdir / "game.bmp")
    loaded = str(tmpdir / "loaded.bmp")

    # Save at title screen, play into game, load → should return to title
    inputs = [f"400:{title}"]  # screenshot only
    # Open menu and save state (Down×5 → A → A → B×2)
    t = 500
    inputs_list = [f"{t}:L+R"]
    t += 200
    inputs_list += menu_down(5, t)
    t += 5 * MENU_GAP + 200
    inputs_list += [f"{t}:A"]         # enter save submenu
    t += 200
    inputs_list += [f"{t}:A"]         # select slot
    t += 200
    inputs_list += [f"{t}:B"]         # back
    t += 200
    inputs_list += [f"{t}:B"]         # close menu
    t += 200
    # Play into game
    inputs_list += [f"{t}:Start"]
    t += 300
    inputs_list += [f"{t}:Start"]
    t += 1500
    game_frame = t
    # Open menu and load state (Down×6 → A → A → B)
    t += 200
    inputs_list += [f"{t}:L+R"]
    t += 200
    inputs_list += menu_down(6, t)
    t += 6 * MENU_GAP + 200
    inputs_list += [f"{t}:A"]         # enter load submenu
    t += 200
    inputs_list += [f"{t}:A"]         # select slot
    t += 200
    inputs_list += [f"{t}:B"]         # close
    t += 1500
    loaded_frame = t

    total_frames = t + 500

    run(gba, total_frames, inputs_list,
        screenshots=[f"400:{title}", f"{game_frame}:{game}", f"{loaded_frame}:{loaded}"],
        savefile=sav)

    d_title = pixel_diff_pct(title, loaded)
    d_game = pixel_diff_pct(game, loaded)
    passed = d_title < d_game
    print(f"  Title={d_title:.1f}% Game={d_game:.1f}% {'PASS' if passed else 'FAIL'}")
    return passed


def test_display_submenu(tmpdir):
    """Display settings submenu opens and closes."""
    print("Test: Display submenu")
    gba = tmpdir / "t.gba"
    if not compile_sml2(gba):
        return False
    menu = str(tmpdir / "menu.bmp")
    submenu = str(tmpdir / "sub.bmp")
    back = str(tmpdir / "back.bmp")

    t = 2000
    inputs = ["600:Start", "900:Start", f"{t}:L+R"]
    t += 200
    inputs += menu_down(2, t)  # Down×2 → Display
    t += 2 * MENU_GAP
    inputs += [f"{t}:A"]       # enter
    t += 200
    inputs += [f"{t}:B"]       # back

    run(gba, t + 500, inputs,
        screenshots=[f"{2200}:{menu}",
                     f"{2000 + 200 + 2 * MENU_GAP + 100}:{submenu}",
                     f"{t + 300}:{back}"])

    # Submenu should look different from main menu
    d = menu_diff_pct(menu, submenu)
    passed = d > 3
    print(f"  Submenu diff: {d:.1f}% {'PASS' if passed else 'FAIL'}")
    return passed


def test_other_settings_submenu(tmpdir):
    """Other Settings submenu opens and closes."""
    print("Test: Other Settings submenu")
    gba = tmpdir / "t.gba"
    if not compile_sml2(gba):
        return False
    menu = str(tmpdir / "menu.bmp")
    submenu = str(tmpdir / "sub.bmp")

    t = 2000
    inputs = ["600:Start", "900:Start", f"{t}:L+R"]
    t += 200
    inputs += menu_down(3, t)  # Down×3 → Other Settings
    t += 3 * MENU_GAP
    inputs += [f"{t}:A"]
    t += 200
    inputs += [f"{t}:B"]

    run(gba, t + 500, inputs,
        screenshots=[f"2200:{menu}",
                     f"{2000 + 200 + 3 * MENU_GAP + 100}:{submenu}"])

    d = menu_diff_pct(menu, submenu)
    passed = d > 3
    print(f"  Submenu diff: {d:.1f}% {'PASS' if passed else 'FAIL'}")
    return passed


def test_restart(tmpdir):
    """Restart returns game to boot state."""
    print("Test: Restart")
    gba = tmpdir / "t.gba"
    if not compile_sml2(gba):
        return False
    title = str(tmpdir / "title.bmp")
    game = str(tmpdir / "game.bmp")
    restarted = str(tmpdir / "restarted.bmp")

    t = 2000
    inputs = ["600:Start", "900:Start"]
    # Open menu, Down×9 → Restart
    inputs += [f"{t}:L+R"]
    t += 200
    inputs += menu_down(9, t)
    t += 9 * MENU_GAP
    inputs += [f"{t}:A"]
    t += 2000

    run(gba, t + 500, inputs,
        screenshots=[f"300:{title}", f"1800:{game}", f"{t}:{restarted}"])

    d_title = pixel_diff_pct(title, restarted)
    d_game = pixel_diff_pct(game, restarted)
    passed = d_title < d_game
    print(f"  Title={d_title:.1f}% Game={d_game:.1f}% {'PASS' if passed else 'FAIL'}")
    return passed


def test_speed_hacks_submenu(tmpdir):
    """Speed Hacks submenu opens and closes."""
    print("Test: Speed Hacks submenu")
    gba = tmpdir / "t.gba"
    if not compile_sml2(gba):
        return False
    menu = str(tmpdir / "menu.bmp")
    submenu = str(tmpdir / "sub.bmp")

    t = 2000
    inputs = ["600:Start", "900:Start", f"{t}:L+R"]
    t += 200
    inputs += menu_down(4, t)  # Down×4 → Speed Hacks
    t += 4 * MENU_GAP
    inputs += [f"{t}:A"]
    t += 200
    inputs += [f"{t}:B"]

    run(gba, t + 500, inputs,
        screenshots=[f"2200:{menu}",
                     f"{2000 + 200 + 4 * MENU_GAP + 100}:{submenu}"])

    d = menu_diff_pct(menu, submenu)
    passed = d > 3
    print(f"  Submenu diff: {d:.1f}% {'PASS' if passed else 'FAIL'}")
    return passed


def test_autofire_toggle(tmpdir):
    """B autofire cycles through OFF/Hold/Toggle on A press."""
    print("Test: Autofire toggle")
    gba = tmpdir / "t.gba"
    if not compile_sml2(gba):
        return False
    before = str(tmpdir / "before.bmp")
    after = str(tmpdir / "after.bmp")

    # Item 0 = B autofire. Open menu, screenshot, press A to toggle, screenshot again.
    t = 2000
    inputs = ["600:Start", "900:Start", f"{t}:L+R"]
    before_frame = t + 300
    t += 400
    # Cursor starts at item 0 (B autofire). Press A to toggle.
    inputs += [f"{t}:A"]
    after_frame = t + 300

    run(gba, after_frame + 500, inputs,
        screenshots=[f"{before_frame}:{before}", f"{after_frame}:{after}"])

    # The menu text should change (autofire OFF → Hold).  Mask the clock row:
    # at this threshold (~19 pixels) a single advancing seconds digit is
    # enough to satisfy the assertion on its own.
    d = menu_diff_pct(before, after)
    passed = d > 0.05  # sharp pixel font: OFF→Hold is ~27 pixels (0.07%)
    print(f"  Menu diff after toggle: {d:.1f}% {'PASS' if passed else 'FAIL'}")
    return passed


def test_manage_sram(tmpdir):
    """Manage SRAM submenu opens (may show empty if no compressed saves)."""
    print("Test: Manage SRAM submenu")
    gba, sav = tmpdir / "t.gba", tmpdir / "t.sav"
    if not compile_sml2(gba):
        return False
    menu = str(tmpdir / "menu.bmp")
    submenu = str(tmpdir / "sub.bmp")
    back = str(tmpdir / "back.bmp")

    # First quicksave so there's an SRAM entry to manage
    t = 2000
    inputs = ["600:Start", "900:Start", f"{t}:R+Select"]
    t += 400
    # Open menu, Down×7 → Manage SRAM
    inputs += [f"{t}:L+R"]
    t += 200
    inputs += menu_down(7, t)
    t += 7 * MENU_GAP
    inputs += [f"{t}:A"]
    t += 300
    inputs += [f"{t}:B"]

    run(gba, t + 500, inputs,
        screenshots=[f"{2400}:{menu}",
                     f"{2000 + 400 + 200 + 7 * MENU_GAP + 150}:{submenu}",
                     f"{t + 300}:{back}"],
        savefile=sav)

    # Submenu should differ from main menu (even if empty, header text changes)
    d = menu_diff_pct(menu, submenu)
    passed = d > 2
    print(f"  Submenu diff: {d:.1f}% {'PASS' if passed else 'FAIL'}")
    return passed


def test_a_autofire_behavior(tmpdir):
    """A autofire: verify joycfg bitmask changes and autofire affects gameplay."""
    print("Test: A autofire (behavioral)")
    gba = tmpdir / "t.gba"
    if not compile_sml2(gba):
        return False
    dump_path = str(tmpdir / "joycfg_af.bin")
    control_dump = str(tmpdir / "joycfg_af_control.bin")
    no_press_ss = [str(tmpdir / f"no_press_{o}.bmp") for o in AF_SAMPLES]
    autofire_ss = [str(tmpdir / f"autofire_{o}.bmp") for o in AF_SAMPLES]
    menu_before_ss = str(tmpdir / "af_menu_before.bmp")
    menu_after_ss = str(tmpdir / "af_menu_after.bmp")

    # The old control was a plain boot with no menu and no A press at all,
    # screenshotted at frame 2500 while the experimental run screenshotted
    # ~1500 frames later.  `diff > 2` between two such frames is guaranteed by
    # animation, so the visual half asserted nothing.  Both runs now navigate
    # identically and both press A in gameplay at the same frame; only the
    # toggle differs, so the difference isolates autofire's effect on that
    # held A press.
    #
    # The A press is held for AF_HOLD frames via the runner's `frame:keys:hold`
    # spec.  With the old fixed 15-frame auto-release the visual half measured
    # exactly 0.0%: 15 frames is roughly one jump either way, and 300 frames
    # later Mario has landed in the same place whether that was one sustained
    # press or several autofired pulses.  Held for AF_HOLD instead, autofire
    # turns one long jump into a string of short ones and the screens diverge
    # for the rest of the hold.
    def autofire_run(toggle, gameplay_ss, dump, menu_shots=None):
        t = 2000
        inputs = ["600:Start", "900:Start", f"{t}:L+R"]
        t += 300
        inputs += menu_down(1, t)  # A autofire (item 1)
        t += MENU_GAP
        menu_before_frame = t
        t += 200
        if toggle:
            inputs += [f"{t}:A"]  # toggle A autofire ON
        t += MENU_GAP
        menu_after_frame = t
        t += 200
        inputs += [f"{t}:B"]  # close menu
        t += 300
        # Hold A in gameplay - with autofire this pulses causing repeated jumps
        inputs += [f"{t}:A:{AF_HOLD}"]
        shots = [f"{t + off}:{path}"
                 for off, path in zip(AF_SAMPLES, gameplay_ss)]
        t += AF_HOLD
        if menu_shots:
            shots = [f"{menu_before_frame}:{menu_shots[0]}",
                     f"{menu_after_frame}:{menu_shots[1]}"] + shots
        run(gba, t + 500, inputs, screenshots=shots,
            memdumps=[memdump_arg(ADDR_JOYCFG, 4, dump)])

    autofire_run(toggle=False, gameplay_ss=no_press_ss, dump=control_dump)
    autofire_run(toggle=True, gameplay_ss=autofire_ss, dump=dump_path,
                 menu_shots=(menu_before_ss, menu_after_ss))

    joycfg = read_u32_le(dump_path)
    control_joycfg = read_u32_le(control_dump)
    a_bit_cleared = (joycfg & 0x01) == 0
    control_a_bit_set = (control_joycfg & 0x01) == 1
    # The menu screenshots were captured but never compared. The label does
    # change on toggle, so assert it (clock row masked -- see menu_diff_pct).
    menu_changed = menu_diff_pct(menu_before_ss, menu_after_ss) > 0.05
    # Gameplay effect.  The two runs are identical apart from the menu toggle,
    # and the runner is deterministic -- running the control twice gives 0.00%
    # at both sample points -- so any divergence here is autofire's doing.
    # Measured: 2.71% at +90 and 2.75% at +290 against a 0.00% floor.  The
    # threshold sits an order of magnitude below the signal and above a floor
    # that is exactly zero, and both samples must show it, so a single frame of
    # incidental animation cannot carry the assertion the way the old
    # `diff > 2` between two differently-timed runs did.
    diffs = [pixel_diff_pct(a, b) for a, b in zip(no_press_ss, autofire_ss)]
    gameplay_changed = all(d > AF_MIN_DIFF for d in diffs)
    passed = (a_bit_cleared and control_a_bit_set and menu_changed
              and gameplay_changed)
    print(f"  joycfg=0x{joycfg:08X} (A bit cleared={a_bit_cleared}), "
          f"control=0x{control_joycfg:08X} (A bit set={control_a_bit_set})")
    print(f"  menu label changed={menu_changed}")
    print("  autofire-vs-control gameplay diff: "
          + ", ".join(f"+{o}f {d:.2f}%" for o, d in zip(AF_SAMPLES, diffs))
          + f" (need >{AF_MIN_DIFF}% at both)")
    print(f"  {'PASS' if passed else 'FAIL'}")
    return passed


def test_vsync_behavior(tmpdir):
    """VSync: verify novblankwait changes and game progression differs."""
    print("Test: VSync (behavioral)")
    gba = tmpdir / "t.gba"
    if not compile_sml2(gba):
        return False
    dump_path = str(tmpdir / "novblankwait.bin")
    control_dump = str(tmpdir / "novblankwait_control.bin")
    vsync_on_ss = str(tmpdir / "vsync_on.bmp")
    vsync_off_ss = str(tmpdir / "vsync_off.bmp")

    # This used to compare a screenshot taken before the menu was opened
    # against one taken ~2500 frames later in the same run.  Those differ by
    # far more than 5% from ordinary gameplay animation alone, so `diff > 5`
    # held regardless of what VSync did.  Compare instead against a control
    # run with the identical schedule and no toggle, screenshotted at the
    # same frame.
    def vsync_run(toggle, screenshot, dump):
        t = 2000
        inputs = ["600:Start", "900:Start"]
        # Open menu, Other Settings (Down×3), VSync (item 0), toggle OFF
        nav, t = navigate_to_submenu_item(t, 3, 0)
        inputs += nav
        tog, t = toggle_and_close_menu(t, toggle=toggle)
        inputs += tog
        # Let the game run past the menu close, then screenshot
        t += 2000
        run(gba, t + 500, inputs,
            screenshots=[f"{t}:{screenshot}"],
            memdumps=[memdump_arg(ADDR_NOVBLANKWAIT, 1, dump)])

    vsync_run(toggle=False, screenshot=vsync_on_ss, dump=control_dump)
    vsync_run(toggle=True, screenshot=vsync_off_ss, dump=dump_path)

    val = read_u8(dump_path)
    control_val = read_u8(control_dump)
    state_ok = val == 1 and control_val == 0  # novblankwait=1 means VSync OFF
    # With VSync OFF the game runs uncapped, so by the shared screenshot frame
    # it has advanced further than the control.
    diff = pixel_diff_pct(vsync_on_ss, vsync_off_ss)
    visual_ok = diff > 5
    passed = state_ok and visual_ok
    print(f"  novblankwait={val} (expect 1), control={control_val} (expect 0)")
    print(f"  on-vs-off diff={diff:.1f}% {'PASS' if passed else 'FAIL'}")
    return passed


def test_fps_meter_behavior(tmpdir):
    """FPS-Meter: verify FPS overlay appears on game screen."""
    print("Test: FPS-Meter (behavioral)")
    gba = tmpdir / "t.gba"
    if not compile_sml2(gba):
        return False
    before_ss = str(tmpdir / "nofps.bmp")
    after_ss = str(tmpdir / "fps.bmp")
    dump_path = str(tmpdir / "fpsenabled.bin")

    # Boot game, screenshot gameplay without FPS
    t = 2000
    inputs = ["600:Start", "900:Start"]
    before_frame = t
    # Open menu, Other Settings (Down×3), FPS-Meter (item 1), toggle ON
    nav, t = navigate_to_submenu_item(t, 3, 1)
    inputs += nav
    tog, t = toggle_and_close_menu(t)
    inputs += tog
    # Let game run with FPS overlay for ~120 frames so counter updates
    t += 200
    after_frame = t

    run(gba, t + 500, inputs,
        screenshots=[f"{before_frame}:{before_ss}", f"{after_frame}:{after_ss}"],
        memdumps=[memdump_arg(ADDR_FPSENABLED, 1, dump_path)])

    val = read_u8(dump_path)
    flag_ok = val == 1
    # FPS overlay adds text to game screen
    diff = pixel_diff_pct(before_ss, after_ss)
    overlay_ok = diff > 0.3
    passed = flag_ok and overlay_ok
    print(f"  fpsenabled={val}, overlay diff={diff:.1f}% {'PASS' if passed else 'FAIL'}")
    return passed


def test_autosleep_behavior(tmpdir):
    """Autosleep: verify sleeptime cycles through all 4 distinct timer values."""
    print("Test: Autosleep (behavioral)")
    gba = tmpdir / "t.gba"
    if not compile_sml2(gba):
        return False

    expected_values = [36000, 108000, 0x7F000000, 18000]  # 10min, 30min, OFF, 5min
    actual_values = []

    for i in range(4):
        dump_path = str(tmpdir / f"sleeptime_{i}.bin")
        t = 2000
        inputs = ["600:Start", "900:Start"]
        # Open menu, Other Settings, Autosleep (item 2)
        nav, t = navigate_to_submenu_item(t, 3, 2)
        inputs += nav
        # Press A (i+1) times to cycle through values
        for _ in range(i + 1):
            inputs += [f"{t}:A"]
            t += MENU_GAP
        # Close menu
        inputs += [f"{t}:B", f"{t + MENU_GAP}:B"]
        t += 2 * MENU_GAP

        run(gba, t + 200, inputs,
            memdumps=[memdump_arg(ADDR_SLEEPTIME, 4, dump_path)])
        actual_values.append(read_u32_le(dump_path))

    # Verify all 4 values are distinct and match expected
    all_distinct = len(set(actual_values)) == 4
    match = actual_values == expected_values
    passed = all_distinct and match
    print(f"  Values: {actual_values}")
    print(f"  Expected: {expected_values}")
    print(f"  Distinct={all_distinct} Match={match} {'PASS' if passed else 'FAIL'}")
    return passed


def test_swap_ab_behavior(tmpdir):
    """Swap A-B: verify joycfg bit 10 set, and B acts as jump with swap enabled."""
    print("Test: Swap A-B (behavioral)")
    gba = tmpdir / "t.gba"
    if not compile_sml2(gba):
        return False
    dump_path = str(tmpdir / "joycfg_swap.bin")
    press_a_ss = str(tmpdir / "press_a.bmp")
    press_b_swapped_ss = str(tmpdir / "press_b_swapped.bmp")
    no_press_ss = str(tmpdir / "no_press.bmp")

    # Run 1: Boot game, press A in gameplay (Mario jumps)
    t = 2000
    inputs1 = ["600:Start", "900:Start"]
    inputs1 += [f"{t}:A"]  # jump
    t += 300
    run(gba, t + 500, inputs1,
        screenshots=[f"{t}:{press_a_ss}"])

    # Run 2: Boot game, enable swap A-B, then press B (which should act as A = jump)
    t = 2000
    inputs2 = ["600:Start", "900:Start"]
    nav, t = navigate_to_submenu_item(t, 3, 3)  # Other Settings, Swap A-B
    inputs2 += nav
    tog, t = toggle_and_close_menu(t)
    inputs2 += tog
    inputs2 += [f"{t}:B"]  # press B (should act as A = jump with swap)
    t += 300
    run(gba, t + 500, inputs2,
        screenshots=[f"{t}:{press_b_swapped_ss}"],
        memdumps=[memdump_arg(ADDR_JOYCFG, 4, dump_path)])

    # Run 3: Boot game, no button press at gameplay point (control)
    t = 2000
    inputs3 = ["600:Start", "900:Start"]
    t += 600
    run(gba, t + 500, inputs3,
        screenshots=[f"{t}:{no_press_ss}"])

    joycfg = read_u32_le(dump_path)
    bit10_set = (joycfg & 0x400) != 0
    # With swap, pressing B should produce a jump like pressing A.
    # Both "press A" and "press B swapped" should differ from "no press".
    diff_a_vs_none = pixel_diff_pct(press_a_ss, no_press_ss)
    diff_bswap_vs_none = pixel_diff_pct(press_b_swapped_ss, no_press_ss)
    # Both runs that pressed a jump button should show movement
    a_jumped = diff_a_vs_none > 2
    b_jumped = diff_bswap_vs_none > 2
    passed = bit10_set and a_jumped and b_jumped
    print(f"  joycfg=0x{joycfg:08X} bit10={bit10_set}, A diff={diff_a_vs_none:.1f}%, B(swap) diff={diff_bswap_vs_none:.1f}%")
    print(f"  {'PASS' if passed else 'FAIL'}")
    return passed


def test_autoload_state_behavior(tmpdir):
    """Autoload state: save state, enable autoload, reboot, verify auto-restore."""
    print("Test: Autoload state (behavioral)")
    gba, sav = tmpdir / "t.gba", tmpdir / "t.sav"
    if not compile_sml2(gba):
        return False
    title_ss = str(tmpdir / "title.bmp")
    gameplay_ss = str(tmpdir / "gameplay.bmp")
    autoloaded_ss = str(tmpdir / "autoloaded.bmp")

    # This test used to prove almost nothing.  Closing the menu with B does
    # not call writeconfig(), so `autostate` never reached the .sav -- and run
    # 2 replayed the same "600:Start, 900:Start" that walks SML2 from its
    # title screen into gameplay by hand.  So run 2 reached gameplay whether
    # autoload worked or not, and the only live assertion was the in-memory
    # flag from run 1.
    #
    # Now: run 1 exits through Restart (src/ui.c restart() calls writeconfig(),
    # so the setting is actually persisted), and run 2 supplies no inputs at
    # all -- if autoload does not fire, run 2 sits on the title screen and the
    # comparison fails.
    t = 2000
    inputs1 = ["600:Start", "900:Start"]
    inputs1 += [f"{t}:R+Select"]  # quicksave at gameplay
    t += 400
    # Open menu, Other Settings, Autoload state (item 4), toggle ON
    nav, t = navigate_to_submenu_item(t, 3, 4)
    inputs1 += nav
    tog, t = toggle_and_close_menu(t)
    inputs1 += tog
    # Reopen the menu (the cursor resets to item 0 on every open -- ui.c sets
    # selected=0) and pick Restart, item 9, to force a writeconfig().
    inputs1 += [f"{t}:L+R"]
    t += 200
    inputs1 += menu_down(9, t)
    t += 9 * MENU_GAP
    inputs1 += [f"{t}:A"]  # Restart -> writeconfig() -> jump_to_rommenu()
    t += 1200

    run(gba, t + 500, inputs1,
        screenshots=[f"300:{title_ss}", f"1800:{gameplay_ss}"],
        savefile=sav)

    # Run 2: same savefile, no inputs whatsoever. Autoload has to do the work.
    autostate_dump = str(tmpdir / "autostate.bin")
    run(gba, 3000, [],
        screenshots=[f"2500:{autoloaded_ss}"],
        savefile=sav,
        memdumps=[memdump_arg(ADDR_AUTOSTATE, 1, autostate_dump)])

    # Reading the flag on the *fresh* boot is what proves writeconfig()
    # persisted it; reading it in run 1 only proved the menu set a variable.
    autostate_val = read_u8(autostate_dump)
    # Autoloaded should look like gameplay, not like title
    d_title = pixel_diff_pct(title_ss, autoloaded_ss)
    d_gameplay = pixel_diff_pct(gameplay_ss, autoloaded_ss)
    restored = d_gameplay < d_title
    flag_ok = autostate_val == 1
    passed = flag_ok and restored
    print(f"  autostate after reboot={autostate_val} (expect 1), "
          f"title diff={d_title:.1f}%, gameplay diff={d_gameplay:.1f}%")
    print(f"  Restored to gameplay={restored} {'PASS' if passed else 'FAIL'}")
    return passed


def test_palette_behavior(tmpdir):
    """Palette: verify changing palette produces visually different game colors."""
    print("Test: Palette (behavioral)")
    gba = tmpdir / "t.gba"
    if not compile_sml2(gba):
        return False
    default_ss = str(tmpdir / "default_pal.bmp")
    changed_ss = str(tmpdir / "changed_pal.bmp")
    dump_path = str(tmpdir / "palettebank.bin")

    # Run 1: Boot game, screenshot at gameplay (default palette)
    run(gba, 2500, ["600:Start", "900:Start"],
        screenshots=[f"2000:{default_ss}"])

    # Run 2: Boot game, change palette to Grayscale (index 1), screenshot gameplay
    t = 2000
    inputs = ["600:Start", "900:Start"]
    # Open menu, Display (Down×2), enter, Palette (item 0), enter palette list
    inputs += [f"{t}:L+R"]
    t += 300
    inputs += menu_down(2, t)
    t += 2 * MENU_GAP
    inputs += [f"{t}:A"]  # enter Display
    t += 300
    inputs += [f"{t}:A"]  # open palette list (item 0)
    t += 300
    # Scroll down 1 to Grayscale (from whatever auto-detected default)
    # Actually we need to go to index 1 absolute. The list starts at current selection.
    # Use Left to wrap to index 0 (Pea Soup) first, then Down to Grayscale.
    inputs += [f"{t}:Down"]  # move to next palette
    t += MENU_GAP
    inputs += [f"{t}:A"]  # confirm
    t += 300
    inputs += [f"{t}:B"]  # back to main menu
    t += MENU_GAP
    inputs += [f"{t}:B"]  # close menu
    t += 1000
    run(gba, t + 500, inputs,
        screenshots=[f"{t}:{changed_ss}"],
        memdumps=[memdump_arg(ADDR_PALETTEBANK, 4, dump_path)])

    new_palette = read_u32_le(dump_path)
    diff = pixel_diff_pct(default_ss, changed_ss)
    # Palette change should produce a dramatically different color scheme
    palette_changed = diff > 5
    passed = palette_changed
    print(f"  palettebank={new_palette}, color diff={diff:.1f}% {'PASS' if passed else 'FAIL'}")
    return passed


def test_gamma_behavior(tmpdir):
    """Gamma: verify brightness increases with higher gamma (single-run)."""
    print("Test: Gamma (behavioral)")
    gba = tmpdir / "t.gba"
    if not compile_sml2(gba):
        return False
    low_ss = str(tmpdir / "gamma_low.bmp")
    high_ss = str(tmpdir / "gamma_high.bmp")
    menu_before_ss = str(tmpdir / "gamma_menu_before.bmp")
    menu_after_ss = str(tmpdir / "gamma_menu_after.bmp")
    dump_path = str(tmpdir / "gammavalue.bin")

    # Single run: screenshot at default gamma, toggle to V, screenshot again.
    # Same run ensures identical game state for fair brightness comparison.
    t = 2000
    inputs = ["600:Start", "900:Start"]
    before_frame = t
    # Open menu, Display, Gamma (item 1)
    nav, t = navigate_to_submenu_item(t, 2, 1)
    inputs += nav
    # Screenshot menu at gamma I (before)
    menu_before_frame = t
    t += 200
    # Press A 4 times to go from I to V
    for _ in range(4):
        inputs += [f"{t}:A"]
        t += MENU_GAP
    # Screenshot menu at gamma V (after)
    menu_after_frame = t
    t += 200
    # Close menu
    inputs += [f"{t}:B"]
    t += MENU_GAP
    inputs += [f"{t}:B"]
    t += 500
    after_frame = t

    run(gba, t + 500, inputs,
        screenshots=[f"{before_frame}:{low_ss}",
                     f"{menu_before_frame}:{menu_before_ss}",
                     f"{menu_after_frame}:{menu_after_ss}",
                     f"{after_frame}:{high_ss}"],
        memdumps=[memdump_arg(ADDR_GAMMAVALUE, 1, dump_path)])

    gamma_val = read_u8(dump_path)
    bright_low = avg_brightness(low_ss)
    bright_high = avg_brightness(high_ss)
    brighter = bright_high > bright_low
    gamma_ok = gamma_val == 4
    # Also verify the menu text changed between gamma I and V.  Mask the
    # clock row: these two menu screenshots are ~600 frames (10s) apart, so
    # the seconds digit alone comfortably clears a 0.1% (38 pixel) threshold
    # and the assertion would hold with the gamma label frozen.
    menu_diff = menu_diff_pct(menu_before_ss, menu_after_ss)
    menu_ok = menu_diff > 0.1
    passed = brighter and gamma_ok and menu_ok
    print(f"  gamma={gamma_val}, brightness: low={bright_low:.1f} high={bright_high:.1f} brighter={brighter}")
    print(f"  menu diff={menu_diff:.1f}% {'PASS' if passed else 'FAIL'}")
    return passed


def test_sgb_palette_number_behavior(tmpdir):
    """SGB Palette Number: verify variable cycles and border colors change."""
    print("Test: SGB Palette Number (behavioral)")
    gba = tmpdir / "t.gba"
    if not compile_sml2(gba):
        return False

    # Verify all 4 values via memdump
    values = []
    for i in range(4):
        dump_path = str(tmpdir / f"sgbpal_{i}.bin")
        t = 2000
        inputs = ["600:Start", "900:Start"]
        nav, t = navigate_to_submenu_item(t, 2, 1)  # Display, SGB Palette Number (item 1 after gamma removal)
        inputs += nav
        for _ in range(i + 1):
            inputs += [f"{t}:A"]
            t += MENU_GAP
        inputs += [f"{t}:B", f"{t + MENU_GAP}:B"]
        t += 2 * MENU_GAP
        run(gba, t + 200, inputs,
            memdumps=[memdump_arg(ADDR_SGB_PALNUM, 1, dump_path)])
        values.append(read_u8(dump_path))

    expected = [1, 2, 3, 0]
    cycle_ok = values == expected

    # Visual verification: with Kirby DL2 (SGB game), different palette numbers
    # produce visibly different SGB border colors.
    visual_ok = True
    if KIRBY_DL2_ROM.exists():
        kirby_gba = tmpdir / "kirby_pal.gba"
        if compile_rom(KIRBY_DL2_ROM, kirby_gba):
            pal0_ss = str(tmpdir / "kirby_pal0.bmp")
            pal1_ss = str(tmpdir / "kirby_pal1.bmp")

            # Run 1: Default palette 0
            run(kirby_gba, 6000, [],
                screenshots=[f"5500:{pal0_ss}"])

            # Run 2: Change to palette 1, let border redraw
            t = 1000
            inputs = []
            nav, t = navigate_to_submenu_item(t, 2, 1)  # Display, SGB Palette Number (item 1 after gamma removal)
            inputs += nav
            inputs += [f"{t}:A"]  # toggle to 1
            t += MENU_GAP
            inputs += [f"{t}:B", f"{t + MENU_GAP}:B"]
            t += 2 * MENU_GAP + 4000
            run(kirby_gba, t + 500, inputs,
                screenshots=[f"{t}:{pal1_ss}"])

            diff = pixel_diff_pct(pal0_ss, pal1_ss)
            visual_ok = diff > 10
            print(f"  Kirby palette 0 vs 1 diff={diff:.1f}%")

    passed = cycle_ok and visual_ok
    print(f"  Values: {values} (expected {expected}) {'PASS' if passed else 'FAIL'}")
    return passed


def test_double_speed_behavior(tmpdir):
    """Double Speed: verify doubletimer changes and affects game speed."""
    print("Test: Double Speed (behavioral)")
    gba = tmpdir / "t.gba"
    if not compile_sml2(gba):
        return False
    dump_path = str(tmpdir / "doubletimer.bin")
    control_dump = str(tmpdir / "doubletimer_control.bin")
    normal_ss = str(tmpdir / "normal_speed.bmp")
    half_ss = str(tmpdir / "half_speed.bmp")

    # The control run used to be a plain boot with no menu interaction at all,
    # screenshotted at a different frame from the experimental run.  Comparing
    # those two with `diff > 2` asserted nothing: two SML2 gameplay frames from
    # differently-timed runs always differ by far more than 2%, so the test
    # passed whether or not Double Speed did anything.  Both runs now share one
    # input schedule and one screenshot frame, and differ only in the A press
    # that flips the setting.
    def speed_run(toggle, screenshot, dump):
        t = 2000
        inputs = ["600:Start", "900:Start"]
        nav, t = navigate_to_submenu_item(t, 4, 0)  # Speed Hacks, Double Speed
        inputs += nav
        tog, t = toggle_and_close_menu(t, toggle=toggle)
        inputs += tog
        end = t + 2000
        run(gba, end, inputs,
            screenshots=[f"{end - 500}:{screenshot}"],
            memdumps=[memdump_arg(ADDR_DOUBLETIMER, 1, dump)])

    speed_run(toggle=False, screenshot=normal_ss, dump=control_dump)
    speed_run(toggle=True, screenshot=half_ss, dump=dump_path)

    val = read_u8(dump_path)
    control_val = read_u8(control_dump)
    # doubletimer toggles between 1 and 2. Default=2 (gbz80.s: .byte 2),
    # after toggle=1.
    state_ok = val == 1 and control_val == 2
    # No visual assertion, deliberately.  Against a properly matched control
    # this measured exactly 0.0%, and that is correct rather than a bug:
    # doubletimer is the CGB double-speed clock divisor (read from gbz80.s and
    # timeout.s), and SML2 is a DMG game that never enters double-speed mode,
    # so the setting cannot change what it renders.  The old `diff > 2` only
    # held because it compared two unrelated frames from differently-timed
    # runs.  The diff is printed as a diagnostic for anyone revisiting the
    # scenario with a CGB ROM that does switch speeds.
    diff = pixel_diff_pct(normal_ss, half_ss)
    passed = state_ok
    print(f"  doubletimer={val} (expect 1), control={control_val} (expect 2)")
    print(f"  [diagnostic, not asserted] half-vs-full diff={diff:.1f}%")
    print(f"  {'PASS' if passed else 'FAIL'}")
    return passed


def test_lcd_scanline_hack_behavior(tmpdir):
    """LCD scanline hack: verify g_lcdhack cycles and High hack changes rendering."""
    print("Test: LCD scanline hack (behavioral)")
    gba = tmpdir / "t.gba"
    if not compile_sml2(gba):
        return False
    hack_off_ss = str(tmpdir / "lcdhack_off.bmp")
    hack_high_ss = str(tmpdir / "lcdhack_high.bmp")

    # Verify all 4 values via memdump
    values = []
    for i in range(4):
        dump_path = str(tmpdir / f"lcdhack_{i}.bin")
        t = 2000
        inputs = ["600:Start", "900:Start"]
        nav, t = navigate_to_submenu_item(t, 4, 1)  # Speed Hacks, LCD hack
        inputs += nav
        for _ in range(i + 1):
            inputs += [f"{t}:A"]
            t += MENU_GAP
        inputs += [f"{t}:B", f"{t + MENU_GAP}:B"]
        t += 2 * MENU_GAP
        run(gba, t + 200, inputs,
            memdumps=[memdump_arg(ADDR_G_LCDHACK, 1, dump_path)])
        values.append(read_u8(dump_path))

    expected = [1, 2, 3, 0]
    cycle_ok = values == expected

    # Visual verification: LCD hack at High (3) changes rendering vs OFF.
    # The OFF run used to be a plain boot screenshotted at frame 2500 while
    # the High run screenshotted ~1800 frames later after a menu detour, so
    # `diff > 3` was satisfied by animation alone.  Both runs now share the
    # navigation, the frame schedule and the screenshot frame; only the
    # number of A presses on the LCD-hack item differs (0 vs 3).
    def lcdhack_run(presses, screenshot, dump):
        t = 2000
        inputs = ["600:Start", "900:Start"]
        nav, t = navigate_to_submenu_item(t, 4, 1)
        inputs += nav
        for _ in range(presses):  # OFF→Low→Med→High
            inputs += [f"{t}:A"]
            t += MENU_GAP
        # Keep the frame schedule identical regardless of press count, so the
        # two runs reach the shared screenshot frame with the same amount of
        # elapsed gameplay.
        t += (3 - presses) * MENU_GAP
        inputs += [f"{t}:B", f"{t + MENU_GAP}:B"]
        t += 2 * MENU_GAP + 1000
        run(gba, t + 500, inputs, screenshots=[f"{t}:{screenshot}"],
            memdumps=[memdump_arg(ADDR_G_LCDHACK, 1, dump)])
        return t

    off_dump = str(tmpdir / "lcdhack_off.bin")
    high_dump = str(tmpdir / "lcdhack_high.bin")
    lcdhack_run(0, hack_off_ss, off_dump)
    lcdhack_run(3, hack_high_ss, high_dump)

    off_val, high_val = read_u8(off_dump), read_u8(high_dump)
    state_ok = off_val == 0 and high_val == 3
    # No visual assertion, deliberately.  Against a matched control this
    # measured exactly 0.0%, which is what this setting should do:
    # update_lcdhack() (src/lcd.s:5308) swaps the FF41/STAT read handler and
    # patches in a cycle subtraction, so it only changes behaviour for games
    # that poll STAT in wait loops -- it is a speed hack, not a renderer
    # change, and SML2's idle scene gives it nothing to affect.  A stronger
    # check would assert the FF41_R_function pointer was repatched, but that
    # word has no linker symbol to dump (lcd.s writes it via an adrl_ offset).
    diff = pixel_diff_pct(hack_off_ss, hack_high_ss)
    passed = cycle_ok and state_ok
    print(f"  g_lcdhack OFF={off_val} (expect 0), High={high_val} (expect 3)")
    print(f"  [diagnostic, not asserted] hack OFF vs High diff={diff:.1f}%")
    print(f"  Values: {values} (expected {expected})")
    print(f"  Hack OFF vs High diff={diff:.1f}% {'PASS' if passed else 'FAIL'}")
    return passed


def test_identify_as_gba_behavior(tmpdir):
    """Identify as GBA: verify request_gba_mode variable toggles."""
    print("Test: Identify as GBA (behavioral)")
    gba = tmpdir / "t.gba"
    if not compile_sml2(gba):
        return False
    before_dump = str(tmpdir / "gba_before.bin")
    after_dump = str(tmpdir / "gba_after.bin")

    # Run 1: Default (OFF), dump value
    run(gba, 2500, ["600:Start", "900:Start"],
        memdumps=[memdump_arg(ADDR_REQUEST_GBA, 1, before_dump)])

    # Run 2: Toggle ON, dump value
    t = 2000
    inputs = ["600:Start", "900:Start"]
    nav, t = navigate_to_submenu_item(t, 3, 7)  # Other Settings, Identify as GBA
    inputs += nav
    tog, t = toggle_and_close_menu(t)
    inputs += tog
    run(gba, t + 500, inputs,
        memdumps=[memdump_arg(ADDR_REQUEST_GBA, 1, after_dump)])

    before_val = read_u8(before_dump)
    after_val = read_u8(after_dump)
    # Default request_gba_mode=0. After toggle via gbatype(), it becomes 1.
    changed = before_val != after_val
    passed = changed
    print(f"  Before={before_val}, After={after_val}, Changed={changed} {'PASS' if passed else 'FAIL'}")
    return passed


def test_gameboy_type_behavior(tmpdir):
    """Game Boy type: verify Zelda DX boots in GBC vs DMG mode."""
    print("Test: Game Boy type (behavioral)")
    if not ZELDA_DX_ROM.exists():
        print("  SKIP: Zelda DX ROM not found")
        return True
    gba, sav = tmpdir / "zelda.gba", tmpdir / "zelda.sav"
    if not compile_rom(ZELDA_DX_ROM, gba):
        return False
    gbc_ss = str(tmpdir / "zelda_gbc.bmp")
    dmg_ss = str(tmpdir / "zelda_dmg.bmp")

    # Run 1: Default (Prefer GBC). Boot to title screen.
    run(gba, 4000, [],
        screenshots=[f"3500:{gbc_ss}"])

    # Run 2: Set GB type to "GB" (DMG), then restart.
    # Default request_gb_type=2. Need to cycle: 2→3 (A), 3→0 (A) = DMG.
    t = 1000
    inputs = []
    nav, t = navigate_to_submenu_item(t, 3, 5)  # Other Settings, Game Boy type
    inputs += nav
    # Press A twice: Prefer GBC(2) → GBC+SGB(3) → GB(0)
    inputs += [f"{t}:A"]
    t += MENU_GAP
    inputs += [f"{t}:A"]
    t += MENU_GAP
    # Back to main menu (cursor returns to position 3 = Other Settings)
    inputs += [f"{t}:B"]
    t += MENU_GAP
    # Navigate from position 3 to Restart (position 9): Down×6
    inputs += menu_down(6, t)
    t += 6 * MENU_GAP
    inputs += [f"{t}:A"]  # Restart (calls writeconfig + jump_to_rommenu)
    t += 4000  # wait for game to reboot to title
    run(gba, t + 500, inputs,
        screenshots=[f"{t}:{dmg_ss}"],
        savefile=sav)

    diff = pixel_diff_pct(gbc_ss, dmg_ss)
    # Zelda DX GBC mode has a full-color title; DMG mode is very different
    passed = diff > 25
    print(f"  GBC vs DMG title diff={diff:.1f}% (expect >25%) {'PASS' if passed else 'FAIL'}")
    return passed


def test_auto_sgb_border_behavior(tmpdir):
    """Auto SGB border: verify toggle works and SGB border renders with Kirby DL2."""
    print("Test: Auto SGB border (behavioral)")
    if not KIRBY_DL2_ROM.exists():
        print("  SKIP: Kirby DL2 ROM not found")
        return True
    gba = tmpdir / "kirby.gba"
    if not compile_rom(KIRBY_DL2_ROM, gba):
        return False
    border_ss = str(tmpdir / "border.bmp")
    no_border_ss = str(tmpdir / "no_border.bmp")
    dump_path = str(tmpdir / "auto_border.bin")

    # auto_border is not persisted in config (always resets to ON=1 on boot).
    # Its effect is at SGB init time, so we can't toggle it before border loads.
    # We verify: (1) the variable toggles, and (2) with auto_border=ON, the SGB
    # border renders correctly by comparing Kirby SGB vs DMG-mode (no SGB border).

    # Run 1: Default (auto_border=ON, gb_type=Prefer GBC). Kirby boots with SGB border.
    run(gba, 6000, [],
        screenshots=[f"5500:{border_ss}"])

    # Verify auto_border toggles correctly via memdump
    t = 1000
    inputs = []
    nav, t = navigate_to_submenu_item(t, 3, 6)  # Other Settings, Auto SGB border
    inputs += nav
    inputs += [f"{t}:A"]  # toggle OFF
    t += MENU_GAP
    inputs += [f"{t}:B", f"{t + MENU_GAP}:B"]
    t += 2 * MENU_GAP
    run(gba, t + 500, inputs,
        memdumps=[memdump_arg(ADDR_AUTO_BORDER, 1, dump_path)])
    toggle_ok = read_u8(dump_path) == 0

    # Run 2: Boot Kirby in DMG mode (gb_type=0) which disables SGB entirely.
    # gb_type IS persisted, so: toggle gb_type to "GB", restart, boot without border.
    t = 1000
    inputs = []
    nav, t = navigate_to_submenu_item(t, 3, 5)  # Other Settings, Game Boy type
    inputs += nav
    # Cycle: Prefer GBC(2) → GBC+SGB(3) → GB(0): 2 presses
    inputs += [f"{t}:A"]
    t += MENU_GAP
    inputs += [f"{t}:A"]
    t += MENU_GAP
    # Back to main menu (cursor at position 3), navigate to Restart (position 9)
    inputs += [f"{t}:B"]
    t += MENU_GAP
    inputs += menu_down(6, t)
    t += 6 * MENU_GAP
    inputs += [f"{t}:A"]  # Restart
    t += 5000
    sav = tmpdir / "kirby.sav"
    run(gba, t + 500, inputs,
        screenshots=[f"{t}:{no_border_ss}"],
        savefile=sav)

    # SGB mode has decorative border; DMG mode has plain black/game-only border
    diff = pixel_diff_pct(border_ss, no_border_ss)
    visual_ok = diff > 15
    passed = toggle_ok and visual_ok
    print(f"  auto_border toggle={toggle_ok}, SGB vs DMG border diff={diff:.1f}%")
    print(f"  {'PASS' if passed else 'FAIL'}")
    return passed


def test_license_screen(tmpdir):
    """License screen opens and shows copyright text."""
    print("Test: License screen")
    gba = tmpdir / "t.gba"
    if not compile_sml2(gba):
        return False
    menu = str(tmpdir / "menu.bmp")
    license_scr = str(tmpdir / "license.bmp")

    t = 2000
    inputs = ["600:Start", "900:Start", f"{t}:L+R"]
    t += 200
    # Down×10 → License
    inputs += menu_down(10, t)
    t += 10 * MENU_GAP
    inputs += [f"{t}:A"]
    t += 300

    run(gba, t + 500, inputs,
        screenshots=[f"2200:{menu}", f"{t}:{license_scr}"])

    d = menu_diff_pct(menu, license_scr)
    passed = d > 5
    print(f"  License diff: {d:.1f}% {'PASS' if passed else 'FAIL'}")
    return passed


# test_sram_persistence used to live here and shell out to
# test_sram_writethrough.py. run_all_tests.py then ran that same script again
# as its own step, so the slowest suite in the tree executed twice per CI run
# for no added coverage. It belongs to the suite runner, which owns it now.


# (label, function) in execution order.  Kept as data so main() can run each
# one under its own error handler.
TESTS = [
    ("Quicksave/load round-trip", test_quicksave_roundtrip),
    ("Quicksave persistence", test_quicksave_persistence),
    ("Menu open/close", test_menu_open_close),
    ("Menu save/load state", test_menu_save_load_state),
    ("Display submenu", test_display_submenu),
    ("Other Settings submenu", test_other_settings_submenu),
    ("Speed Hacks submenu", test_speed_hacks_submenu),
    ("Autofire B toggle", test_autofire_toggle),
    ("Manage SRAM", test_manage_sram),
    ("Restart", test_restart),
    ("License screen", test_license_screen),
    # Behavioral tests: verify actual setting effects
    ("A autofire behavior", test_a_autofire_behavior),
    ("VSync behavior", test_vsync_behavior),
    ("FPS-Meter behavior", test_fps_meter_behavior),
    ("Autosleep behavior", test_autosleep_behavior),
    ("Swap A-B behavior", test_swap_ab_behavior),
    ("Autoload state behavior", test_autoload_state_behavior),
    ("Palette behavior", test_palette_behavior),
    # Gamma removed from emulator — no test needed
    ("SGB Palette Number behavior", test_sgb_palette_number_behavior),
    ("Double Speed behavior", test_double_speed_behavior),
    ("LCD scanline hack behavior", test_lcd_scanline_hack_behavior),
    ("Identify as GBA behavior", test_identify_as_gba_behavior),
    ("Game Boy type behavior", test_gameboy_type_behavior),
    ("Auto SGB border behavior", test_auto_sgb_border_behavior),
]


def main():
    if _ADDR_ERROR is not None:
        print(f"ERROR: {_ADDR_ERROR}")
        sys.exit(1)
    if not all(p.exists() for p in [RUNNER, EMULATOR, SML2_ROM]):
        print("ERROR: missing prerequisites")
        sys.exit(1)

    results = []

    def record(name, fn, arg):
        """Run one test, converting any escape into a FAIL for that test.

        Tests used to be called inline in a single expression list with no
        error handling, and each of them gave its own temp directory to a
        runner whose exit status nobody checked.  One failed run left its
        screenshots unwritten, the next Image.open raised FileNotFoundError,
        and that exception propagated out of main() -- so a single broken
        test aborted the suite and every test after it went unreported (and
        unblamed).  Isolate them: one test's collapse costs exactly one FAIL.
        """
        try:
            return results.append((name, bool(fn(arg))))
        except RunnerError as exc:
            print(f"  ERROR: {exc}")
        except (OSError, ValueError) as exc:
            # Missing/short dump files and unreadable or mismatched images.
            print(f"  ERROR: {type(exc).__name__}: {exc}")
        results.append((name, False))

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        for name, fn in TESTS:
            record(name, fn, tmpdir)

    print(f"\n{'='*60}")
    passed = sum(1 for _, r in results if r)
    failed = sum(1 for _, r in results if not r)
    for name, r in results:
        print(f"  {'PASS' if r else 'FAIL'}: {name}")
    print(f"\nMenu tests: {passed} passed, {failed} failed")
    if len(results) != len(TESTS):
        print(f"ERROR: {len(TESTS)} tests expected, {len(results)} reported")
        sys.exit(1)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
