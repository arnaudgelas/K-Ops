#!/usr/bin/env python3
"""check_doc_links.py — modest, stdlib-only Markdown link checker for docs/.

Scope (deliberately narrow):
- Verifies that *internal* relative links in `docs/*.md` resolve to a file that
  exists on disk (and, when a `#anchor` is present, that a matching heading
  exists in the target Markdown file).
- *Lists* external links (http/https/mailto) so a human can eyeball them. It does
  NOT fetch them.

IMPORTANT — what this does NOT do:
A live link is not a correct characterization. This checker only proves a link
*resolves*; it says nothing about whether the linked page still describes what the
prose claims it describes. Comparator projects change their feature surface without
changing their URL. Treat green output here as "no broken paths", never as
"competitive claims are still accurate."

Usage:
    python3 scripts/check_doc_links.py            # check docs/*.md
    python3 scripts/check_doc_links.py path/to.md # check specific file(s)

Exit code: 0 if no broken internal links, 1 otherwise. External links never fail
the run (they are reported, not fetched). No third-party dependencies.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"

# [text](target)  — capture the target, ignoring images' leading ! is fine (still a path check)
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")


def slugify(heading: str) -> str:
    """GitHub-style heading anchor slug (good enough for internal cross-refs)."""
    text = heading.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    return text


def headings_of(path: Path) -> set[str]:
    slugs: set[str] = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            m = HEADING_RE.match(line)
            if m:
                slugs.add(slugify(m.group(1)))
    except OSError:
        pass
    return slugs


def check_file(md_path: Path) -> tuple[list[str], list[str]]:
    """Return (broken_internal, external) findings for one Markdown file."""
    broken: list[str] = []
    external: list[str] = []
    text = md_path.read_text(encoding="utf-8")
    for target in LINK_RE.findall(text):
        target = target.strip()
        if not target:
            continue
        # Strip an optional "title": [x](path "title")
        target = target.split(" ", 1)[0].strip()
        if target.startswith(("http://", "https://", "mailto:")):
            external.append(target)
            continue
        if target.startswith("#"):
            anchor = target[1:]
            if slugify(anchor) not in headings_of(md_path):
                broken.append(f"{md_path.name}: missing in-page anchor {target}")
            continue
        path_part, _, anchor = target.partition("#")
        resolved = (md_path.parent / path_part).resolve()
        if not resolved.exists():
            broken.append(f"{md_path.name}: broken link {target} -> {path_part}")
            continue
        if anchor and resolved.suffix.lower() == ".md":
            if slugify(anchor) not in headings_of(resolved):
                broken.append(f"{md_path.name}: {path_part} exists but anchor #{anchor} not found")
    return broken, external


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        files = [Path(a).resolve() for a in argv[1:]]
    else:
        files = sorted(DOCS_DIR.glob("*.md"))
    if not files:
        print("no markdown files to check", file=sys.stderr)
        return 0

    all_broken: list[str] = []
    all_external: list[str] = []
    for f in files:
        broken, external = check_file(f)
        all_broken.extend(broken)
        all_external.extend(external)

    if all_external:
        print("External links (NOT fetched — verify characterization by hand):")
        for url in sorted(set(all_external)):
            print(f"  - {url}")
        print()

    if all_broken:
        print("BROKEN internal links:")
        for b in all_broken:
            print(f"  - {b}")
        return 1

    print(f"OK: {len(files)} file(s) checked, no broken internal links.")
    print("Reminder: resolving links != correct characterization.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
