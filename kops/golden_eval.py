"""Deterministic grader for the rich golden evaluation set (M1 task E1.2).

Given a produced answer (text + the retrieval/context it used) and a golden
question, score the answer along several dimensions:

  * required-element coverage,
  * forbidden-conclusion violation (catastrophic),
  * abstention appropriateness,
  * contradiction awareness,
  * uncertainty expression,
  * citation checks (fabricated / out-of-registry citations are catastrophic).

The grader reuses the existing fact-matching helpers rather than reinventing a
parallel scorer:

  * ``fact_present_in_text`` / ``keyword_match`` from ``kops.run_full_benchmark``
  * ``_fact_present`` / ``_normalize`` from ``kops.evaluate_compilation``

Per-question results plus a category/tier breakdown are emitted to a dated
``data/eval_runs/golden-<date>.jsonl`` artifact, matching the output convention
of ``kops.evaluate_compilation``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from kops.evaluate_compilation import _normalize
from kops.run_full_benchmark import fact_present_in_text, keyword_match
from kops.utils import ROOT

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_GOLDEN_SET = ROOT / "research" / "benchmarks" / "held-out" / "golden_set.yaml"
EVAL_RUNS_DIR = ROOT / "data" / "eval_runs"

CATEGORIES = [
    "direct-factual",
    "multi-source-synthesis",
    "contradiction-sensitive",
    "freshness-sensitive",
    "source-retraction-sensitive",
    "insufficient-evidence",
    "decision-grade",
    "adversarial-citation",
]
CONSEQUENCE_TIERS = ["exploratory", "recommendation", "decision", "autonomous"]
BEHAVIORS = {"answer", "abstain", "qualify"}

REQUIRED_FIELDS = (
    "id",
    "category",
    "question",
    "expected_answer_elements",
    "forbidden_conclusions",
    "relevant_claim_refs",
    "relevant_source_spans",
    "expected_contradictions",
    "required_uncertainty",
    "expected_behavior",
    "consequence_tier",
)

# Result codes (aligned with the failure-taxonomy style in evaluate_compilation).
RESULT_PASS = "pass"
RESULT_FAIL = "fail"
RESULT_CATASTROPHIC = "catastrophic"

FAILURE_FORBIDDEN_CONCLUSION = "forbidden-conclusion"
FAILURE_FABRICATED_CITATION = "fabricated-citation"
FAILURE_MISSING_ELEMENTS = "missing-required-elements"
FAILURE_BAD_ABSTENTION = "inappropriate-abstention"
FAILURE_MISSING_ABSTENTION = "missing-abstention"
FAILURE_MISSING_CONTRADICTION = "missing-contradiction"
FAILURE_MISSING_UNCERTAINTY = "missing-uncertainty"

CATASTROPHIC_FAILURES = {FAILURE_FORBIDDEN_CONCLUSION, FAILURE_FABRICATED_CITATION}

# Phrases that signal an answer is abstaining / declining to answer.
_ABSTENTION_MARKERS = (
    "insufficient evidence",
    "not answerable",
    "cannot answer",
    "can't answer",
    "cannot be answered",
    "no data",
    "does not contain",
    "not in the corpus",
    "not present in the corpus",
    "corpus does not",
    "unable to",
    "not documented",
    "not disclosed",
    "no such data",
    "not available",
    "no information",
    "not provided",
    "no evidence",
    "not stated",
    "no provider named",
    "no name given",
    "no cloud provider",
)

# Phrases that signal an answer is expressing uncertainty / hedging.
_UNCERTAINTY_MARKERS = (
    "dispute",
    "disputed",
    "unverified",
    "unresolved",
    "conflict",
    "contradic",
    "not independent",
    "caution",
    "however",
    "but ",
    "unclear",
    "not confirmed",
    "not proven",
    "cannot be confirmed",
    "retracted",
    "revoked",
    "self-benchmark",
    "vendor benchmark",
    "not independently",
    "weigh",
    "no firm date",
    "must be verified",
    "should be verified",
    "not equally",
    "time-sensitive",
)

_SRC_ID_RE = re.compile(r"src-[a-z0-9]{10}")


# ---------------------------------------------------------------------------
# Loading / validation
# ---------------------------------------------------------------------------


def load_golden_set(path: Path | str = DEFAULT_GOLDEN_SET) -> dict[str, Any]:
    """Load and parse a golden-set YAML file."""
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "questions" not in data:
        raise ValueError(f"{path}: not a golden-set mapping with a 'questions' key")
    return data


def validate_golden_set(data: dict[str, Any]) -> list[str]:
    """Return a list of schema errors (empty means valid)."""
    errors: list[str] = []
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        return ["'questions' must be a non-empty list"]

    seen_ids: set[str] = set()
    seen_categories: set[str] = set()
    for idx, q in enumerate(questions, start=1):
        if not isinstance(q, dict):
            errors.append(f"q{idx}: not a mapping")
            continue
        qid = q.get("id", f"q{idx}")
        for field in REQUIRED_FIELDS:
            if field not in q:
                errors.append(f"{qid}: missing required field '{field}'")
        if qid in seen_ids:
            errors.append(f"{qid}: duplicate id")
        seen_ids.add(qid)
        cat = q.get("category")
        if cat is not None:
            seen_categories.add(cat)
            if cat not in CATEGORIES:
                errors.append(f"{qid}: unknown category '{cat}'")
        if q.get("expected_behavior") not in BEHAVIORS:
            errors.append(f"{qid}: expected_behavior must be one of {sorted(BEHAVIORS)}")
        if q.get("consequence_tier") not in CONSEQUENCE_TIERS:
            errors.append(f"{qid}: consequence_tier must be one of {CONSEQUENCE_TIERS}")
        for key in ("expected_answer_elements", "relevant_source_spans"):
            if key in q and not isinstance(q[key], list):
                errors.append(f"{qid}: '{key}' must be a list")

    missing = set(CATEGORIES) - seen_categories
    if missing:
        errors.append(f"missing required categories: {sorted(missing)}")
    return errors


def load_registry_ids(corpus: Path | str) -> set[str]:
    """Load the set of valid source ids from a corpus registry."""
    registry = Path(corpus) / "data" / "registry.json"
    if not registry.exists():
        return set()
    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    if isinstance(data, list):
        return {r["id"] for r in data if isinstance(r, dict) and "id" in r}
    return set()


def verify_source_spans(data: dict[str, Any], corpus: Path | str) -> list[str]:
    """Verify that every source-span quote is verbatim-present in the corpus note.

    Whitespace is normalised so quotes wrapped across lines still match. Returns
    a list of mismatch errors (empty means all spans verified).
    """
    corpus = Path(corpus)
    src_dir = corpus / "notes" / "Sources"
    errors: list[str] = []
    for q in data.get("questions", []):
        for span in q.get("relevant_source_spans", []) or []:
            src = span.get("src")
            quote = span.get("quote", "")
            note = src_dir / f"{src}.md"
            if not note.exists():
                errors.append(f"{q.get('id')}: missing source note {src}")
                continue
            if _normalize(quote) not in _normalize(note.read_text(encoding="utf-8")):
                errors.append(f"{q.get('id')}: span not verbatim in {src}: {quote!r}")
    return errors


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------


def _detect_abstention(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in _ABSTENTION_MARKERS)


def _detect_uncertainty(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in _UNCERTAINTY_MARKERS)


def _extract_cited_ids(answer: dict[str, Any]) -> list[str]:
    cited = answer.get("cited_source_ids")
    if cited:
        return list(cited)
    return sorted(set(_SRC_ID_RE.findall(answer.get("text", ""))))


def grade_answer(
    question: dict[str, Any],
    answer: dict[str, Any] | str,
    registry_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Grade a produced answer against a single golden question.

    ``answer`` may be a raw string or a mapping with keys ``text`` (required),
    ``cited_source_ids`` (optional list), and ``abstained`` (optional bool). If
    ``abstained`` is omitted it is inferred from abstention markers in the text.
    """
    if isinstance(answer, str):
        answer = {"text": answer}
    text = answer.get("text", "")
    registry_ids = registry_ids or set()

    expected_behavior = question.get("expected_behavior", "answer")
    elements = question.get("expected_answer_elements", []) or []
    forbidden = question.get("forbidden_conclusions", []) or []
    contradictions = question.get("expected_contradictions", []) or []
    required_uncertainty = bool(question.get("required_uncertainty", False))

    # --- Dimension: forbidden conclusions (catastrophic) ---
    # A forbidden conclusion is a specific wrong claim; match it as a strict
    # normalized substring so loose keyword overlap cannot trigger a false
    # catastrophic (e.g. "first ... release" appearing in a correct answer).
    norm_text = _normalize(text)
    violated = [f for f in forbidden if _normalize(f) in norm_text]

    # --- Dimension: required-element coverage ---
    matched_elements = [e for e in elements if fact_present_in_text(e, text)]
    element_coverage = len(matched_elements) / len(elements) if elements else 1.0

    # --- Dimension: abstention appropriateness ---
    detected_abstention = bool(answer.get("abstained")) or _detect_abstention(text)
    if expected_behavior == "abstain":
        abstention_ok = detected_abstention
    else:
        abstention_ok = not detected_abstention

    # --- Dimension: contradiction awareness ---
    if contradictions:
        contra_hits = [c for c in contradictions if keyword_match(text, [c])[0]]
        contradiction_ok = len(contra_hits) >= max(1, len(contradictions))
    else:
        contra_hits = []
        contradiction_ok = True

    # --- Dimension: uncertainty expression ---
    uncertainty_ok = (not required_uncertainty) or _detect_uncertainty(text)

    # --- Dimension: citation checks ---
    cited_ids = _extract_cited_ids(answer)
    fabricated = [c for c in cited_ids if registry_ids and c not in registry_ids]

    # --- Classify ---
    failures: list[str] = []
    if violated:
        failures.append(FAILURE_FORBIDDEN_CONCLUSION)
    if fabricated:
        failures.append(FAILURE_FABRICATED_CITATION)
    if not abstention_ok:
        failures.append(
            FAILURE_MISSING_ABSTENTION if expected_behavior == "abstain" else FAILURE_BAD_ABSTENTION
        )
    if expected_behavior != "abstain" and elements and element_coverage < 0.5:
        failures.append(FAILURE_MISSING_ELEMENTS)
    if not contradiction_ok:
        failures.append(FAILURE_MISSING_CONTRADICTION)
    if not uncertainty_ok:
        failures.append(FAILURE_MISSING_UNCERTAINTY)

    if any(f in CATASTROPHIC_FAILURES for f in failures):
        result = RESULT_CATASTROPHIC
    elif failures:
        result = RESULT_FAIL
    else:
        result = RESULT_PASS

    return {
        "id": question.get("id"),
        "category": question.get("category"),
        "consequence_tier": question.get("consequence_tier"),
        "expected_behavior": expected_behavior,
        "result": result,
        "failures": failures,
        "dimensions": {
            "element_coverage": round(element_coverage, 3),
            "matched_elements": matched_elements,
            "forbidden_violated": violated,
            "abstention_expected": expected_behavior == "abstain",
            "abstention_detected": detected_abstention,
            "abstention_ok": abstention_ok,
            "contradiction_ok": contradiction_ok,
            "contradiction_hits": contra_hits,
            "uncertainty_required": required_uncertainty,
            "uncertainty_ok": uncertainty_ok,
            "cited_ids": cited_ids,
            "fabricated_citations": fabricated,
        },
    }


def grade_all(
    data: dict[str, Any],
    answers: dict[str, Any],
    registry_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Grade a whole golden set against a mapping of ``id -> answer``."""
    records = []
    for q in data.get("questions", []):
        ans = answers.get(q["id"])
        if ans is None:
            # No answer supplied: treat as an empty non-abstaining response.
            ans = {"text": ""}
        records.append(grade_answer(q, ans, registry_ids))
    return records


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a category/tier breakdown from per-question records."""
    total = len(records)
    passed = sum(1 for r in records if r["result"] == RESULT_PASS)
    catastrophic = sum(1 for r in records if r["result"] == RESULT_CATASTROPHIC)
    by_category: dict[str, Counter] = {}
    by_tier: dict[str, Counter] = {}
    failure_breakdown: Counter = Counter()
    for r in records:
        by_category.setdefault(r["category"], Counter())[r["result"]] += 1
        by_tier.setdefault(r["consequence_tier"], Counter())[r["result"]] += 1
        for f in r["failures"]:
            failure_breakdown[f] += 1
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "catastrophic": catastrophic,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "by_category": {k: dict(v) for k, v in by_category.items()},
        "by_tier": {k: dict(v) for k, v in by_tier.items()},
        "failure_breakdown": dict(failure_breakdown),
    }


def write_run(records: list[dict[str, Any]], summary: dict[str, Any]) -> Path:
    """Write per-question results + a summary line to a dated artifact."""
    EVAL_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().strftime("%Y%m%d")
    out_path = EVAL_RUNS_DIR / f"golden-{today}.jsonl"
    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    lines.append(json.dumps({"summary": summary}, ensure_ascii=False))
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_answers(path: Path) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        qid = obj.get("id")
        if qid:
            answers[qid] = obj
    return answers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Grade answers against the golden evaluation set.")
    parser.add_argument("--golden-set", type=Path, default=DEFAULT_GOLDEN_SET)
    parser.add_argument(
        "--answers",
        type=Path,
        help="JSONL of {id, text, cited_source_ids?, abstained?}; if omitted, only validates.",
    )
    args = parser.parse_args(argv)

    data = load_golden_set(args.golden_set)
    errors = validate_golden_set(data)
    if errors:
        print(f"Golden set INVALID ({len(errors)} error(s)):")
        for err in errors:
            print(f"  - {err}")
        return 1

    corpus = ROOT / data.get("corpus", "research/benchmarks/held-out/corpus")
    registry_ids = load_registry_ids(corpus)
    questions = data["questions"]

    if not args.answers:
        counts = Counter(q["category"] for q in questions)
        tiers = Counter(q["consequence_tier"] for q in questions)
        print(f"Golden set OK: {len(questions)} question(s), {len(counts)} categories.")
        print("By category:")
        for cat in CATEGORIES:
            print(f"  {cat}: {counts.get(cat, 0)}")
        print("By consequence tier:")
        for tier in CONSEQUENCE_TIERS:
            print(f"  {tier}: {tiers.get(tier, 0)}")
        return 0

    answers = _load_answers(args.answers)
    records = grade_all(data, answers, registry_ids)
    summary = summarize(records)
    out_path = write_run(records, summary)

    print(f"=== Golden eval — {len(records)} question(s) ===")
    print(f"Pass: {summary['passed']}/{summary['total']} ({summary['pass_rate']:.0%})")
    print(f"Catastrophic: {summary['catastrophic']}")
    print("By category:")
    for cat, res in sorted(summary["by_category"].items()):
        print(f"  {cat}: {res}")
    print("By consequence tier:")
    for tier, res in sorted(summary["by_tier"].items()):
        print(f"  {tier}: {res}")
    if summary["failure_breakdown"]:
        print("Failure breakdown:")
        for f, n in sorted(summary["failure_breakdown"].items(), key=lambda x: -x[1]):
            print(f"  {f}: {n}")
    print(f"Results written to: {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
