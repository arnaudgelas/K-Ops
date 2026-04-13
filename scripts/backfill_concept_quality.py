from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent
CONCEPTS_DIR = ROOT / "notes" / "Concepts"
SOURCES_DIR = ROOT / "notes" / "Sources"

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
EVIDENCE_SECTION_RE = re.compile(r"## Evidence / Source Basis\s+(.*?)(?:\n## |\Z)", re.DOTALL)
SOURCE_LINK_RE = re.compile(r"\[\[Sources/(src-[0-9a-f]{10})\|")
CONTRADICTION_RE = re.compile(r"\bcontradiction\b|\bconflict(?:ing)?\b", re.IGNORECASE)

VALID_QUALITIES = {"supported", "provisional", "weak", "conflicting", "stale"}


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    data = yaml.safe_load(match.group(1)) or {}
    if not isinstance(data, dict):
        data = {}
    return data, match.group(2)


def load_source_strengths() -> dict[str, str]:
    strengths: dict[str, str] = {}
    for path in SOURCES_DIR.glob("src-*.md"):
        text = path.read_text(encoding="utf-8")
        frontmatter, _ = parse_frontmatter(text)
        value = frontmatter.get("evidence_strength")
        if isinstance(value, str):
            strengths[path.stem] = value.strip()
    return strengths


def extract_evidence_source_ids(text: str) -> list[str]:
    match = EVIDENCE_SECTION_RE.search(text)
    if not match:
        return []
    return sorted(set(SOURCE_LINK_RE.findall(match.group(1))))


def classify_claim_quality(text: str, strengths: dict[str, str]) -> str:
    evidence_source_ids = extract_evidence_source_ids(text)
    if not evidence_source_ids:
        return "weak"

    observed_strengths = [strengths.get(source_id) for source_id in evidence_source_ids]
    if any(strength in {"primary-doc", "strong"} for strength in observed_strengths):
        return "supported"

    if all(strength in {"stub", "image-only"} for strength in observed_strengths if strength is not None):
        return "weak"

    if CONTRADICTION_RE.search(text):
        return "conflicting"

    return "provisional"


def update_frontmatter(text: str, claim_quality: str) -> tuple[str, bool]:
    if not text.startswith("---\n"):
        return text, False

    match = FRONTMATTER_RE.match(text)
    if not match:
        return text, False

    frontmatter_text, body = match.group(1), match.group(2)
    lines = frontmatter_text.splitlines()
    new_line = f"claim_quality: {claim_quality}"

    for index, line in enumerate(lines):
        if line.startswith("claim_quality:"):
            if line.strip() == new_line:
                return text, False
            lines[index] = new_line
            return "---\n" + "\n".join(lines) + "\n---\n" + body, True

    insert_at = len(lines)
    found_tags = False
    for index, line in enumerate(lines):
        if line.startswith("tags:"):
            found_tags = True
            insert_at = index + 1
            while insert_at < len(lines) and (lines[insert_at].startswith("  ") or not lines[insert_at].strip()):
                insert_at += 1
            break
    if not found_tags:
        for index, line in enumerate(lines):
            if line.startswith("type:"):
                insert_at = index + 1
                break

    lines.insert(insert_at, new_line)
    return "---\n" + "\n".join(lines) + "\n---\n" + body, True


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill claim-quality metadata on concept pages.")
    parser.add_argument("--all", action="store_true", help="Process every concept page in notes/Concepts/.")
    parser.add_argument("--dry-run", action="store_true", help="Report planned changes without writing files.")
    args = parser.parse_args()

    if not args.all:
        raise SystemExit("Pass --all to backfill all concept pages.")

    strengths = load_source_strengths()
    changed = 0

    for path in sorted(CONCEPTS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        quality = classify_claim_quality(text, strengths)
        if quality not in VALID_QUALITIES:
            raise RuntimeError(f"Invalid claim quality inferred for {path}: {quality}")
        updated_text, did_change = update_frontmatter(text, quality)
        if did_change:
            changed += 1
            if not args.dry_run:
                path.write_text(updated_text, encoding="utf-8")
            print(f"{'Would update' if args.dry_run else 'Updated'} {path.relative_to(ROOT)} -> claim_quality: {quality}")

    if changed == 0:
        print("No concept claim-quality metadata needed backfilling")


if __name__ == "__main__":
    main()
