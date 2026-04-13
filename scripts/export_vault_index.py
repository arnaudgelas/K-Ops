from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import yaml

from utils import CONFIG, ROOT, ensure_dir, now_stamp


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        return {}, text
    data = yaml.safe_load(parts[0][4:]) or {}
    if not isinstance(data, dict):
        data = {}
    return data, parts[1]


def collect_notes() -> dict[str, list[dict]]:
    concept_rows: list[dict] = []
    source_rows: list[dict] = []
    answer_rows: list[dict] = []

    for path in sorted(CONFIG.concepts_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)
        concept_rows.append(
            {
                "kind": "concept",
                "path": path.relative_to(ROOT).as_posix(),
                "title": frontmatter.get("title") or path.stem,
                "claim_quality": frontmatter.get("claim_quality"),
                "tags": frontmatter.get("tags", []),
                "heading_count": sum(1 for line in body.splitlines() if line.startswith("## ")),
            }
        )

    for path in sorted(CONFIG.summaries_dir.glob("src-*.md")):
        text = path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)
        source_rows.append(
            {
                "kind": "source-summary",
                "path": path.relative_to(ROOT).as_posix(),
                "title": frontmatter.get("title") or path.stem,
                "source_id": frontmatter.get("source_id") or path.stem,
                "evidence_strength": frontmatter.get("evidence_strength"),
                "tags": frontmatter.get("tags", []),
                "summary_length": len(body.split()),
            }
        )

    for path in sorted(CONFIG.answers_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)
        answer_rows.append(
            {
                "kind": "answer",
                "path": path.relative_to(ROOT).as_posix(),
                "title": frontmatter.get("title") or path.stem,
                "asked_at": frontmatter.get("asked_at"),
                "answer_quality": frontmatter.get("answer_quality"),
                "tags": frontmatter.get("tags", []),
                "vault_update_present": "## Vault Updates" in body,
            }
        )

    return {"concepts": concept_rows, "sources": source_rows, "answers": answer_rows}


def write_json_index(output_path: Path, payload: dict) -> None:
    ensure_dir(output_path.parent)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_csv_index(output_path: Path, payload: dict) -> None:
    ensure_dir(output_path.parent)
    rows = []
    for section in ("concepts", "sources", "answers"):
        for item in payload[section]:
            row = {"kind": section[:-1], **item}
            rows.append(row)
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a structured manifest of the vault.")
    parser.add_argument("--output", help="Output file path. Defaults to outputs/<repo>-vault-index-<timestamp>.json")
    parser.add_argument("--format", choices=["json", "csv"], default="json")
    args = parser.parse_args()

    output = (
        Path(args.output).resolve()
        if args.output
        else (CONFIG.outputs_dir / f"{ROOT.name}-vault-index-{now_stamp()}.{args.format}").resolve()
    )
    payload = {
        "generated_at": now_stamp(),
        "project": CONFIG.project_name,
        "counts": {
            "concepts": len(list(CONFIG.concepts_dir.glob("*.md"))),
            "sources": len(list(CONFIG.summaries_dir.glob("src-*.md"))),
            "answers": len(list(CONFIG.answers_dir.glob("*.md"))),
        },
        **collect_notes(),
    }

    if args.format == "json":
        write_json_index(output, payload)
    else:
        write_csv_index(output, payload)
    print(output)


if __name__ == "__main__":
    main()
