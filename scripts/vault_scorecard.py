"""Vault scorecard — compute knowledge-quality metrics across the whole vault.

Reads the vault in read-only mode; builds a structured health report and writes
it to ``data/scorecard.json``.  Run via ``kb.py scorecard``.

The scorecard covers five domains:
  - concepts   (claim quality, unsupported pages, revalidation backlog)
  - sources    (evidence-strength distribution, stub/primary fractions)
  - claims     (coverage, inline citation rate from ``data/claims.json``)
  - answers    (durable vs. memo-only, provenance coverage)
  - research   (active topics, phase distribution)

Health signals are emitted when any metric crosses a threshold.  They are
deliberately distinct from lint findings: lint enforces hard structure rules,
scorecards surface soft quality concerns.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections import Counter
from pathlib import Path

from utils import CONFIG, ROOT, ensure_dir, parse_frontmatter

SCORECARD_PATH = ROOT / "data" / "scorecard.json"

_CLAIMS_PATH = ROOT / "data" / "claims.json"
_CONTRADICTIONS_PATH = ROOT / "data" / "contradictions.json"
_RESEARCH_DIR = CONFIG.research_dir

_INLINE_SOURCE_RE = re.compile(r"\(\[\[Sources/src-[0-9a-f]{10}")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*\S.*?)\s*$")
_CLAIMS_SECTION_RE = re.compile(r"## Key Claims\s+(.*?)(?:\n## |\Z)", re.DOTALL)
_EVIDENCE_SOURCE_RE = re.compile(r"\[\[Sources/(src-[0-9a-f]{10})\|")
_EVIDENCE_SECTION_RE = re.compile(r"## Evidence / Source Basis\s+(.*?)(?:\n## |\Z)", re.DOTALL)


def _claims_inline_citation_count(body: str) -> tuple[int, int]:
    """Return ``(bullets_with_inline_citation, total_bullets)`` from Key Claims."""
    m = _CLAIMS_SECTION_RE.search(body)
    if not m:
        return 0, 0
    total = 0
    with_citation = 0
    for line in m.group(1).splitlines():
        if _BULLET_RE.match(line):
            total += 1
            if _INLINE_SOURCE_RE.search(line):
                with_citation += 1
    return with_citation, total


def _score_concepts() -> dict:
    concepts = list(CONFIG.concepts_dir.glob("*.md"))
    quality_counter: Counter = Counter()
    unsupported = 0
    revalidation_required = 0
    conflicting_no_oq = 0
    bullets_total = 0
    bullets_with_inline = 0

    for path in concepts:
        text = path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)
        cq = str(frontmatter.get("claim_quality") or "unknown")
        quality_counter[cq] += 1
        if frontmatter.get("revalidation_required"):
            revalidation_required += 1
        ev_match = _EVIDENCE_SECTION_RE.search(body)
        if not ev_match or not _EVIDENCE_SOURCE_RE.search(ev_match.group(1)):
            unsupported += 1
        if cq == "conflicting" and "## Open Questions" not in text:
            conflicting_no_oq += 1
        with_cite, total = _claims_inline_citation_count(body)
        bullets_total += total
        bullets_with_inline += with_cite

    return {
        "total": len(concepts),
        "by_claim_quality": dict(quality_counter),
        "unsupported": unsupported,
        "revalidation_required": revalidation_required,
        "conflicting_without_open_questions": conflicting_no_oq,
        "claim_bullets_total": bullets_total,
        "claim_bullets_with_inline_citation": bullets_with_inline,
        "inline_citation_rate": (
            round(bullets_with_inline / bullets_total, 3) if bullets_total else None
        ),
    }


def _score_sources() -> dict:
    sources = list(CONFIG.summaries_dir.glob("src-*.md"))
    strength_counter: Counter = Counter()
    kind_counter: Counter = Counter()

    for path in sources:
        frontmatter, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        strength_counter[str(frontmatter.get("evidence_strength") or "unknown")] += 1
        kind_counter[str(frontmatter.get("source_kind") or "web-page")] += 1

    total = len(sources)
    stub_count = sum(
        strength_counter.get(k, 0) for k in ("stub", "citation-only", "image-only")
    )
    primary_count = sum(
        strength_counter.get(k, 0) for k in ("primary-doc", "official-spec", "strong")
    )
    model_gen_count = strength_counter.get("model-generated", 0) + kind_counter.get(
        "imported_model_report", 0
    )

    return {
        "total": total,
        "by_evidence_strength": dict(strength_counter),
        "by_source_kind": dict(kind_counter),
        "stub_count": stub_count,
        "primary_count": primary_count,
        "model_generated_count": model_gen_count,
        "stub_fraction": round(stub_count / total, 3) if total else None,
        "primary_fraction": round(primary_count / total, 3) if total else None,
    }


def _score_claims() -> dict:
    if not _CLAIMS_PATH.exists():
        return {
            "total": 0,
            "by_quality": {},
            "with_sources": 0,
            "without_sources": 0,
        }
    payload = json.loads(_CLAIMS_PATH.read_text(encoding="utf-8"))
    claims = payload.get("claims", [])
    total = len(claims)
    with_sources = sum(1 for c in claims if c.get("source_ids"))
    quality_counter: Counter = Counter(
        str(c.get("claim_quality") or "unknown") for c in claims
    )
    return {
        "total": total,
        "by_quality": dict(quality_counter),
        "with_sources": with_sources,
        "without_sources": total - with_sources,
    }


def _score_answers() -> dict:
    answers = [
        p
        for p in CONFIG.answers_dir.glob("*.md")
        if parse_frontmatter(p.read_text(encoding="utf-8"))[0].get("type") == "answer"
    ]
    quality_counter: Counter = Counter()
    with_provenance = 0
    revalidation_required = 0

    for path in answers:
        frontmatter, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        quality_counter[str(frontmatter.get("answer_quality") or "unknown")] += 1
        sc = frontmatter.get("sources_consulted")
        if sc and isinstance(sc, list) and len(sc) > 0:
            with_provenance += 1
        if frontmatter.get("revalidation_required"):
            revalidation_required += 1

    return {
        "total": len(answers),
        "by_quality": dict(quality_counter),
        "with_provenance": with_provenance,
        "revalidation_required": revalidation_required,
    }


def _score_contradictions() -> dict:
    if not _CONTRADICTIONS_PATH.exists():
        return {"total": 0, "documented": 0, "undocumented": 0, "concepts_affected": 0}
    try:
        payload = json.loads(_CONTRADICTIONS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"total": 0, "documented": 0, "undocumented": 0, "concepts_affected": 0}
    recs = payload.get("contradictions", [])
    total = len(recs)
    documented = sum(1 for r in recs if r.get("documented"))
    concepts_affected = len({r["concept"] for r in recs if r.get("concept")})
    return {
        "total": total,
        "documented": documented,
        "undocumented": total - documented,
        "concepts_affected": concepts_affected,
    }


def _score_research() -> dict:
    if not _RESEARCH_DIR.exists():
        return {"active": 0, "by_phase": {}, "archived": 0}
    phase_counter: Counter = Counter()
    active = list((_RESEARCH_DIR / "notes").glob("*-status.md")) if (_RESEARCH_DIR / "notes").exists() else []
    archived = list((_RESEARCH_DIR / "archive").rglob("*-status.md")) if (_RESEARCH_DIR / "archive").exists() else []
    for path in active:
        frontmatter, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        phase_counter[str(frontmatter.get("phase") or "unknown")] += 1
    return {
        "active": len(active),
        "by_phase": dict(phase_counter),
        "archived": len(archived),
    }


def _compute_signals(
    concepts: dict,
    sources: dict,
    claims: dict,
    answers: dict,
    contradictions: dict | None = None,
) -> list[dict]:
    signals: list[dict] = []

    if sources["total"] > 0:
        if (sources["stub_fraction"] or 0.0) > 0.3:
            signals.append({
                "code": "high-stub-fraction",
                "severity": "warning",
                "message": f"{sources['stub_fraction']:.0%} of sources are stubs/citation-only (>30% threshold)",
            })
        if (sources["primary_fraction"] or 1.0) < 0.2 and sources["total"] >= 5:
            signals.append({
                "code": "low-primary-coverage",
                "severity": "warning",
                "message": f"Only {sources['primary_fraction']:.0%} of sources are primary/official (want ≥20%)",
            })
        model_frac = sources["model_generated_count"] / sources["total"]
        if model_frac > 0.5:
            signals.append({
                "code": "model-report-dominance",
                "severity": "warning",
                "message": f"{model_frac:.0%} of sources are model-generated — verify against primary sources",
            })

    if concepts["revalidation_required"] > 0:
        signals.append({
            "code": "revalidation-backlog",
            "severity": "warning",
            "message": (
                f"{concepts['revalidation_required']} concept(s) are flagged for revalidation; "
                "run 'stale-impact' to review, 'clear-stale-flags' when done"
            ),
        })

    if concepts["conflicting_without_open_questions"] > 0:
        signals.append({
            "code": "undocumented-conflicts",
            "severity": "warning",
            "message": (
                f"{concepts['conflicting_without_open_questions']} concept(s) have "
                "claim_quality: conflicting without an ## Open Questions section"
            ),
        })

    if concepts["unsupported"] > 0 and concepts["total"] > 0:
        signals.append({
            "code": "unsupported-concepts",
            "severity": "info",
            "message": (
                f"{concepts['unsupported']}/{concepts['total']} concept(s) have no cited sources "
                "in their Evidence section"
            ),
        })

    bullets_total = concepts.get("claim_bullets_total", 0)
    inline_rate = concepts.get("inline_citation_rate")
    if bullets_total >= 3 and inline_rate is not None and inline_rate < 0.5:
        signals.append({
            "code": "low-inline-citation-rate",
            "severity": "info",
            "message": (
                f"Only {inline_rate:.0%} of Key Claims bullets have inline source citations "
                "(aim for ≥50% — add [[Sources/src-id|source]] after each grounded claim)"
            ),
        })

    if answers["total"] > 0 and answers["with_provenance"] == 0:
        signals.append({
            "code": "no-answer-provenance",
            "severity": "info",
            "message": "No answer memos have sources_consulted populated yet (new memos will include the field)",
        })

    if answers["revalidation_required"] > 0:
        signals.append({
            "code": "answer-revalidation-backlog",
            "severity": "warning",
            "message": f"{answers['revalidation_required']} answer(s) are flagged for revalidation",
        })

    if contradictions and contradictions.get("undocumented", 0) > 0:
        signals.append({
            "code": "undocumented-contradictions",
            "severity": "warning",
            "message": (
                f"{contradictions['undocumented']} conflicting concept(s) have no Open Questions "
                "bullet — run 'extract-contradictions' then add an ## Open Questions section"
            ),
        })

    return signals


def compute_scorecard() -> dict:
    """Compute the full vault scorecard and return it as a dict."""
    concepts = _score_concepts()
    sources = _score_sources()
    claims = _score_claims()
    answers = _score_answers()
    research = _score_research()
    contradictions = _score_contradictions()
    signals = _compute_signals(concepts, sources, claims, answers, contradictions)

    return {
        "generated_at": dt.datetime.now().replace(microsecond=0).isoformat(),
        "project": CONFIG.project_name,
        "concepts": concepts,
        "sources": sources,
        "claims": claims,
        "answers": answers,
        "research": research,
        "contradictions": contradictions,
        "health_signals": signals,
    }


def run(output: Path | None = None) -> dict:
    """Compute the scorecard, write it to ``data/scorecard.json``, and return it."""
    scorecard = compute_scorecard()
    out_path = output or SCORECARD_PATH
    ensure_dir(out_path.parent)
    content = json.dumps(scorecard, indent=2, ensure_ascii=False) + "\n"
    changed = not out_path.exists() or out_path.read_text(encoding="utf-8") != content
    if changed:
        out_path.write_text(content, encoding="utf-8")
    return scorecard


def print_summary(scorecard: dict) -> None:
    """Print a human-readable scorecard summary to stdout."""
    c = scorecard["concepts"]
    s = scorecard["sources"]
    cl = scorecard["claims"]
    a = scorecard["answers"]
    r = scorecard["research"]
    ct = scorecard.get("contradictions", {})

    print(f"\n=== {scorecard['project']} Vault Scorecard ({scorecard['generated_at']}) ===\n")

    quality_str = "  ".join(
        f"{k}:{v}" for k, v in sorted(c["by_claim_quality"].items())
    ) or "none"
    print(
        f"Concepts : {c['total']} total  |  unsupported: {c['unsupported']}"
        f"  |  revalidation backlog: {c['revalidation_required']}"
    )
    print(f"           quality: {quality_str}")

    print(
        f"Sources  : {s['total']} total  |  primary: {s['primary_count']}"
        f"  |  stub: {s['stub_count']}  |  model-gen: {s['model_generated_count']}"
    )

    if cl["total"] or c.get("claim_bullets_total", 0):
        inline_pct = (
            f"{c['inline_citation_rate']:.0%}"
            if c.get("inline_citation_rate") is not None
            else "n/a"
        )
        print(
            f"Claims   : {cl['total']} extracted  |  {cl['with_sources']} with sources"
            f"  |  inline citation rate: {inline_pct}"
        )

    print(
        f"Answers  : {a['total']} total  |  durable: {a['by_quality'].get('durable', 0)}"
        f"  |  with provenance: {a['with_provenance']}"
    )

    if r["active"] or r["archived"]:
        phase_str = "  ".join(f"{k}:{v}" for k, v in sorted(r["by_phase"].items()))
        print(f"Research : {r['active']} active  |  {r['archived']} archived  |  {phase_str}")

    if ct.get("total", 0) or ct.get("concepts_affected", 0):
        print(
            f"Conflicts: {ct.get('total', 0)} records  |  "
            f"documented: {ct.get('documented', 0)}  |  "
            f"undocumented: {ct.get('undocumented', 0)}  |  "
            f"concepts: {ct.get('concepts_affected', 0)}"
        )

    signals = scorecard["health_signals"]
    if signals:
        print(f"\nHealth signals ({len(signals)}):")
        for sig in signals:
            icon = "⚠" if sig["severity"] == "warning" else "ℹ"
            print(f"  {icon}  [{sig['code']}] {sig['message']}")
    else:
        print("\nNo health signals — vault looks healthy.")
    print()
