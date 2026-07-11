from __future__ import annotations

import argparse

from kops.utils import parse_frontmatter, dump_frontmatter


from kops.kb_paths import ROOT  # noqa: E402

ANSWERS_DIR = ROOT / "notes" / "Answers"


def infer_answer_quality(body: str) -> str:
    # Use simple check to see if there are any updates listed under Vault Updates
    import re

    vault_updates_re = re.compile(r"## Vault Updates\s+(.*?)(?:\n## |\Z)", re.DOTALL)
    match = vault_updates_re.search(body)
    updates = match.group(1).strip() if match else ""
    if not updates or updates in {"- None.", "None.", "- None"}:
        return "memo-only"
    return "durable"


def infer_answer_scope(answer_quality: str) -> str:
    return "shared" if answer_quality == "durable" else "private"


def backfill_answer_quality(all_pages: bool = False, dry_run: bool = False) -> None:
    if not all_pages:
        raise SystemExit("Pass --all to backfill all answer memos.")

    changed = 0
    for path in sorted(ANSWERS_DIR.glob("*.md")):
        if path.name == ".gitkeep":
            continue
        text = path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)
        if frontmatter.get("type") != "answer":
            continue

        file_did_change = False

        # 1. Answer quality
        desired_quality = infer_answer_quality(body)
        if frontmatter.get("answer_quality") != desired_quality:
            frontmatter["answer_quality"] = desired_quality
            file_did_change = True

        # 2. Scope
        desired_scope = infer_answer_scope(desired_quality)
        if frontmatter.get("scope") != desired_scope:
            frontmatter["scope"] = desired_scope
            file_did_change = True

        # 3. Query class
        if "query_class" not in frontmatter:
            frontmatter["query_class"] = "synthesis"
            file_did_change = True

        # 4. Retrieval path
        if "retrieval_path" not in frontmatter:
            frontmatter["retrieval_path"] = []
            file_did_change = True

        # 5. Fetch required
        if "fetch_required" not in frontmatter:
            frontmatter["fetch_required"] = False
            file_did_change = True

        # 6. Tags check
        tags = frontmatter.get("tags")
        if not tags:
            frontmatter["tags"] = ["kb/answer"]
            file_did_change = True
        elif isinstance(tags, list):
            if "kb/answer" not in tags:
                frontmatter["tags"] = tags + ["kb/answer"]
                file_did_change = True
        else:
            frontmatter["tags"] = [tags] if "kb/answer" == tags else [tags, "kb/answer"]
            file_did_change = True

        if file_did_change:
            changed += 1
            if not dry_run:
                updated_text = dump_frontmatter(frontmatter) + body
                path.write_text(updated_text, encoding="utf-8")
            print(
                f"{'Would update' if dry_run else 'Updated'} {path.relative_to(ROOT)} -> "
                f"quality: {frontmatter['answer_quality']}, scope: {frontmatter['scope']}, query_class: {frontmatter['query_class']}"
            )

    if changed == 0:
        print("No answer quality or metadata needed backfilling")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill answer_quality and required metadata on answer memos."
    )
    parser.add_argument(
        "--all", action="store_true", help="Process every answer memo in notes/Answers/."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report planned changes without writing files."
    )
    args = parser.parse_args()
    backfill_answer_quality(all_pages=args.all, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
