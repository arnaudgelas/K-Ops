#!/usr/bin/env python3
"""
Check that dev-probes and held-out benchmark questions do not overlap.
Exits 0 if no overlap (PASS), exits 1 if overlap detected (FAIL).
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DEV_PROBES = REPO_ROOT / "research/evals/dev-probes.jsonl"
HELD_OUT = REPO_ROOT / "research/benchmarks/held-out/questions.jsonl"


def load_jsonl(path: Path, skip_comment: bool = False):
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if skip_comment and "_comment" in obj:
                continue
            entries.append(obj)
    return entries


def main():
    dev = load_jsonl(DEV_PROBES)
    held = load_jsonl(HELD_OUT, skip_comment=True)

    dev_questions = {e["question"] for e in dev if "question" in e}
    held_questions = {e["question"] for e in held if "question" in e}

    dev_ids = {e["id"] for e in dev if "id" in e}
    held_ids = {e["id"] for e in held if "id" in e}

    overlapping_questions = dev_questions & held_questions
    overlapping_ids = dev_ids & held_ids

    failures = []
    if overlapping_questions:
        failures.append(f"overlapping question text: {sorted(overlapping_questions)}")
    if overlapping_ids:
        failures.append(f"overlapping question IDs: {sorted(overlapping_ids)}")

    if failures:
        print("FAIL: " + "; ".join(failures))
        sys.exit(1)
    else:
        print(f"PASS: no overlap ({len(dev)} dev-probes, {len(held)} held-out questions)")
        sys.exit(0)


if __name__ == "__main__":
    main()
