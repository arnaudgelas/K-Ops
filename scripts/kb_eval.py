from __future__ import annotations

from utils import ROOT


def run_eval_setup() -> None:
    """Create the golden Q&A evaluation scaffold if it does not exist."""
    import yaml

    eval_path = ROOT / "tests" / "qa_golden.yaml"
    if eval_path.exists():
        print(f"Eval scaffold already exists: {eval_path.relative_to(ROOT)}")
        return
    scaffold = {
        "version": "1.0",
        "description": (
            "Golden Q&A evaluation set for K-Ops vault quality assurance. "
            "Add questions whose answers should be consistently derivable from the vault."
        ),
        "questions": [
            {
                "id": "q001",
                "question": "What is the core purpose of K-Ops?",
                "expected_themes": ["knowledge base", "agent", "Obsidian", "ingest"],
                "expected_sources": [],
                "expected_concepts": [],
                "notes": "Should be answerable from OPERATING_RULES.md or notes/Home.md",
            }
        ],
    }
    eval_path.write_text(
        yaml.safe_dump(scaffold, sort_keys=False, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    print(f"Eval scaffold created: {eval_path.relative_to(ROOT)}")
    print("Add questions to tests/qa_golden.yaml, then run 'eval-check' to validate.")


def run_eval_check() -> None:
    """Validate the golden Q&A file structure and print a summary."""
    import yaml

    eval_path = ROOT / "tests" / "qa_golden.yaml"
    if not eval_path.exists():
        print("No eval file found. Run 'eval-setup' to create it.")
        raise SystemExit(1)
    try:
        data = yaml.safe_load(eval_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(f"YAML parse error in {eval_path.relative_to(ROOT)}: {exc}")
        raise SystemExit(1)
    if not isinstance(data, dict) or "questions" not in data:
        print("Invalid eval file: missing 'questions' key.")
        raise SystemExit(1)
    questions = data["questions"]
    if not isinstance(questions, list):
        print("Invalid eval file: 'questions' must be a list.")
        raise SystemExit(1)
    errors: list[str] = []
    for idx, q in enumerate(questions, start=1):
        if not isinstance(q, dict):
            errors.append(f"  q{idx}: not a mapping")
            continue
        for field in ("id", "question"):
            if not q.get(field):
                errors.append(f"  {q.get('id', f'q{idx}')}: missing required field '{field}'")
    if errors:
        print(f"Eval check FAILED ({len(errors)} error(s)):")
        for err in errors:
            print(err)
        raise SystemExit(1)
    print(
        f"Eval check OK: {len(questions)} question(s) in "
        f"{eval_path.relative_to(ROOT)} (version {data.get('version', '?')})"
    )
