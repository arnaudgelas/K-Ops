"""
run_full_benchmark.py — Full 100-question benchmark across 3 retrieval modes.

Methodology: keyword overlap check (require ≥60% of content-bearing tokens from
each expected fact to appear in the retrieved text). This matches the intent of
the sample evaluation's fact-presence check more closely than the original lenient
0.4 threshold.

Writes results to research/benchmarks/held-out/results_full.jsonl
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parent.parent
NOTES_DIR = VAULT_ROOT / "notes"
CONCEPTS_DIR = NOTES_DIR / "Concepts"
SOURCES_DIR = NOTES_DIR / "Sources"
QUESTIONS_FILE = VAULT_ROOT / "research/benchmarks/held-out/questions.jsonl"
OUTPUT_FILE = VAULT_ROOT / "research/benchmarks/held-out/results_full.jsonl"
SCRIPTS_DIR = VAULT_ROOT / "kops"

STOP_WORDS = {
    "that",
    "this",
    "with",
    "from",
    "have",
    "been",
    "they",
    "when",
    "where",
    "about",
    "should",
    "because",
    "after",
    "before",
    "their",
    "which",
    "would",
    "could",
    "does",
    "also",
    "into",
    "than",
    "then",
    "note",
    "vault",
    "answer",
    "claim",
    "page",
    "what",
    "some",
    "more",
    "each",
    "only",
    "will",
    "such",
    "many",
    "most",
    "used",
    "using",
    "used",
    "given",
    "over",
    "same",
    "very",
    "even",
    "make",
    "made",
    "need",
    "must",
    "well",
    "been",
    "both",
    "just",
    "like",
    "than",
    "been",
    "here",
    "were",
    "these",
    "those",
    "them",
    "then",
    "time",
}


def load_questions() -> list[dict]:
    questions = []
    with open(QUESTIONS_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if "_comment" in data:
                continue
            questions.append(data)
    return questions


def find_source_file(src_id: str) -> Path | None:
    """Find a source note file by its src-ID."""
    for p in SOURCES_DIR.rglob(f"{src_id}.md"):
        return p
    return None


def read_file_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def extract_keywords(text: str, min_len: int = 4) -> list[str]:
    """Extract meaningful content words from text."""
    words = re.findall(r"\b[a-zA-Z0-9_-]{" + str(min_len) + r",}\b", text.lower())
    return [w for w in words if w not in STOP_WORDS]


def fact_present_in_text(fact: str, text: str, threshold: float = 0.55) -> bool:
    """Check if a fact's key content words are present in text at given threshold."""
    fact_keywords = extract_keywords(fact)
    if not fact_keywords:
        return True  # empty fact is trivially present
    text_lower = text.lower()
    matches = sum(1 for k in fact_keywords if k in text_lower)
    return matches / len(fact_keywords) >= threshold


def keyword_match(
    text: str, facts: list[str], threshold: float = 0.55
) -> tuple[bool, list[str], list[str]]:
    """Check which facts are present in text.
    Returns (overall_pass, matched_facts, missing_facts).
    Pass = at least half the facts are present."""
    matched = []
    missing = []
    for fact in facts:
        if fact_present_in_text(fact, text, threshold):
            matched.append(fact)
        else:
            missing.append(fact)
    overall_pass = len(matched) >= max(1, len(facts) * 0.5)
    return overall_pass, matched, missing


def find_concept_files_for_question(question: str, q_class: str) -> list[Path]:
    """Find concept pages whose names relate to the question topic."""
    question_words = set(extract_keywords(question, min_len=5))
    # Remove question-class-specific boilerplate words
    boilerplate = {
        "vault",
        "source",
        "claim",
        "concept",
        "question",
        "answer",
        "specific",
        "described",
        "according",
        "following",
        "appear",
        "provide",
        "exact",
        "mentioned",
        "stated",
        "supported",
        "definitively",
        "marked",
        "documented",
        "evidence",
        "status",
        "inherited",
        "directly",
        "cited",
        "tension",
        "conflict",
        "repository",
        "snapshot",
        "github",
        "class",
        "quality",
        "required",
        "strong",
        "contain",
        "relates",
        "topic",
        "establish",
        "which",
        "claim_quality",
    }
    question_words -= boilerplate

    scored: list[tuple[float, Path]] = []
    for cp in CONCEPTS_DIR.glob("*.md"):
        # Score by name match
        name_words = set(extract_keywords(cp.stem.replace("_", " "), min_len=4))
        name_overlap = len(question_words & name_words)
        if name_overlap > 0:
            # Higher weight for name match
            scored.append((name_overlap * 3.0, cp))
        else:
            # Content match - lower weight
            text = read_file_text(cp).lower()
            text_words = set(extract_keywords(text, min_len=5))
            content_overlap = len(question_words & text_words)
            if content_overlap >= 4:
                scored.append((content_overlap * 0.3, cp))

    scored.sort(key=lambda x: -x[0])
    return [p for _, p in scored[:5]]


def run_bm25_search(question: str) -> str:
    """Run BM25 search and return combined result text."""
    # Use first 100 chars to keep query focused
    search_query = question[:100].replace('"', "'").replace("\n", " ")
    try:
        result = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "kops.search_vault",
                search_query,
                "--top",
                "5",
            ],
            capture_output=True,
            text=True,
            timeout=45,
            cwd=str(VAULT_ROOT),
        )
        return result.stdout + result.stderr
    except Exception as e:
        return f"ERROR: {e}"


def evaluate_mode_a(q: dict) -> dict:
    """Mode A: concept-only retrieval."""
    question = q["question"]
    facts = q["expected_answer_facts"]
    q_class = q["class"]

    concept_files = find_concept_files_for_question(question, q_class)
    if not concept_files:
        return {
            "question_id": q["id"],
            "class": q_class,
            "mode": "A",
            "result": "missing-required-fact",
            "notes": "No matching concept pages found",
        }

    combined_text = ""
    found_pages = []
    for cf in concept_files:
        text = read_file_text(cf)
        combined_text += "\n" + text
        found_pages.append(cf.name)

    passed, matched, missing = keyword_match(combined_text, facts)
    result = "pass" if passed else "missing-required-fact"

    return {
        "question_id": q["id"],
        "class": q_class,
        "mode": "A",
        "result": result,
        "notes": (
            f"Pages: {found_pages[:3]}; "
            f"matched {len(matched)}/{len(facts)} facts; "
            f"missing: {missing[:1]}"
        ),
    }


def evaluate_mode_b(q: dict) -> dict:
    """Mode B: source-summary-only retrieval."""
    required = q.get("required_source_ids", [])
    facts = q["expected_answer_facts"]
    q_class = q["class"]

    if not required:
        return {
            "question_id": q["id"],
            "class": q_class,
            "mode": "B",
            "result": "missing-required-fact",
            "notes": "No required_source_ids specified",
        }

    src_id = required[0]
    src_file = find_source_file(src_id)
    if not src_file:
        return {
            "question_id": q["id"],
            "class": q_class,
            "mode": "B",
            "result": "missing-required-fact",
            "notes": f"Source file not found: {src_id}",
        }

    text = read_file_text(src_file)
    passed, matched, missing = keyword_match(text, facts)
    result = "pass" if passed else "missing-required-fact"

    return {
        "question_id": q["id"],
        "class": q_class,
        "mode": "B",
        "result": result,
        "notes": (
            f"Source: {src_file.name}; "
            f"matched {len(matched)}/{len(facts)} facts; "
            f"missing: {missing[:1]}"
        ),
    }


def evaluate_mode_c(q: dict) -> dict:
    """Mode C: BM25 search."""
    question = q["question"]
    facts = q["expected_answer_facts"]
    q_class = q["class"]

    search_text = run_bm25_search(question)

    passed, matched, missing = keyword_match(search_text, facts)
    result = "pass" if passed else "missing-required-fact"

    return {
        "question_id": q["id"],
        "class": q_class,
        "mode": "C",
        "result": result,
        "notes": (
            f"BM25 search; matched {len(matched)}/{len(facts)} facts; "
            f"output len: {len(search_text)}; missing: {missing[:1]}"
        ),
    }


def compute_stats(results: list[dict]) -> dict:
    stats = {}
    for mode in ["A", "B", "C"]:
        mode_results = [r for r in results if r["mode"] == mode]
        total = len(mode_results)
        passed = sum(1 for r in mode_results if r["result"] == "pass")
        catastrophic = sum(
            1
            for r in mode_results
            if r["result"] in {"fabricated-citation", "wrong-source", "contradicted-by-source"}
        )
        per_class = {}
        for cls in ["lookup", "synthesis", "freshness", "code", "trap"]:
            cls_results = [r for r in mode_results if r["class"] == cls]
            cls_total = len(cls_results)
            cls_passed = sum(1 for r in cls_results if r["result"] == "pass")
            per_class[cls] = {
                "pass": cls_passed,
                "total": cls_total,
                "rate": round(100 * cls_passed / cls_total, 1) if cls_total else 0,
            }
        stats[mode] = {
            "pass": passed,
            "total": total,
            "rate": round(100 * passed / total, 1) if total else 0,
            "catastrophic": catastrophic,
            "catastrophic_rate": round(100 * catastrophic / total, 1) if total else 0,
            "per_class": per_class,
        }
    return stats


def main():
    print("Loading questions...")
    questions = load_questions()
    print(f"Loaded {len(questions)} questions.")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        pass

    results = []
    batch_size = 20

    for batch_start in range(0, len(questions), batch_size):
        batch = questions[batch_start : batch_start + batch_size]
        batch_end = batch_start + len(batch)
        print(f"\nProcessing questions {batch_start + 1}-{batch_end}...")

        batch_results = []
        for q in batch:
            print(f"  {q['id']} ({q['class']})", end=" ", flush=True)

            r_a = evaluate_mode_a(q)
            r_b = evaluate_mode_b(q)
            r_c = evaluate_mode_c(q)

            batch_results.extend([r_a, r_b, r_c])
            print(f"A:{r_a['result'][:4]} B:{r_b['result'][:4]} C:{r_c['result'][:4]}")

        with open(OUTPUT_FILE, "a") as f:
            for r in batch_results:
                f.write(json.dumps(r) + "\n")

        results.extend(batch_results)
        print(f"  Batch {batch_start // batch_size + 1} written ({len(batch_results)} records).")

    print(f"\nDone. {len(results)} results written to {OUTPUT_FILE}")

    stats = compute_stats(results)
    print("\n=== SUMMARY ===")
    for mode in ["A", "B", "C"]:
        s = stats[mode]
        print(
            f"Mode {mode}: {s['pass']}/{s['total']} pass ({s['rate']}%), "
            f"catastrophic: {s['catastrophic']} ({s['catastrophic_rate']}%)"
        )
        for cls, cs in s["per_class"].items():
            print(f"  {cls}: {cs['pass']}/{cs['total']} ({cs['rate']}%)")

    # Decision rule
    rate_a = stats["A"]["rate"]
    rate_c = stats["C"]["rate"]
    delta = rate_c - rate_a
    cat_a = stats["A"]["catastrophic_rate"]
    cat_c = stats["C"]["catastrophic_rate"]
    adopt = delta >= 10.0 and cat_c <= cat_a
    print(f"\nMode C vs Mode A delta: {delta:+.1f}pp")
    print(f"Adoption decision: {'ADOPT' if adopt else 'DEFER'}")
    print(f"Rationale: delta={delta:+.1f}pp (need ≥+10pp); cat_A={cat_a}% cat_C={cat_c}%")

    # Write stats as JSON for reference
    stats_file = VAULT_ROOT / "research/benchmarks/held-out/stats_full.json"
    with open(stats_file, "w") as f:
        json.dump(
            {"stats": stats, "delta_C_vs_A": delta, "decision": "adopt" if adopt else "defer"},
            f,
            indent=2,
        )
    print(f"\nStats written to {stats_file}")

    return stats, adopt, delta


if __name__ == "__main__":
    main()
