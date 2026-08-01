#!/usr/bin/env python3
"""
Generates a "problem coverage" SVG for CSES (cses.fi), based on the public
statistics grid at https://cses.fi/problemset/user/{CSES_USER_ID} -- no
login required, this page is publicly viewable.

Important: this is NOT a date-based activity calendar like the Codeforces/
CodeChef heatmaps. CSES doesn't expose per-day submission timestamps
anywhere publicly (confirmed -- even the account owner can't see that on
CSES itself). What CSES *does* show publicly is a grid of every problem in
the problem set, colored by whether you've solved it (green), attempted it
without success (red), or haven't tried it (gray) -- in problem-set order,
not calendar order. That's what this script renders.

Because I couldn't directly verify CSES's exact HTML markup while building
this (network-restricted sandbox), the cell parser uses the visible glyphs
(checkmark / cross / dash) rather than guessing CSS class names, and prints
a diagnostic summary every run. If the counts look wrong the first time you
run this in your real Action (which does have full internet access), check
the "Generate CSES heatmap" step's log -- it dumps a snippet of the raw grid
HTML specifically so a mismatch is easy to diagnose and fix in one pass.

Environment variables:
  CSES_USER_ID - your numeric CSES user id, e.g. 18428
                 (find it in the URL of your CSES profile page)

Output:
  dist/cses-heatmap.svg
"""

import datetime
import html
import os
import re
import sys
import urllib.error
import urllib.request

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dist")

BG = "#0d1117"
BORDER = "#30363d"
TEXT = "#c9d1d9"
SOLVED_COLOR = "#26a641"    # green
ATTEMPTED_COLOR = "#f85149" # red
UNTOUCHED_COLOR = "#161b22" # gray/empty

PROBLEMSET_URL = "https://cses.fi/problemset/"
USER_STATS_URL = "https://cses.fi/problemset/user/{uid}"

CHECK_CHARS = ("\u2713", "\u2714", "&#10003;", "&#10004;", "&check;")
CROSS_CHARS = ("\u2717", "\u2718", "&#10007;", "&#10008;", "&times;")
DASH_CHARS = ("\u2013", "\u2014", "-", "&ndash;", "&mdash;")


def fetch_html(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (cses-heatmap-action)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def get_problem_order():
    """Returns an ordered list of problem names by scraping the public task
    list, so grid cells can be labeled. Falls back to generic numbering if
    this fails for any reason -- labeling is a nice-to-have, not required
    for the grid itself to render."""
    try:
        page = fetch_html(PROBLEMSET_URL)
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"[warn] Could not fetch problem list for labels: {e}", file=sys.stderr)
        return []
    # Task links look like: <a href="/problemset/task/1068">Weird Algorithm</a>
    matches = re.findall(r'/problemset/task/\d+"[^>]*>([^<]+)</a>', page)
    return [html.unescape(m).strip() for m in matches]


def classify_cell(cell_html):
    for c in CHECK_CHARS:
        if c in cell_html:
            return "solved"
    for c in CROSS_CHARS:
        if c in cell_html:
            return "attempted"
    for c in DASH_CHARS:
        if c in cell_html:
            return "untouched"
    return None


def get_user_grid(user_id):
    url = USER_STATS_URL.format(uid=user_id)
    try:
        page = fetch_html(url)
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"[error] Could not fetch CSES stats page: {e}", file=sys.stderr)
        return None, None

    print(f"[debug] Fetched {len(page)} bytes from {url}")
    lowered = page.lower()
    if "login" in lowered and "solved tasks" not in lowered:
        print("[warn] Page mentions 'login' and has no 'Solved tasks' text -- "
              "likely got redirected to a login page instead of the public "
              "stats page. This can happen if CSES blocks generic script "
              "User-Agents.", file=sys.stderr)
    print("[debug] First 600 chars of fetched page:", file=sys.stderr)
    print(page[:600], file=sys.stderr)

    solved_match = re.search(r"Solved tasks:\s*(\d+)\s*/\s*(\d+)", page)
    solved_count = int(solved_match.group(1)) if solved_match else None
    total_count = int(solved_match.group(2)) if solved_match else None

    cells = re.findall(r"<td[^>]*>(.*?)</td>", page, re.DOTALL)
    statuses = []
    unclassified = 0
    for cell in cells:
        status = classify_cell(cell)
        if status is None:
            unclassified += 1
            continue
        statuses.append(status)

    print(f"[info] Parsed {len(statuses)} classified cells "
          f"({unclassified} unclassified/skipped) from {len(cells)} <td> tags.")
    if solved_count is not None:
        actual_solved = statuses.count("solved")
        print(f"[info] Page reports {solved_count}/{total_count} solved; "
              f"grid parse found {actual_solved} 'solved' cells.")
        if actual_solved != solved_count:
            print("[warn] Mismatch between reported solved count and parsed grid -- "
                  "the cell classifier may need adjusting. Raw snippet around first "
                  "table row for debugging:", file=sys.stderr)
            snippet_match = re.search(r"<table.*?</tr>", page, re.DOTALL)
            if snippet_match:
                print(snippet_match.group(0)[:1000], file=sys.stderr)
    else:
        print("[warn] Could not find 'Solved tasks: X/Y' text anywhere on the "
              "fetched page -- this page is very likely not the stats content "
              "we expected. See the [debug] snippet above.", file=sys.stderr)

    return statuses, (solved_count, total_count)


def build_svg(statuses, labels, solved_count, total_count, user_id, cols=20):
    cell, gap = 14, 3
    left_pad, top_pad, right_pad, bottom_pad = 16, 30, 16, 14

    rows = (len(statuses) + cols - 1) // cols if statuses else 1
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

    for i, status in enumerate(statuses):
        r, c = divmod(i, cols)
        x = left_pad + c * (cell + gap)
        y = top_pad + r * (cell + gap)
        fill = color_map.get(status, UNTOUCHED_COLOR)
        label = html.escape(labels[i]) if i < len(labels) else f"Problem {i + 1}"
        parts.append(
            f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" '
            f'fill="{fill}" stroke="{BORDER}" stroke-width="0.5">'
            f'<title>{label}: {status}</title></rect>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def main():
    user_id = os.environ.get("CSES_USER_ID", "").strip()
    if not user_id:
        print("[error] Set CSES_USER_ID (the numeric id from your CSES profile URL).",
              file=sys.stderr)
        sys.exit(1)

    labels = get_problem_order()
    statuses, (solved_count, total_count) = get_user_grid(user_id)

    if statuses is None:
        print("[skip] No data fetched; leaving any previous dist/cses-heatmap.svg untouched.")
        return

    svg = build_svg(statuses, labels, solved_count, total_count, user_id)
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "cses-heatmap.svg")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"[ok] wrote {out_path}")


if __name__ == "__main__":
    main()
