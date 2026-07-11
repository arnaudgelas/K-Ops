#!/usr/bin/env python3
"""
Feed failed probes back into compiled concept pages under ## Coverage Gaps.
Implements P2.3 of the evaluation plan.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Add scripts directory to path to allow importing utils
sys.path.append(str(Path(__file__).resolve().parent))
from kops.utils import ROOT, parse_frontmatter, dump_frontmatter

RESULTS_FILE = ROOT / "research" / "evals" / "evaluation-results.jsonl"


def load_results() -> list[dict]:
    results = []
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        results.append(json.loads(line))
                    except Exception as e:
                        print(f"Warning: failed to parse result line: {e}")
    return results


def parse_gaps_section(lines: list[str]) -> dict[str, list[str]]:
    items = {}
    current_probe_id = None
    current_lines = []

    for line in lines:
        m = re.match(r"^\s*-\s+\*\*\[Unresolved\]\*\*\s+\[(probe-[a-f0-9]+)\]", line)
        if m:
            if current_probe_id and current_lines:
                items[current_probe_id] = current_lines
            current_probe_id = m.group(1)
            current_lines = [line]
        elif current_probe_id:
            if not line.strip() or line.startswith("  ") or line.startswith("\t"):
                current_lines.append(line)
            else:
                items[current_probe_id] = current_lines
                current_probe_id = None
                current_lines = []

    if current_probe_id and current_lines:
        items[current_probe_id] = current_lines

    return items


def build_probe_lines(probe: dict) -> list[str]:
    lines = []
    lines.append(f"- **[Unresolved]** [{probe['id']}] Question: {probe['question']}")
    lines.append("  - Expected facts:")
    for fact in probe["expected_answer"]:
        lines.append(f"    - {fact}")
    return lines


def parse_sections(content: str) -> list[tuple[str, list[str]]]:
    lines = content.splitlines()
    sections = [("", [])]
    for line in lines:
        if line.startswith("## "):
            sections.append((line, []))
        else:
            sections[-1][1].append(line)
    return sections


def update_concept_file(
    concept: str, failed_probes: list[dict], passed_probe_ids: set[str]
) -> None:
    path = ROOT / "notes" / "Concepts" / f"{concept}.md"
    if not path.exists():
        print(f"Warning: concept file {path} not found.")
        return

    try:
        text = path.read_text(encoding="utf-8")
        frontmatter, content = parse_frontmatter(text)
    except Exception as e:
        print(f"Error reading concept {concept}: {e}")
        return

    sections = parse_sections(content)

    # 1. Find Coverage Gaps section index
    gaps_index = -1
    for idx, (heading, _) in enumerate(sections):
        if heading.strip() == "## Coverage Gaps":
            gaps_index = idx
            break

    # Load existing items in this section
    existing_items = {}
    if gaps_index != -1:
        existing_items = parse_gaps_section(sections[gaps_index][1])

    # Remove passed probes
    updated_items = {}
    for pid, item_lines in existing_items.items():
        if pid not in passed_probe_ids:
            updated_items[pid] = item_lines

    # Add/overwrite failed probes
    for probe in failed_probes:
        pid = probe["id"]
        updated_items[pid] = build_probe_lines(probe)

    # Reconstruct the Coverage Gaps lines
    gaps_lines = []
    if updated_items:
        # Add spacing before items
        gaps_lines.append("")
        for pid in sorted(updated_items.keys()):
            gaps_lines.extend(updated_items[pid])
            gaps_lines.append("")
        # Remove trailing empty string
        if gaps_lines and gaps_lines[-1] == "":
            gaps_lines.pop()

    # Update or insert Coverage Gaps section
    if updated_items:
        new_gaps_section = ("## Coverage Gaps", gaps_lines)
        if gaps_index != -1:
            sections[gaps_index] = new_gaps_section
        else:
            # Insert before Related Concepts, Open Questions, Backlinks, or Evidence / Source Basis
            insert_idx = -1
            for idx, (heading, _) in enumerate(sections):
                h = heading.strip()
                if h in [
                    "## Related Concepts",
                    "## Open Questions",
                    "## Backlinks",
                    "## Evidence / Source Basis",
                ]:
                    insert_idx = idx
                    break
            if insert_idx != -1:
                sections.insert(insert_idx, new_gaps_section)
            else:
                sections.append(new_gaps_section)
    else:
        # If no gaps left, remove the section entirely
        if gaps_index != -1:
            sections.pop(gaps_index)

    # Reassemble the content
    content_parts = []
    for heading, lines in sections:
        if heading:
            content_parts.append(heading)
        content_parts.extend(lines)

    new_content = "\n".join(content_parts)
    if not new_content.endswith("\n"):
        new_content += "\n"

    # Update frontmatter
    has_gaps = len(updated_items) > 0
    if has_gaps:
        frontmatter["revalidation_required"] = True
    else:
        frontmatter.pop("revalidation_required", None)

    # Write back to file
    try:
        new_text = dump_frontmatter(frontmatter) + new_content
        path.write_text(new_text, encoding="utf-8")
        status = "UPDATED (revalidation_required: true)" if has_gaps else "CLEARED"
        print(f"  Concept '{concept}': {status}")
    except Exception as e:
        print(f"Error writing concept {concept}: {e}")


def main() -> None:
    results = load_results()
    if not results:
        print("No evaluation results found in evaluation-results.jsonl.")
        sys.exit(0)

    # Group results by concept
    concept_failed = {}
    concept_passed_ids = {}

    for res in results:
        concept = res["concept"]
        probe_id = res["id"]

        if concept not in concept_failed:
            concept_failed[concept] = []
        if concept not in concept_passed_ids:
            concept_passed_ids[concept] = set()

        if res["pass_fail"]:
            concept_passed_ids[concept].add(probe_id)
        else:
            concept_failed[concept].append(res)

    # All concepts present in the results
    all_concepts = set(concept_failed.keys()) | set(concept_passed_ids.keys())

    print(f"Applying feedback loop to {len(all_concepts)} concept page(s)...")

    for concept in sorted(all_concepts):
        failed_probes = concept_failed.get(concept, [])
        passed_ids = concept_passed_ids.get(concept, set())
        update_concept_file(concept, failed_probes, passed_ids)


if __name__ == "__main__":
    main()
