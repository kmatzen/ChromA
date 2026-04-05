#!/usr/bin/env python3
"""Generate an HTML visual diff report from test_roms/run_tests.py --diff-dir output.

Usage:
    python3 test_roms/run_tests.py --diff-dir /tmp/diffs
    python3 test_roms/generate_diff_report.py /tmp/diffs /tmp/report.html
"""

import base64
import sys
from pathlib import Path


def img_to_data_uri(path):
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <diff-dir> <output.html>")
        sys.exit(1)

    diff_dir = Path(sys.argv[1])
    output = Path(sys.argv[2])

    # Find all comparison images
    comparisons = sorted(diff_dir.glob("*_comparison.png"))
    if not comparisons:
        print("No comparison images found")
        # Write empty report
        output.write_text("<html><body><h1>No visual regressions</h1></body></html>")
        return

    # Group by test name
    tests = {}
    for comp in comparisons:
        # Format: TestName_screenshot_comparison.png
        name = comp.stem.replace("_comparison", "")
        test_name = "_".join(name.rsplit("_", 1)[:-1]) if "_" in name else name
        screenshot = name.rsplit("_", 1)[-1] if "_" in name else "final"

        expected = diff_dir / f"{name}_expected.png"
        actual = diff_dir / f"{name}_actual.png"
        diff = diff_dir / f"{name}_diff.png"

        if test_name not in tests:
            tests[test_name] = []
        tests[test_name].append({
            "screenshot": screenshot,
            "comparison": comp,
            "expected": expected if expected.exists() else None,
            "actual": actual if actual.exists() else None,
            "diff": diff if diff.exists() else None,
        })

    html = []
    html.append("""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Visual Regression Report</title>
<style>
  body { background: #1a1a1a; color: #ccc; font-family: system-ui, sans-serif; margin: 0; padding: 20px; }
  h1 { color: #5bf; }
  h2 { color: #fa0; margin-top: 30px; border-bottom: 1px solid #333; padding-bottom: 5px; }
  h3 { color: #aaa; font-size: 0.9em; }
  .test { margin-bottom: 40px; }
  .screenshots { display: flex; flex-wrap: wrap; gap: 20px; }
  .shot { background: #222; border-radius: 8px; padding: 10px; }
  .shot img { image-rendering: pixelated; border: 1px solid #333; }
  .label { font-size: 12px; color: #888; margin-bottom: 4px; }
  .tabs { display: flex; gap: 2px; margin-bottom: 8px; }
  .tab { padding: 4px 12px; background: #333; border-radius: 4px 4px 0 0; cursor: pointer; font-size: 12px; }
  .tab.active { background: #444; color: #5bf; }
  .view { display: none; }
  .view.active { display: block; }
  .summary { background: #222; padding: 15px; border-radius: 8px; margin-bottom: 20px; }
  .pass { color: #0fa; }
  .fail { color: #f55; }
</style>
</head>
<body>
<h1>Visual Regression Report</h1>
""")

    html.append(f'<div class="summary">{len(tests)} test(s) with differences, {sum(len(v) for v in tests.values())} screenshot(s)</div>')

    idx = 0
    for test_name, shots in tests.items():
        html.append(f'<div class="test"><h2>{test_name}</h2>')
        html.append('<div class="screenshots">')

        for shot in shots:
            html.append(f'<div class="shot">')
            html.append(f'<h3>{shot["screenshot"]}</h3>')

            tabs_id = f"tabs_{idx}"
            html.append(f'<div class="tabs">')
            for i, (label, key) in enumerate([("Expected", "expected"), ("Actual", "actual"), ("Diff", "diff"), ("Side-by-side", "comparison")]):
                active = " active" if i == 3 else ""
                html.append(f'<div class="tab{active}" onclick="showTab(\'{tabs_id}\',{i})">{label}</div>')
            html.append('</div>')

            for i, (label, key) in enumerate([("expected", "expected"), ("actual", "actual"), ("diff", "diff"), ("comparison", "comparison")]):
                path = shot.get(key) or shot.get("comparison")
                active = " active" if i == 3 else ""
                if path and path.exists():
                    uri = img_to_data_uri(path)
                    html.append(f'<div class="view{active}" id="{tabs_id}_{i}"><img src="{uri}" width="720"></div>')
                else:
                    html.append(f'<div class="view{active}" id="{tabs_id}_{i}"><p>Not available</p></div>')

            html.append('</div>')
            idx += 1

        html.append('</div></div>')

    html.append("""
<script>
function showTab(group, idx) {
  for (let i = 0; i < 4; i++) {
    document.getElementById(group + '_' + i).className = 'view' + (i === idx ? ' active' : '');
  }
  const tabs = document.getElementById(group)?.parentElement?.querySelector('.tabs');
  if (tabs) {
    Array.from(tabs.children).forEach((t, i) => {
      t.className = 'tab' + (i === idx ? ' active' : '');
    });
  }
}
</script>
</body></html>
""")

    output.write_text("\n".join(html))
    print(f"Report: {output} ({len(tests)} tests, {sum(len(v) for v in tests.values())} screenshots)")


if __name__ == "__main__":
    main()
