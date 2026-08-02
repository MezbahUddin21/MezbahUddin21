#!/usr/bin/env python3
"""
Generates a "problem coverage" SVG for CSES (cses.fi), based on the
statistics grid at https://cses.fi/problemset/user/{CSES_USER_ID}.

Important: this is NOT a date-based activity calendar like the Codeforces/
CodeChef heatmaps. CSES doesn't expose per-day submission timestamps
anywhere publicly, so there's no calendar-style "activity over time" data
available to build a real heatmap from. What CSES does show is a grid of
every problem in its problem set, colored by whether you've solved it
(green), attempted it without solving (red), or haven't tried it (gray) --
in problem-set order, not calendar order. That's what this renders.

This page requires an active CSES login session to load real data (it was
originally assumed to be public and isn't -- confirmed by testing). That
means this script can't run unattended in a scheduled Action the way the
other generators do. Instead:
  1. Open https://cses.fi/problemset/user/{your_id} while logged in.
  2. View page source, copy the full HTML.
  3. Save it to a local file (or paste it in when prompted).
  4. Run this script locally against that saved HTML file.
It reads real CSES markup: <a href="/problemset/task/ID/" title="Name"
class="task-score icon full|zero|">, matched exactly against a real page
sample rather than guessed.

Usage:
  python generate_cses.py path/to/saved_page.html [CSES_USER_ID]

Output:
  dist/cses-heatmap.svg
"""

import html
import os
import re
import sys

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dist")

BG = "#0d1117"
BORDER = "#30363d"
TEXT = "#c9d1d9"
SOLVED_COLOR = "#26a641"    # green -- "full" class
ATTEMPTED_COLOR = "#f85149" # red -- "zero" class
UNTOUCHED_COLOR = "#161b22" # gray -- plain "icon" class, no full/zero

CELL_RE = re.compile(
    r'<a href="/problemset/task/(\d+)/" title="([^"]*)" class="task-score icon( full| zero)?"'
)
SOLVED_LINE_RE = re.compile(r"Solved tasks:\s*(\d+)\s*/\s*(\d+)")


def parse_page(page_html):
    solved_match = SOLVED_LINE_RE.search(page_html)
    solved_count = int(solved_match.group(1)) if solved_match else None
    total_count = int(solved_match.group(2)) if solved_match else None

    cells = []
    for task_id, title, variant in CELL_RE.findall(page_html):
        if variant == " full":
            status = "solved"
        elif variant == " zero":
            status = "attempted"
        else:
            status = "untouched"
        cells.append({"task_id": task_id, "title": html.unescape(title), "status": status})

    print(f"[info] Parsed {len(cells)} problem cells.")
    if solved_count is not None:
        actual_solved = sum(1 for c in cells if c["status"] == "solved")
        print(f"[info] Page reports {solved_count}/{total_count} solved; "
              f"parse found {actual_solved} 'solved' cells.")
        if actual_solved != solved_count:
            print("[warn] Mismatch -- the saved HTML may be stale, truncated, "
                  "or from a different page than expected.", file=sys.stderr)

    return cells, solved_count, total_count


def build_svg(cells, solved_count, total_count, user_id, cols=20):
    cell, gap = 14, 3
    left_pad, top_pad, right_pad, bottom_pad = 16, 30, 16, 14

    rows = (len(cells) + cols - 1) // cols if cells else 1
    svg_w = left_pad + cols * (cell + gap) + right_pad
    svg_h = top_pad + rows * (cell + gap) + bottom_pad

    color_map = {
        "solved": SOLVED_COLOR,
        "attempted": ATTEMPTED_COLOR,
        "untouched": UNTOUCHED_COLOR,
    }

    title = f"CSES @{user_id}"
    if solved_count is not None:
        title += f" \u00b7 {solved_count}/{total_count} solved"

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {svg_w} {svg_h}" '
        f'font-family="Fira Code, ui-monospace, monospace">',
        f'<rect width="100%" height="100%" fill="{BG}" rx="8"/>',
        f'<text x="{left_pad}" y="16" fill="{TEXT}" font-size="12" font-weight="700">{title}</text>',
    ]

    for i, c in enumerate(cells):
        r, col = divmod(i, cols)
        x = left_pad + col * (cell + gap)
        y = top_pad + r * (cell + gap)
        fill = color_map.get(c["status"], UNTOUCHED_COLOR)
        label = html.escape(c["title"])
        parts.append(
            f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" '
            f'fill="{fill}" stroke="{BORDER}" stroke-width="0.5">'
            f'<title>{label}: {c["status"]}</title></rect>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def main():
    if len(sys.argv) < 2:
        print("Usage: python generate_cses.py path/to/saved_page.html [CSES_USER_ID]",
              file=sys.stderr)
        sys.exit(1)

    html_path = sys.argv[1]
    user_id = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("CSES_USER_ID", "unknown")

    with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
        page_html = f.read()

    cells, solved_count, total_count = parse_page(page_html)
    if not cells:
        print("[error] No problem cells found -- check the saved HTML is the "
              "real statistics page (view-source, not a screenshot or the "
              "rendered DOM export).", file=sys.stderr)
        sys.exit(1)

    svg = build_svg(cells, solved_count, total_count, user_id)
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "cses-heatmap.svg")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"[ok] wrote {out_path}")


if __name__ == "__main__":
    main()
