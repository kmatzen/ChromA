#!/usr/bin/env python3
"""Automated tests for all Goomba menu features.

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

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
RUNNER = SCRIPT_DIR / "mgba_runner"
COMPILER = SCRIPT_DIR / "goomba_compile.py"
EMULATOR = PROJECT_DIR / "jagoombacolor.gba"
SML2_ROM = SCRIPT_DIR / "Super Mario Land 2 - 6 Golden Coins (USA, Europe) (Rev 2).gb"

# Menu runs ~1 iteration per 2-3 mGBA frames.
# Use 120-frame gaps between inputs to ensure each registers exactly once.
MENU_GAP = 120


def run(gba, frames, inputs, screenshots=None, savefile=None):
    cmd = [str(RUNNER), str(gba), str(frames), "/dev/null"]
    for inp in inputs:
        cmd.extend(["--input", inp])
    for ss in (screenshots or []):
        cmd.extend(["--screenshot", ss])
    if savefile:
        cmd.extend(["--savefile", str(savefile)])
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300).returncode == 0


def pixel_diff_pct(a, b):
    ia = Image.open(a).convert("RGB")
    ib = Image.open(b).convert("RGB")
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


def menu_down(n, start_frame):
    """Generate Down×n inputs with proper spacing."""
    return [f"{start_frame + i * MENU_GAP}:Down" for i in range(n)]


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
    menu_ok = pixel_diff_pct(b, m) > 5
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
    d = pixel_diff_pct(menu, submenu)
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

    d = pixel_diff_pct(menu, submenu)
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


def test_sram_persistence(tmpdir):
    """SRAM write-through persists across sessions."""
    print("Test: SRAM persistence")
    result = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "test_sram_writethrough.py")],
        capture_output=True, text=True, timeout=600)
    for line in result.stdout.strip().split("\n")[-3:]:
        print(f"  {line}")
    return result.returncode == 0


def main():
    if not all(p.exists() for p in [RUNNER, EMULATOR, SML2_ROM]):
        print("ERROR: missing prerequisites")
        sys.exit(1)

    results = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        results.append(("Quicksave/load round-trip", test_quicksave_roundtrip(tmpdir)))
        results.append(("Quicksave persistence", test_quicksave_persistence(tmpdir)))
        results.append(("Menu open/close", test_menu_open_close(tmpdir)))
        results.append(("Menu save/load state", test_menu_save_load_state(tmpdir)))
        results.append(("Display submenu", test_display_submenu(tmpdir)))
        results.append(("Other Settings submenu", test_other_settings_submenu(tmpdir)))
        results.append(("Restart", test_restart(tmpdir)))
    results.append(("SRAM persistence", test_sram_persistence(None)))

    print(f"\n{'='*60}")
    passed = sum(1 for _, r in results if r)
    failed = sum(1 for _, r in results if not r)
    for name, r in results:
        print(f"  {'PASS' if r else 'FAIL'}: {name}")
    print(f"\nMenu tests: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
