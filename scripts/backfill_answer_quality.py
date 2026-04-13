from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent
ANSWERS_DIR = ROOT / "notes" / "Answers"

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
VAULT_UPDATES_RE = re.compile(r"## Vault Updates\s+(.*?)(?:\n## |\Z)", re.DOTALL)


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


def set_frontmatter_field(text: str, field: str, value: str) -> tuple[str, bool]:
    if not text.startswith("---\n"):
        return text, False
    match = FRONTMATTER_RE.match(text)
    if not match:
        return text, False

    frontmatter_lines = match.group(1).splitlines()
    new_line = f"{field}: {value}"
    for index, line in enumerate(frontmatter_lines):
        if line.startswith(f"{field}:"):
            if line.strip() == new_line:
                return text, False
            frontmatter_lines[index] = new_line
            return "---\n" + "\n".join(frontmatter_lines) + "\n---\n" + match.group(2), True

    insert_at = len(frontmatter_lines)
    for index, line in enumerate(frontmatter_lines):
        if line.startswith("type:"):
            insert_at = index + 1
            break
    frontmatter_lines.insert(insert_at, new_line)
    return "---\n" + "\n".join(frontmatter_lines) + "\n---\n" + match.group(2), True


def infer_answer_quality(body: str) -> str:
    match = VAULT_UPDATES_RE.search(body)
    updates = match.group(1).strip() if match else ""
    if not updates or updates in {"- None.", "None.", "- None"}:
        return "memo-only"
    return "durable"


def infer_answer_scope(answer_quality: str) -> str:
    return "shared" if answer_quality == "durable" else "private"


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill answer_quality on answer memos.")
    parser.add_argument("--all", action="store_true", help="Process every answer memo in notes/Answers/.")
    parser.add_argument("--dry-run", action="store_true", help="Report planned changes without writing files.")
    args = parser.parse_args()

    if not args.all:
        raise SystemExit("Pass --all to backfill all answer memos.")

    changed = 0
    for path in sorted(ANSWERS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)
        if frontmatter.get("type") != "answer":
            continue
        desired = infer_answer_quality(body)
        updated_text, did_change = set_frontmatter_field(text, "answer_quality", desired)
        scope = infer_answer_scope(desired)
        updated_text, scope_changed = set_frontmatter_field(updated_text, "scope", scope)
        did_change = did_change or scope_changed
        if did_change:
            changed += 1
            if not args.dry_run:
                path.write_text(updated_text, encoding="utf-8")
            print(
                f"{'Would update' if args.dry_run else 'Updated'} {path.relative_to(ROOT)} -> "
                f"answer_quality: {desired}, scope: {scope}"
            )

    if changed == 0:
        print("No answer quality metadata needed backfilling")


if __name__ == "__main__":
    main()
