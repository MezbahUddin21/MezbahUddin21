#!/usr/bin/env python3
"""
Generates GitHub-style submission heatmaps (as SVG) for Codeforces and CodeChef.

- Codeforces data comes from the official public API (codeforces.com/api/user.status),
  so it never breaks or rate-limits unexpectedly.
- CodeChef has no official public API, so this uses the community-maintained
  codechef-stats-api-two.vercel.app scraper. Unlike some older CodeChef scrapers,
  it returns full submission history (years, not just ~6 months), so with
  ALL_YEARS=true both heatmaps render the same way: one stacked calendar row
  per year.

Environment variables:
  CF_HANDLE   - your Codeforces handle (required for the CF heatmap)
  CC_HANDLE   - your CodeChef handle (optional; skipped if not set)
  ALL_YEARS   - "true" for a stacked multi-year calendar (like GitHub's own
                heatmap, one row per year); "false"/unset for a single strip
                covering roughly the last year.

Output:
  dist/cf-heatmap.svg
  dist/codechef-heatmap.svg   (only if CC_HANDLE is set and data is available)
"""

import datetime
import json
import os
import sys
import urllib.error
import urllib.request

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dist")

# Colors tuned to match a github_dark-style profile README
BG = "#0d1117"
EMPTY_CELL = "#161b22"
BORDER = "#30363d"
TEXT = "#c9d1d9"
LEVELS = ["#0e4429", "#006d32", "#26a641", "#39d353"]  # low -> high intensity


def fetch_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (heatmap-action)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_cf_daily_counts(handle, days=371):
    """Returns {YYYY-MM-DD: count} of accepted submissions for the last `days` days.
    Pass days=None to fetch the account's entire history (no cutoff)."""
    url = f"https://codeforces.com/api/user.status?handle={handle}"
    try:
        data = fetch_json(url)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
        print(f"[warn] Codeforces fetch failed: {e}", file=sys.stderr)
        return {}

    if data.get("status") != "OK":
        print(f"[warn] Codeforces API error: {data.get('comment')}", file=sys.stderr)
        return {}

    cutoff = None
    if days is not None:
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    counts = {}
    solved_today = set()  # avoid double-counting repeated AC on the same problem/day
    for sub in data["result"]:
        if sub.get("verdict") != "OK":
            continue
        ts = datetime.datetime.utcfromtimestamp(sub["creationTimeSeconds"])
        if cutoff is not None and ts < cutoff:
            continue
        day = ts.date().isoformat()
        problem = sub.get("problem", {})
        key = (day, problem.get("contestId"), problem.get("index"))
        if key in solved_today:
            continue
        solved_today.add(key)
        counts[day] = counts.get(day, 0) + 1
    return counts


def get_cc_daily_counts(handle):
    """Returns {YYYY-MM-DD: count} using the codechef-stats-api.vercel.app mirror.
    This API returns the account's full daily submission history (its own docs
    example spans 2024-2026), unlike some older CodeChef scrapers limited to
    ~6 months -- so with ALL_YEARS=true you get a real multi-year heatmap.

    Note: the older codechef-api.vercel.app scraper this script originally used
    went down (its free Vercel deployment was disabled -- a hosting-side outage
    on the maintainer's end, unrelated to your handle). This uses a different,
    actively-maintained mirror with a documented /{handle}/heatmap endpoint instead."""
    if not handle:
        return {}
    url = f"https://codechef-stats-api-two.vercel.app/{handle}/heatmap"
    try:
        data = fetch_json(url)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
        print(f"[warn] CodeChef fetch failed: {e}", file=sys.stderr)
        return {}

    if data.get("status") != "success":
        print(f"[warn] CodeChef API error: {data.get('message')}", file=sys.stderr)
        return {}

    contributions = (data.get("data") or {}).get("dailyContributions") or []
    counts = {}
    for entry in contributions:
        date = entry.get("date")
        count = entry.get("count", 0)
        if date:
            counts[date] = int(count)
    if not counts:
        print("[warn] CodeChef response had no usable heatmap data (handle may not exist)", file=sys.stderr)
    return counts


def color_for(count, max_count):
    if count <= 0:
        return EMPTY_CELL
    ratio = min(count / max_count, 1.0) if max_count else 1.0
    idx = min(int(ratio * len(LEVELS)), len(LEVELS) - 1)
    return LEVELS[idx]


def build_svg(counts, title, weeks=53):
    cell, gap = 11, 3
    left_pad, top_pad, right_pad, bottom_pad = 20, 32, 16, 14

    today = datetime.date.today()
    start = today - datetime.timedelta(days=weeks * 7 - 1)
    start -= datetime.timedelta(days=(start.weekday() + 1) % 7)  # snap back to Sunday

    max_count = max(counts.values()) if counts else 0
    total = sum(counts.values())

    svg_w = left_pad + weeks * (cell + gap) + right_pad
    svg_h = top_pad + 7 * (cell + gap) + bottom_pad

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {svg_w} {svg_h}" '
        f'font-family="Fira Code, ui-monospace, monospace">',
        f'<rect width="100%" height="100%" fill="{BG}" rx="8"/>',
        f'<text x="{left_pad}" y="16" fill="{TEXT}" font-size="12" font-weight="700">'
        f'{title} &#183; {total} submissions (last {weeks} wks)</text>',
    ]

    month_labels_done = set()
    d = start
    for w in range(weeks):
        # Month label above the first week that contains day 1-7 of a new month
        month_key = (d.year, d.month)
        if d.day <= 7 and month_key not in month_labels_done:
            month_labels_done.add(month_key)
            x = left_pad + w * (cell + gap)
            parts.append(
                f'<text x="{x}" y="{top_pad - 6}" fill="{TEXT}" font-size="8">'
                f'{d.strftime("%b")}</text>'
            )
        for day in range(7):
            date_str = d.isoformat()
            c = counts.get(date_str, 0)
            x = left_pad + w * (cell + gap)
            y = top_pad + day * (cell + gap)
            fill = color_for(c, max_count)
            parts.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" '
                f'fill="{fill}" stroke="{BORDER}" stroke-width="0.5">'
                f'<title>{date_str}: {c} submission{"s" if c != 1 else ""}</title></rect>'
            )
            d += datetime.timedelta(days=1)

    parts.append("</svg>")
    return "\n".join(parts)


def build_multi_year_svg(counts, title):
    """One calendar row per calendar year that has any data, newest year on top.
    This is how GitHub itself handles multi-year history (a year selector) --
    since a README image can't be interactive, we stack the years instead."""
    if not counts:
        years = [datetime.date.today().year]
    else:
        years = sorted({int(d[:4]) for d in counts}, reverse=True)

    cell, gap = 10, 3
    weeks = 53
    left_pad, top_pad, right_pad, bottom_pad = 46, 36, 16, 10
    row_h = 7 * (cell + gap)
    row_gap = 16

    max_count = max(counts.values()) if counts else 0
    total = sum(counts.values())

    svg_w = left_pad + weeks * (cell + gap) + right_pad
    svg_h = top_pad + len(years) * row_h + (len(years) - 1) * row_gap + bottom_pad

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {svg_w} {svg_h}" '
        f'font-family="Fira Code, ui-monospace, monospace">',
        f'<rect width="100%" height="100%" fill="{BG}" rx="8"/>',
        f'<text x="{left_pad}" y="16" fill="{TEXT}" font-size="12" font-weight="700">'
        f'{title} &#183; {total} submissions total ({years[-1]}-{years[0]})</text>',
    ]

    y_cursor = top_pad
    for year in years:
        jan1 = datetime.date(year, 1, 1)
        start = jan1 - datetime.timedelta(days=(jan1.weekday() + 1) % 7)  # back to Sunday
        year_total = sum(v for k, v in counts.items() if k.startswith(str(year)))

        parts.append(
            f'<text x="0" y="{y_cursor + row_h / 2 + 3}" fill="{TEXT}" font-size="10" '
            f'font-weight="700">{year}</text>'
        )

        month_labels_done = set()
        d = start
        for w in range(weeks):
            month_key = (d.year, d.month)
            if d.year == year and d.day <= 7 and month_key not in month_labels_done:
                month_labels_done.add(month_key)
                x = left_pad + w * (cell + gap)
                parts.append(
                    f'<text x="{x}" y="{y_cursor - 6}" fill="{TEXT}" font-size="7">'
                    f'{d.strftime("%b")}</text>'
                )
            for day in range(7):
                x = left_pad + w * (cell + gap)
                y = y_cursor + day * (cell + gap)
                if d.year == year:
                    date_str = d.isoformat()
                    c = counts.get(date_str, 0)
                    fill = color_for(c, max_count)
                    parts.append(
                        f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" '
                        f'fill="{fill}" stroke="{BORDER}" stroke-width="0.5">'
                        f'<title>{date_str}: {c} submission{"s" if c != 1 else ""}</title></rect>'
                    )
                # days that spill into the previous/next year are left blank (no rect)
                d += datetime.timedelta(days=1)

        parts.append(
            f'<text x="{svg_w - right_pad}" y="{y_cursor + row_h / 2 + 3}" '
            f'fill="{TEXT}" font-size="8" text-anchor="end">{year_total}</text>'
        )
        y_cursor += row_h + row_gap

    parts.append("</svg>")
    return "\n".join(parts)


def write_svg(path, svg):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"[ok] wrote {path}")


def main():
    cf_handle = os.environ.get("CF_HANDLE", "").strip()
    cc_handle = os.environ.get("CC_HANDLE", "").strip()
    all_years = os.environ.get("ALL_YEARS", "false").strip().lower() in ("1", "true", "yes")

    if not cf_handle and not cc_handle:
        print("[error] Set CF_HANDLE and/or CC_HANDLE env vars.", file=sys.stderr)
        sys.exit(1)

    if cf_handle:
        if all_years:
            cf_counts = get_cf_daily_counts(cf_handle, days=None)
            svg = build_multi_year_svg(cf_counts, f"Codeforces @{cf_handle}")
        else:
            cf_counts = get_cf_daily_counts(cf_handle, days=371)
            svg = build_svg(cf_counts, f"Codeforces @{cf_handle}", weeks=53)
        write_svg(os.path.join(OUT_DIR, "cf-heatmap.svg"), svg)

    if cc_handle:
        cc_counts = get_cc_daily_counts(cc_handle)
        if cc_counts:
            if all_years:
                svg = build_multi_year_svg(cc_counts, f"CodeChef @{cc_handle}")
            else:
                svg = build_svg(cc_counts, f"CodeChef @{cc_handle}", weeks=26)
            write_svg(os.path.join(OUT_DIR, "codechef-heatmap.svg"), svg)
        else:
            print("[skip] No CodeChef data available; leaving previous file untouched.")


if __name__ == "__main__":
    main()
