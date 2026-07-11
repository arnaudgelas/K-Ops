from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from kops.utils import CONFIG, ROOT, ensure_dir, now_stamp, parse_frontmatter


def collect_notes() -> dict[str, list[dict]]:
    concept_rows: list[dict] = []
    index_rows: list[dict] = []
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

    for path in sorted(CONFIG.indexes_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)
        index_rows.append(
            {
                "kind": "index",
                "path": path.relative_to(ROOT).as_posix(),
                "title": frontmatter.get("title") or path.stem,
                "note_type": frontmatter.get("type") or "index",
                "tags": frontmatter.get("tags", []),
                "heading_count": sum(1 for line in body.splitlines() if line.startswith("## ")),
            }
        )

    for path in sorted(CONFIG.summaries_dir.rglob("src-*.md")):
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
                "sources_consulted": frontmatter.get("sources_consulted", []),
                "tags": frontmatter.get("tags", []),
                "vault_update_present": "## Vault Updates" in body,
            }
        )

    return {
        "concepts": concept_rows,
        "indexes": index_rows,
        "sources": source_rows,
        "answers": answer_rows,
    }


def write_json_index(output_path: Path, payload: dict) -> None:
    ensure_dir(output_path.parent)

    def json_serial(obj):
        import datetime

        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")

    output_path.write_text(
        json.dumps(payload, default=json_serial, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_csv_index(output_path: Path, payload: dict) -> None:
    ensure_dir(output_path.parent)
    rows = []
    for section in ("concepts", "indexes", "sources", "answers"):
        for item in payload[section]:
            row = {"kind": section[:-1], **item}
            rows.append(row)
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def export_vault_index(output: str | None = None, fmt: str = "json") -> Path:
    output_path = (
        Path(output).resolve()
        if output
        else (CONFIG.outputs_dir / f"{ROOT.name}-vault-index-{now_stamp()}.{fmt}").resolve()
    )
    payload = {
        "generated_at": now_stamp(),
        "project": CONFIG.project_name,
        "counts": {
            "concepts": len(list(CONFIG.concepts_dir.glob("*.md"))),
            "indexes": len(list(CONFIG.indexes_dir.glob("*.md"))),
            "sources": len(list(CONFIG.summaries_dir.rglob("src-*.md"))),
            "answers": len(list(CONFIG.answers_dir.glob("*.md"))),
        },
        **collect_notes(),
    }

    if fmt == "json":
        write_json_index(output_path, payload)
    else:
        write_csv_index(output_path, payload)
    print(output_path)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a structured manifest of the vault.")
    parser.add_argument(
        "--output", help="Output file path. Defaults to outputs/<repo>-vault-index-<timestamp>.json"
    )
    parser.add_argument("--format", choices=["json", "csv"], default="json")
    args = parser.parse_args()
    export_vault_index(output=args.output, fmt=args.format)


if __name__ == "__main__":
    main()
