"""
evaluate_compilation.py — Compiled-vs-source evaluator for dev probes (T10).

Runs each approved dev probe in three deterministic retrieval modes:
  1. concept-only:        search notes/Concepts/<concept>.md for expected facts
  2. source-summary-only: search notes/Sources/**/<source_id>.md for expected facts
  3. claim+anchor:        search data/claims.json; validate citations & claim status

Failure taxonomy:
  - fabricated-citation:     source_id in claim not present in registry
  - wrong-source:            (reserved; not raised in deterministic mode)
  - contradicted-by-source:  (reserved; not raised in deterministic mode)
  - missing-required-fact:   one or more expected_answer facts absent from text
  - stale-evidence:          claim has status: superseded or revoked
  - pass:                    all expected facts found, all citations valid

Writes per-probe, per-mode records to data/eval_runs/<YYYYMMDD>.jsonl.
Prints a summary to stdout.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from kops.utils import CONFIG, ROOT  # noqa: E402

_PROBES_FILE = ROOT / "research" / "evals" / "dev-probes.jsonl"
_CLAIMS_PATH = ROOT / "data" / "claims.json"
_REGISTRY_PATH = ROOT / "data" / "registry.json"
_EVAL_RUNS_DIR = ROOT / "data" / "eval_runs"

# Failure taxonomy codes
FAILURE_FABRICATED_CITATION = "fabricated-citation"
FAILURE_MISSING_REQUIRED_FACT = "missing-required-fact"
FAILURE_STALE_EVIDENCE = "stale-evidence"
RESULT_PASS = "pass"

CATASTROPHIC_FAILURES = {
    FAILURE_FABRICATED_CITATION,
    "wrong-source",
    "contradicted-by-source",
}

STALE_STATUSES = {"superseded", "revoked"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Lowercase and collapse whitespace."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _fact_present(fact: str, text: str) -> bool:
    """
    Return True if fact appears in text.
    Strategy: substring match on normalised strings, then keyword match
    (all significant words with >3 chars must appear).
    """
    fact_n = _normalize(fact)
    text_n = _normalize(text)
    if fact_n in text_n:
        return True
    keywords = [w for w in re.split(r"[\W_]+", fact_n) if len(w) > 3]
    if not keywords:
        return False
    return all(kw in text_n for kw in keywords)


def _load_probes(approved_only: bool = True) -> list[dict]:
    if not _PROBES_FILE.exists():
        return []
    probes: list[dict] = []
    for line in _PROBES_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            p = json.loads(line)
        except json.JSONDecodeError:
            continue
        if approved_only and p.get("review_status") != "approved":
            continue
        probes.append(p)
    return probes


def _load_claims() -> list[dict]:
    if not _CLAIMS_PATH.exists():
        return []
    try:
        data = json.loads(_CLAIMS_PATH.read_text(encoding="utf-8"))
        return data.get("claims", []) if isinstance(data, dict) else list(data)
    except (json.JSONDecodeError, OSError):
        return []


def _load_registry_ids() -> set[str]:
    if not _REGISTRY_PATH.exists():
        return set()
    try:
        data = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {r["id"] for r in data if "id" in r}
        return set()
    except (json.JSONDecodeError, OSError):
        return set()


def _find_concept_page(concept: str) -> Path | None:
    """Find a concept page, trying a few normalisation variants."""
    for variant in (concept, concept.replace("-", "_"), concept.replace("_", "-")):
        p = CONFIG.concepts_dir / f"{variant}.md"
        if p.exists():
            return p
    return None


def _find_source_note(source_id: str) -> Path | None:
    """Find source summary note by source_id under summaries_dir."""
    for p in CONFIG.summaries_dir.rglob(f"{source_id}.md"):
        return p
    return None


def _concept_slug(raw: str) -> str:
    """Normalise concept slug for comparison (replace - and _ to a canonical form)."""
    return raw.replace("-", "_").lower()


# ---------------------------------------------------------------------------
# Mode 1: concept-only
# ---------------------------------------------------------------------------


def _eval_concept_only(probe: dict) -> dict:
    concept = probe.get("concept", "")
    expected = probe.get("expected_answer", [])
    probe_id = probe["id"]

    concept_path = _find_concept_page(concept)
    if not concept_path:
        return {
            "probe_id": probe_id,
            "mode": "concept-only",
            "result": FAILURE_MISSING_REQUIRED_FACT,
            "missing_facts": list(expected),
            "notes": f"Concept page not found for '{concept}'",
        }

    text = concept_path.read_text(encoding="utf-8")
    missing = [f for f in expected if not _fact_present(f, text)]

    if missing:
        return {
            "probe_id": probe_id,
            "mode": "concept-only",
            "result": FAILURE_MISSING_REQUIRED_FACT,
            "missing_facts": missing,
            "notes": f"{concept_path.name}: {len(missing)}/{len(expected)} expected facts missing",
        }
    return {
        "probe_id": probe_id,
        "mode": "concept-only",
        "result": RESULT_PASS,
        "missing_facts": [],
        "notes": f"All {len(expected)} facts found in {concept_path.name}",
    }


# ---------------------------------------------------------------------------
# Mode 2: source-summary-only
# ---------------------------------------------------------------------------


def _eval_source_summary_only(probe: dict) -> dict:
    source_id = probe.get("source_id", "")
    expected = probe.get("expected_answer", [])
    probe_id = probe["id"]

    source_path = _find_source_note(source_id)
    if not source_path:
        return {
            "probe_id": probe_id,
            "mode": "source-summary-only",
            "result": FAILURE_MISSING_REQUIRED_FACT,
            "missing_facts": list(expected),
            "notes": f"Source note not found for '{source_id}'",
        }

    text = source_path.read_text(encoding="utf-8")
    missing = [f for f in expected if not _fact_present(f, text)]

    if missing:
        return {
            "probe_id": probe_id,
            "mode": "source-summary-only",
            "result": FAILURE_MISSING_REQUIRED_FACT,
            "missing_facts": missing,
            "notes": f"{source_path.name}: {len(missing)}/{len(expected)} expected facts missing",
        }
    return {
        "probe_id": probe_id,
        "mode": "source-summary-only",
        "result": RESULT_PASS,
        "missing_facts": [],
        "notes": f"All {len(expected)} facts found in {source_path.name}",
    }


# ---------------------------------------------------------------------------
# Mode 3: claim+anchor
# ---------------------------------------------------------------------------


def _eval_claim_anchor(probe: dict, claims: list[dict], registry_ids: set[str]) -> dict:
    concept = probe.get("concept", "")
    source_id = probe.get("source_id", "")
    expected = probe.get("expected_answer", [])
    probe_id = probe["id"]

    concept_slug = _concept_slug(concept)
    concept_claims = [
        c for c in claims if _concept_slug(str(c.get("concept") or "")) == concept_slug
    ]

    if not concept_claims:
        return {
            "probe_id": probe_id,
            "mode": "claim+anchor",
            "result": FAILURE_MISSING_REQUIRED_FACT,
            "missing_facts": list(expected),
            "notes": f"No claims found for concept '{concept}'",
        }

    # Check for stale evidence first
    for claim in concept_claims:
        status = str(claim.get("status") or "")
        if status in STALE_STATUSES:
            return {
                "probe_id": probe_id,
                "mode": "claim+anchor",
                "result": FAILURE_STALE_EVIDENCE,
                "missing_facts": [],
                "notes": f"Claim '{claim.get('claim_id') or claim.get('id')}' has status='{status}'",
            }

    # Check source_id validity for claims that reference the probe's source
    if registry_ids:
        for claim in concept_claims:
            sids = claim.get("source_ids") or []
            if source_id in sids:
                for sid in sids:
                    if sid not in registry_ids:
                        return {
                            "probe_id": probe_id,
                            "mode": "claim+anchor",
                            "result": FAILURE_FABRICATED_CITATION,
                            "missing_facts": [],
                            "notes": f"Claim references source '{sid}' not in registry",
                        }

    # Check expected facts coverage across all claims for this concept
    combined_text = " ".join(
        str(c.get("claim_text") or c.get("text") or "") for c in concept_claims
    )
    missing = [f for f in expected if not _fact_present(f, combined_text)]

    if missing:
        return {
            "probe_id": probe_id,
            "mode": "claim+anchor",
            "result": FAILURE_MISSING_REQUIRED_FACT,
            "missing_facts": missing,
            "notes": f"{len(missing)}/{len(expected)} facts not covered by {len(concept_claims)} claims",
        }

    return {
        "probe_id": probe_id,
        "mode": "claim+anchor",
        "result": RESULT_PASS,
        "missing_facts": [],
        "notes": f"All {len(expected)} facts covered by {len(concept_claims)} claims",
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(approved_only: bool = True) -> None:
    probes = _load_probes(approved_only=approved_only)
    if not probes:
        if approved_only:
            print("no approved probes — nothing to evaluate")
        else:
            print("no probes found — nothing to evaluate")
        sys.exit(0)

    claims = _load_claims()
    registry_ids = _load_registry_ids()

    _EVAL_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().strftime("%Y%m%d")
    out_path = _EVAL_RUNS_DIR / f"{today}.jsonl"

    records: list[dict] = []
    for probe in probes:
        records.append(_eval_concept_only(probe))
        records.append(_eval_source_summary_only(probe))
        records.append(_eval_claim_anchor(probe, claims, registry_ids))

    out_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )

    # --- Summary ---
    total_probes = len(probes)
    modes = ["concept-only", "source-summary-only", "claim+anchor"]
    pass_counts: dict[str, int] = {}
    failure_breakdown: dict[str, int] = {}

    for mode in modes:
        mode_records = [r for r in records if r["mode"] == mode]
        pass_counts[mode] = sum(1 for r in mode_records if r["result"] == RESULT_PASS)

    for r in records:
        if r["result"] != RESULT_PASS:
            failure_breakdown[r["result"]] = failure_breakdown.get(r["result"], 0) + 1

    print(f"\n=== Compilation Evaluator — {today} ===")
    print(f"Total probes evaluated: {total_probes}")
    print("\nPass counts by mode:")
    for mode in modes:
        count = pass_counts[mode]
        rate = count / total_probes if total_probes else 0.0
        print(f"  {mode}: {count}/{total_probes} ({rate:.0%})")
    print("\nFailure breakdown (across all modes):")
    if failure_breakdown:
        for failure, count in sorted(failure_breakdown.items(), key=lambda x: -x[1]):
            print(f"  {failure}: {count}")
    else:
        print("  (none)")
    print(f"\nResults written to: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run compiled-vs-source evaluation on dev probes.")
    parser.add_argument(
        "--all",
        dest="all_probes",
        action="store_true",
        help="Include unreviewed probes (baseline run). Default: approved-only.",
    )
    args = parser.parse_args()
    run(approved_only=not args.all_probes)
