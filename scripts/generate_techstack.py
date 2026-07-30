#!/usr/bin/env python3
"""
Scans every public repo owned by GH_USERNAME and generates a dynamic
"Tech Stack" section with two rows:
  - Languages: aggregated from GitHub's own per-repo language byte counts
    (this is fully accurate -- same data source GitHub itself uses).
  - Frameworks & Tools: inferred by scanning each repo's dependency/config
    files (package.json, requirements.txt, Dockerfile, etc.) for known
    signatures. This is best-effort: it only catches what's declared in a
    dependency file or present as a config file, not everything you've
    ever touched.

Environment variables:
  GH_USERNAME     - GitHub username to scan (required)
  GH_TOKEN        - token for GitHub API auth (required in practice --
                    unauthenticated requests are capped at 60/hr and will
                    fail on any real profile). In the Action this is
                    ${{ secrets.GITHUB_TOKEN }}, auto-provided, no setup needed.
  INCLUDE_FORKS   - "true" to include forked repos in language stats (default: false)
  TOP_N_LANGUAGES - how many languages to show, most-used first (default: 10)

Output:
  dist/tech-stack.md   - standalone markdown fragment (always written)
  README.md            - if it contains the markers below, the section
                          between them is replaced in place:
                            <!-- TECH-STACK:START -->
                            <!-- TECH-STACK:END -->
"""

import json
import os
import sys
import base64
import urllib.error
import urllib.parse
import urllib.request

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dist")
README_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "README.md")
API = "https://api.github.com"

START_MARKER = "<!-- TECH-STACK:START -->"
END_MARKER = "<!-- TECH-STACK:END -->"

# label -> (badge color hex, shields.io logo slug, logo color)
LANGUAGE_BADGES = {
    "C++": ("00599C", "cplusplus", "white"),
    "Java": ("ED8B00", "openjdk", "white"),
    "Python": ("3776AB", "python", "white"),
    "JavaScript": ("F7DF1E", "javascript", "black"),
    "TypeScript": ("3178C6", "typescript", "white"),
    "C": ("A8B9CC", "c", "black"),
    "C#": ("239120", "csharp", "white"),
    "Go": ("00ADD8", "go", "white"),
    "Rust": ("000000", "rust", "white"),
    "PHP": ("777BB4", "php", "white"),
    "Ruby": ("CC342D", "ruby", "white"),
    "Kotlin": ("7F52FF", "kotlin", "white"),
    "Swift": ("F05138", "swift", "white"),
    "Dart": ("0175C2", "dart", "white"),
    "HTML": ("E34F26", "html5", "white"),
    "CSS": ("1572B6", "css3", "white"),
    "Shell": ("4EAA25", "gnubash", "white"),
    "Jupyter Notebook": ("F37626", "jupyter", "white"),
}

# signature -> (label, color hex, logo slug, logo color)
# "kind" tells the scanner how to detect it:
#   root_file     -> exact filename present at repo root
#   pkg_dep       -> key present in package.json dependencies/devDependencies
#   text_contains -> substring present in a given file's raw text
TOOL_SIGNATURES = [
    {"kind": "root_file", "match": "Dockerfile", "label": "Docker", "color": "2496ED", "logo": "docker", "logoColor": "white"},
    {"kind": "root_file", "match": "docker-compose.yml", "label": "Docker Compose", "color": "2496ED", "logo": "docker", "logoColor": "white"},
    {"kind": "root_file", "match": "tailwind.config.js", "label": "Tailwind", "color": "06B6D4", "logo": "tailwindcss", "logoColor": "white"},
    {"kind": "root_file", "match": "tailwind.config.ts", "label": "Tailwind", "color": "06B6D4", "logo": "tailwindcss", "logoColor": "white"},
    {"kind": "root_file", "match": "next.config.js", "label": "Next.js", "color": "000000", "logo": "nextdotjs", "logoColor": "white"},
    {"kind": "root_file", "match": "next.config.mjs", "label": "Next.js", "color": "000000", "logo": "nextdotjs", "logoColor": "white"},
    {"kind": "root_file", "match": "next.config.ts", "label": "Next.js", "color": "000000", "logo": "nextdotjs", "logoColor": "white"},
    {"kind": "root_file", "match": "vite.config.js", "label": "Vite", "color": "646CFF", "logo": "vite", "logoColor": "white"},
    {"kind": "root_file", "match": "vite.config.ts", "label": "Vite", "color": "646CFF", "logo": "vite", "logoColor": "white"},
    {"kind": "root_file", "match": "angular.json", "label": "Angular", "color": "DD0031", "logo": "angular", "logoColor": "white"},
    {"kind": "root_file", "match": "vue.config.js", "label": "Vue.js", "color": "4FC08D", "logo": "vuedotjs", "logoColor": "white"},
    {"kind": "root_file", "match": "Gemfile", "label": "Ruby on Rails", "color": "CC0000", "logo": "rubyonrails", "logoColor": "white"},
    {"kind": "root_file", "match": "firebase.json", "label": "Firebase", "color": "FFCA28", "logo": "firebase", "logoColor": "black"},
    {"kind": "root_file", "match": ".github/workflows", "label": "GitHub Actions", "color": "2088FF", "logo": "githubactions", "logoColor": "white"},

    {"kind": "pkg_dep", "match": "react", "label": "React", "color": "20232A", "logo": "react", "logoColor": "61DAFB"},
    {"kind": "pkg_dep", "match": "next", "label": "Next.js", "color": "000000", "logo": "nextdotjs", "logoColor": "white"},
    {"kind": "pkg_dep", "match": "vue", "label": "Vue.js", "color": "4FC08D", "logo": "vuedotjs", "logoColor": "white"},
    {"kind": "pkg_dep", "match": "@angular/core", "label": "Angular", "color": "DD0031", "logo": "angular", "logoColor": "white"},
    {"kind": "pkg_dep", "match": "express", "label": "Express", "color": "000000", "logo": "express", "logoColor": "white"},
    {"kind": "pkg_dep", "match": "@nestjs/core", "label": "NestJS", "color": "E0234E", "logo": "nestjs", "logoColor": "white"},
    {"kind": "pkg_dep", "match": "tailwindcss", "label": "Tailwind", "color": "06B6D4", "logo": "tailwindcss", "logoColor": "white"},
    {"kind": "pkg_dep", "match": "mongoose", "label": "MongoDB", "color": "47A248", "logo": "mongodb", "logoColor": "white"},
    {"kind": "pkg_dep", "match": "firebase", "label": "Firebase", "color": "FFCA28", "logo": "firebase", "logoColor": "black"},
    {"kind": "pkg_dep", "match": "redux", "label": "Redux", "color": "764ABC", "logo": "redux", "logoColor": "white"},
    {"kind": "pkg_dep", "match": "@reduxjs/toolkit", "label": "Redux", "color": "764ABC", "logo": "redux", "logoColor": "white"},
    {"kind": "pkg_dep", "match": "socket.io", "label": "Socket.io", "color": "010101", "logo": "socketdotio", "logoColor": "white"},
    {"kind": "pkg_dep", "match": "graphql", "label": "GraphQL", "color": "E10098", "logo": "graphql", "logoColor": "white"},
    {"kind": "pkg_dep", "match": "@prisma/client", "label": "Prisma", "color": "2D3748", "logo": "prisma", "logoColor": "white"},
    {"kind": "pkg_dep", "match": "prisma", "label": "Prisma", "color": "2D3748", "logo": "prisma", "logoColor": "white"},
    {"kind": "pkg_dep", "match": "jest", "label": "Jest", "color": "C21325", "logo": "jest", "logoColor": "white"},
    {"kind": "pkg_dep", "match": "vite", "label": "Vite", "color": "646CFF", "logo": "vite", "logoColor": "white"},
    {"kind": "pkg_dep", "match": "webpack", "label": "Webpack", "color": "8DD6F9", "logo": "webpack", "logoColor": "black"},
    {"kind": "pkg_dep", "match": "electron", "label": "Electron", "color": "47848F", "logo": "electron", "logoColor": "white"},

    {"kind": "text_contains", "file": "requirements.txt", "match": "django", "label": "Django", "color": "092E20", "logo": "django", "logoColor": "white"},
    {"kind": "text_contains", "file": "requirements.txt", "match": "flask", "label": "Flask", "color": "000000", "logo": "flask", "logoColor": "white"},
    {"kind": "text_contains", "file": "requirements.txt", "match": "fastapi", "label": "FastAPI", "color": "009688", "logo": "fastapi", "logoColor": "white"},
    {"kind": "text_contains", "file": "requirements.txt", "match": "tensorflow", "label": "TensorFlow", "color": "FF6F00", "logo": "tensorflow", "logoColor": "white"},
    {"kind": "text_contains", "file": "requirements.txt", "match": "torch", "label": "PyTorch", "color": "EE4C2C", "logo": "pytorch", "logoColor": "white"},
    {"kind": "text_contains", "file": "requirements.txt", "match": "scikit-learn", "label": "scikit-learn", "color": "F7931E", "logo": "scikitlearn", "logoColor": "white"},
    {"kind": "text_contains", "file": "requirements.txt", "match": "pandas", "label": "pandas", "color": "150458", "logo": "pandas", "logoColor": "white"},
    {"kind": "text_contains", "file": "requirements.txt", "match": "numpy", "label": "NumPy", "color": "013243", "logo": "numpy", "logoColor": "white"},
    {"kind": "text_contains", "file": "requirements.txt", "match": "sqlalchemy", "label": "SQLAlchemy", "color": "D71F00", "logo": "python", "logoColor": "white"},
]


def gh_request(path, token, params=None):
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "User-Agent": "tech-stack-generator",
        "Accept": "application/vnd.github+json",
        **({"Authorization": f"Bearer {token}"} if token else {}),
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_repos(username, token, include_forks):
    repos, page = [], 1
    while True:
        batch = gh_request(f"/users/{username}/repos", token,
                            {"per_page": 100, "page": page, "type": "owner"})
        if not batch:
            break
        for r in batch:
            if r.get("fork") and not include_forks:
                continue
            repos.append(r)
        if len(batch) < 100:
            break
        page += 1
    return repos


def get_languages(owner, repo, token):
    try:
        return gh_request(f"/repos/{owner}/{repo}/languages", token)
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"[warn] languages fetch failed for {repo}: {e}", file=sys.stderr)
        return {}


def get_root_contents(owner, repo, token):
    try:
        data = gh_request(f"/repos/{owner}/{repo}/contents/", token)
        return {item["name"]: item for item in data if item.get("type") == "file"}
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"[warn] contents fetch failed for {repo}: {e}", file=sys.stderr)
        return {}


def get_file_text(owner, repo, filename, token):
    try:
        data = gh_request(f"/repos/{owner}/{repo}/contents/{filename}", token)
        if data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
    except (urllib.error.URLError, urllib.error.HTTPError):
        pass
    return ""


def detect_tools_for_repo(owner, repo, token, found):
    root_files = get_root_contents(owner, repo, token)

    for sig in TOOL_SIGNATURES:
        if sig["kind"] == "root_file" and sig["match"] in root_files:
            found.add(sig["label"])

    if "package.json" in root_files:
        pkg_text = get_file_text(owner, repo, "package.json", token)
        try:
            pkg = json.loads(pkg_text) if pkg_text else {}
        except json.JSONDecodeError:
            pkg = {}
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        for sig in TOOL_SIGNATURES:
            if sig["kind"] == "pkg_dep" and sig["match"] in deps:
                found.add(sig["label"])

    if "requirements.txt" in root_files:
        req_text = get_file_text(owner, repo, "requirements.txt", token).lower()
        for sig in TOOL_SIGNATURES:
            if sig["kind"] == "text_contains" and sig["file"] == "requirements.txt" and sig["match"] in req_text:
                found.add(sig["label"])


def badge_md(label, color, logo, logo_color):
    safe_label = urllib.parse.quote(label, safe="")
    return f"![{label}](https://img.shields.io/badge/{safe_label}-{color}?style=flat-square&logo={logo}&logoColor={logo_color})"


def build_markdown(lang_totals, tools_found, top_n, repo_count):
    lang_order = sorted(
        (l for l in lang_totals if l in LANGUAGE_BADGES),
        key=lambda l: lang_totals[l], reverse=True
    )[:top_n]

    lang_badges = " ".join(
        badge_md(l, *LANGUAGE_BADGES[l]) for l in lang_order
    ) or "_No recognized languages found yet._"

    tool_lookup = {sig["label"]: sig for sig in TOOL_SIGNATURES}
    tool_badges = " ".join(
        badge_md(t, tool_lookup[t]["color"], tool_lookup[t]["logo"], tool_lookup[t]["logoColor"])
        for t in sorted(tools_found)
    ) or "_No recognized frameworks/tools found yet._"

    return (
        f"**Languages** _(auto-detected across {repo_count} public repos)_<br/>\n"
        f"{lang_badges}\n\n"
        f"**Frameworks & Tools** _(auto-detected from dependency files)_<br/>\n"
        f"{tool_badges}\n"
    )


def update_readme(section_md):
    if not os.path.exists(README_PATH):
        print("[skip] No README.md found next to the repo root; skipping in-place update.")
        return
    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    if START_MARKER not in content or END_MARKER not in content:
        print(f"[skip] README.md has no {START_MARKER} / {END_MARKER} markers. "
              f"Add them where you want the tech stack to appear, then re-run.")
        return

    before, rest = content.split(START_MARKER, 1)
    _, after = rest.split(END_MARKER, 1)
    new_content = f"{before}{START_MARKER}\n{section_md}\n{END_MARKER}{after}"

    if new_content != content:
        with open(README_PATH, "w", encoding="utf-8") as f:
            f.write(new_content)
        print("[ok] README.md tech stack section updated.")
    else:
        print("[skip] README.md tech stack section unchanged.")


def main():
    username = os.environ.get("GH_USERNAME", "").strip()
    token = os.environ.get("GH_TOKEN", "").strip()
    include_forks = os.environ.get("INCLUDE_FORKS", "false").strip().lower() in ("1", "true", "yes")
    top_n = int(os.environ.get("TOP_N_LANGUAGES", "10"))

    if not username:
        print("[error] Set GH_USERNAME.", file=sys.stderr)
        sys.exit(1)
    if not token:
        print("[warn] No GH_TOKEN set -- unauthenticated GitHub API calls are capped "
              "at 60/hr and will likely fail partway through. Set GH_TOKEN "
              "(use ${{ secrets.GITHUB_TOKEN }} in Actions).", file=sys.stderr)

    repos = list_repos(username, token, include_forks)
    print(f"[info] Scanning {len(repos)} repos for @{username}...")

    lang_totals = {}
    tools_found = set()

    for r in repos:
        name = r["name"]
        langs = get_languages(username, name, token)
        for lang, byte_count in langs.items():
            lang_totals[lang] = lang_totals.get(lang, 0) + byte_count
        detect_tools_for_repo(username, name, token, tools_found)

    section_md = build_markdown(lang_totals, tools_found, top_n, len(repos))

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "tech-stack.md"), "w", encoding="utf-8") as f:
        f.write(section_md)
    print("[ok] wrote dist/tech-stack.md")

    update_readme(section_md)


if __name__ == "__main__":
    main()
