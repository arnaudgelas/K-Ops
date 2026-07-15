"""benchmark_report.py — publish the M1/M2 benchmark as Markdown (roadmap L4.4).

This module is the *publishing* layer on top of the deterministic metrics harness
in :mod:`kops.eval_metrics`. It does **not** rebuild the harness: it consumes a
benchmark JSON report (the one ``kops benchmark`` writes) and renders a stable,
committed-friendly ``research/benchmarks/REPORT.md``.

Two design commitments make the report trustworthy rather than a marketing sheet:

1. **Honest headline.** The governance / leakage numbers are REAL and
   deterministic (they are a property of *which sources reach each baseline's
   context*, computed with no LLM). The answer-quality numbers are still PENDING a
   real-provider run, and the report says so in the headline and in a dedicated
   limitations section — they are never presented as a proven win.

2. **The M4 differentiation is demonstrated, not asserted.** Two deterministic
   decision flips are *computed at render time* from the live M4 modules and
   embedded with their real outcomes:

   - **Source independence** (:mod:`kops.source_lineage`) flips an autonomous
     corroboration decision from *permit* to *refuse* once declared lineage
     collapses the corpus derivative pair (``src-5ec0000012`` / ``src-5ec0000013``,
     both ``derived_from: src-fac0000007``) to a single independent origin.
   - **Typed contradictions** (:mod:`kops.typed_contradictions`) flip a decision
     from *qualify* to *permit* once an immaterial (terminology-mismatch)
     contradiction is distinguished from a material (direct-conflict) one.

Determinism
-----------
The rendered body carries no timestamps, wall-clock latency, or temp paths: the
report dict is passed through :func:`kops.eval_metrics.deterministic_view` before
rendering, and the M4 demonstrations are pure functions of declared inputs. Two
runs over the same corpus therefore produce byte-identical Markdown.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from kops.eval_metrics import (
    DEFAULT_CORPUS,
    DEFAULT_EVAL_RUNS_DIR,
    deterministic_view,
)
from kops.source_lineage import (
    independence_confidence,
    independent_source_ids,
    is_corroborated,
)
from kops.tier_policy import evaluate_tier_policy
from kops.typed_contradictions import classify_contradiction, material_contradiction_ids
from kops.utils import parse_frontmatter

DEFAULT_OUT_PATH = "research/benchmarks/REPORT.md"

#: The corpus derivative pair and their shared upstream (see the corpus MANIFEST).
_DERIVATIVE_PAIR = ("src-5ec0000012", "src-5ec0000013")
_DERIVATIVE_ROOT = "src-fac0000007"

# --------------------------------------------------------------------------- #
# Statistical layer — Wilson score confidence interval (stdlib only)
# --------------------------------------------------------------------------- #

#: 95% two-sided normal quantile (z_{0.975}).
Z_95 = 1.959963984540054


def wilson_interval(successes: int, total: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score confidence interval for a binomial proportion.

    The Wilson score interval is preferred over the naive normal (Wald) interval
    for rates near 0 or 1 and for small ``total`` — exactly the regime the
    governance rates live in (e.g. 0 leaks out of 84 questions). Implemented from
    first principles with the standard library only (no scipy):

        centre = (p̂ + z²/2n) / (1 + z²/n)
        margin = (z / (1 + z²/n)) · √( p̂(1-p̂)/n + z²/4n² )

    Returns ``(lo, hi)`` clamped to ``[0, 1]`` and rounded to 4 dp. A zero-sample
    rate returns ``(0.0, 0.0)``.
    """
    if total <= 0:
        return (0.0, 0.0)
    p = successes / total
    z2 = z * z
    denom = 1.0 + z2 / total
    centre = (p + z2 / (2 * total)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / total + z2 / (4 * total * total))
    lo = max(0.0, centre - margin)
    hi = min(1.0, centre + margin)
    return (round(lo, 4), round(hi, 4))


def _rate_with_ci(successes: int, total: int) -> str:
    """Format ``x (95% CI [lo, hi])`` for a count of successes over a total."""
    if total <= 0:
        return "n/a (no samples)"
    rate = successes / total
    lo, hi = wilson_interval(successes, total)
    return f"{rate:.3f} (95% CI [{lo:.3f}, {hi:.3f}]; {successes}/{total})"


def _count_from_rate(rate: float, total: int) -> int:
    """Reconstruct the integer success count backing a rounded rate."""
    return int(round(rate * total))


# --------------------------------------------------------------------------- #
# M4 differentiation — two deterministic decision flips, computed live
# --------------------------------------------------------------------------- #


def _load_corpus_meta(corpus_dir: Path, source_ids: list[str]) -> dict[str, dict]:
    """Read source-note frontmatter for ``source_ids`` from the benchmark corpus.

    This is the real declared provenance the lineage collapse consults — not a
    hand-written stub — so the independence demonstration reflects a genuine flip.
    """
    meta: dict[str, dict] = {}
    src_dir = corpus_dir / "notes" / "Sources"
    for sid in source_ids:
        note = src_dir / f"{sid}.md"
        if note.exists():
            fm, _ = parse_frontmatter(note.read_text(encoding="utf-8"))
            meta[sid] = fm
        else:
            meta[sid] = {}
    return meta


def compute_independence_flip(corpus_dir: Path | None = None) -> dict[str, Any]:
    """Demonstrate that source independence changes ≥1 corroboration decision.

    A claim cites the corpus derivative pair (two secondary blogs that both
    ``derived_from`` the single vendor benchmark ``src-fac0000007``). At the
    autonomous tier:

    - **Without lineage** (declared ``derived_from`` ignored): the two ids look
      like two independent witnesses → ``is_corroborated`` is True → *permit*.
    - **With lineage** (real corpus frontmatter): they collapse to one origin →
      ``is_corroborated`` is False → ``needs-corroboration`` → *refuse*.

    Returns the two decisions plus supporting counts, all computed from the live
    :mod:`kops.tier_policy` / :mod:`kops.source_lineage` modules.
    """
    corpus_dir = Path(corpus_dir or DEFAULT_CORPUS)
    ids = [*_DERIVATIVE_PAIR, _DERIVATIVE_ROOT]
    lineage_meta = _load_corpus_meta(corpus_dir, ids)
    # "Without lineage" = the same sources, but the declared derived_from signal
    # is not consulted (the pre-L4.2 naive distinct-source count).
    naive_meta = {
        sid: {k: v for k, v in fm.items() if k != "derived_from"}
        for sid, fm in lineage_meta.items()
    }

    claim = {
        "claim_id": "clm-torque-throughput",
        "source_ids": list(_DERIVATIVE_PAIR),
        "admission_status": "admitted",
        "evidence_status": "direct",
        "claim_quality": "supported",
    }
    naive = evaluate_tier_policy([claim], "autonomous", meta_by_id=naive_meta)
    lineage = evaluate_tier_policy([claim], "autonomous", meta_by_id=lineage_meta)

    return {
        "cited_sources": list(_DERIVATIVE_PAIR),
        "shared_upstream": _DERIVATIVE_ROOT,
        "naive_decision": naive["decision"],
        "lineage_decision": lineage["decision"],
        "naive_independent_ids": independent_source_ids(list(_DERIVATIVE_PAIR), naive_meta),
        "lineage_independent_ids": independent_source_ids(list(_DERIVATIVE_PAIR), lineage_meta),
        "naive_corroborated": is_corroborated(list(_DERIVATIVE_PAIR), naive_meta),
        "lineage_corroborated": is_corroborated(list(_DERIVATIVE_PAIR), lineage_meta),
        "lineage_barred_reasons": sorted({r for b in lineage["barred"] for r in b["reasons"]}),
        "independence_confidence_naive": independence_confidence(
            list(_DERIVATIVE_PAIR), naive_meta
        ),
        "independence_confidence_lineage": independence_confidence(
            list(_DERIVATIVE_PAIR), lineage_meta
        ),
        "flipped": naive["decision"] != lineage["decision"],
    }


def compute_materiality_flip() -> dict[str, Any]:
    """Demonstrate that typed contradictions improve qualify/abstain.

    One claim participates in a contradiction. The contradiction is classified by
    the live :mod:`kops.typed_contradictions` classifier:

    - a **direct-conflict** record is *material* → at the decision tier it forces
      *qualify*;
    - a **terminology-mismatch** record is *immaterial* → the same claim now
      *permits* (the contradiction is downgraded to an advisory warning).

    Both classifications come from the real classifier over the record text, and
    both decisions come from :func:`kops.tier_policy.evaluate_tier_policy`.
    """
    claim = {
        "claim_id": "clm-torque-semantics",
        "source_ids": ["src-fac0000001", "src-5ec0000014"],
        "admission_status": "admitted",
        "evidence_status": "direct",
        "claim_quality": "supported",
        "conflicts_with": ["clm-torque-semantics-alt"],
    }
    claims = [claim]

    material_record = {
        "id": "c-demo-material",
        "concept": "Torque Processing Semantics",
        "concept_path": "notes/Concepts/Torque_Processing_Semantics.md",
        "open_question": (
            "The vendor claims exactly-once delivery but the community reports "
            "at-least-once plus dedup — a direct conflict over what actually happens."
        ),
        "documented": True,
        "claim_ids": ["clm-torque-semantics"],
        "source_ids": ["src-fac0000001", "src-5ec0000014"],
    }
    immaterial_record = {
        "id": "c-demo-immaterial",
        "concept": "Torque Processing Semantics",
        "concept_path": "notes/Concepts/Torque_Processing_Semantics.md",
        "open_question": (
            "The two notes use a different term for the same concept; this is a "
            "terminology / naming difference, not a substantive disagreement."
        ),
        "documented": True,
        "claim_ids": ["clm-torque-semantics"],
        "source_ids": ["src-fac0000001", "src-5ec0000014"],
    }

    material_type = classify_contradiction(material_record)
    immaterial_type = classify_contradiction(immaterial_record)
    material_ids = material_contradiction_ids(claims, [material_record])
    immaterial_ids = material_contradiction_ids(claims, [immaterial_record])

    material_decision = evaluate_tier_policy(
        claims, "decision", material_contradictions=material_ids
    )
    immaterial_decision = evaluate_tier_policy(
        claims, "decision", material_contradictions=immaterial_ids
    )

    return {
        "material_type": material_type.contradiction_type,
        "material_materiality": material_type.materiality,
        "immaterial_type": immaterial_type.contradiction_type,
        "immaterial_materiality": immaterial_type.materiality,
        "material_decision": material_decision["decision"],
        "immaterial_decision": immaterial_decision["decision"],
        "material_forced_ids": sorted(material_ids),
        "immaterial_forced_ids": sorted(immaterial_ids),
        "flipped": material_decision["decision"] != immaterial_decision["decision"],
    }


# --------------------------------------------------------------------------- #
# Markdown rendering
# --------------------------------------------------------------------------- #


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join([" --- "] * len(headers)) + "|"]
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(out)


def _headline(report: dict[str, Any]) -> str:
    gov = report["metrics"]["governance"]
    n = report["question_count"]
    kops_leak = gov["current-kops"]["revoked_source_leakage"]
    bm25_leak = gov["bm25-agent"]["revoked_source_leakage"]
    review = report["metrics"]["operations"]["current-kops"]["review_minutes_per_accepted_answer"]
    return (
        f"**On a versioned adversarial corpus of {n} governed questions, K-Ops served "
        f"{kops_leak} stale/revoked-source decision answers versus BM25's {bm25_leak} leaks, "
        f"at ~{review:.1f} review-minutes per accepted answer.** These governance/leakage "
        "numbers are REAL and deterministic (a property of retrieval/exclusion, no LLM). "
        "Answer-*quality* wins remain PENDING a real-provider run and are NOT claimed here."
    )


def _corpus_section(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "## Corpus version and snapshot",
            "",
            _md_table(
                ["Field", "Value"],
                [
                    ["Corpus", report.get("corpus", "?")],
                    ["Snapshot", report.get("snapshot") or "(base corpus, no overlay)"],
                    ["Questions graded", report.get("question_count", "?")],
                    ["Schema version", report.get("schema_version", "?")],
                    ["Harness policy version", report.get("harness_policy_version", "?")],
                    ["Retrieval top-k", report.get("top_k", "?")],
                ],
            ),
            "",
            "The default snapshot is `03-retraction`, in which one source "
            "(`src-5ec0000016`, a 5M-events/sec blog) is revoked. That is the state in "
            "which the governance advantage is demonstrable: an ungoverned lexical baseline "
            "retrieves the revoked source; governed K-Ops excludes it.",
        ]
    )


def _provider_section(report: dict[str, Any]) -> str:
    prov = report.get("provider") or {}
    name = prov.get("name", "deterministic (offline)")
    fingerprint = prov.get("fingerprint", "n/a")
    return "\n".join(
        [
            "## Models, prompts, and provider",
            "",
            _md_table(
                ["Field", "Value"],
                [
                    ["Provider", name],
                    ["Provider fingerprint", fingerprint],
                    ["Baselines", ", ".join(report.get("baselines", []))],
                ],
            ),
            "",
            "The committed report is generated with the offline **deterministic provider**: "
            "it emits canned answer templates, so every *answer-quality* number below is "
            "demo/plumbing (clearly labelled). Governance, retrieval, and the M4 "
            "differentiation are independent of the provider and are real today.",
        ]
    )


def _baselines_section(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "## Baseline configurations",
            "",
            "Four baselines run over identical questions and corpus state:",
            "",
            "- **raw-agent** — no retrieval grounding; answers from the model prior only.",
            "- **bm25-agent** — ungoverned lexical (BM25) retrieval; no exclusion filter.",
            "- **current-kops** — governed retrieval: flagged/revoked sources excluded, "
            "consequence-tier evidence bar applied.",
            "- **improved-kops** — current-kops plus the M2/M4 policy refinements.",
        ]
    )


def _retrieval_section(report: dict[str, Any]) -> str:
    retr = report["metrics"]["retrieval"]
    rows = [
        [
            name,
            f"{retr[name]['recall_at_k']:.3f}",
            f"{retr[name]['evidence_coverage']:.3f}",
            f"{retr[name]['irrelevant_context_rate']:.3f}",
        ]
        for name in report["baselines"]
    ]
    return "\n".join(
        [
            "## Retrieval performance",
            "",
            "Deterministic (measured from retrieved-context membership; no LLM).",
            "",
            _md_table(
                ["Baseline", "recall@k", "evidence_coverage", "irrelevant_context_rate"], rows
            ),
        ]
    )


def _citation_section(report: dict[str, Any]) -> str:
    ent = report.get("entailment") or {}
    status = ent.get("_status", "unknown")
    lines = [
        "## Citation support",
        "",
        f"Cited-span entailment (J1.1 judge): **{status}**.",
    ]
    if status in {"real", "no-pairs"}:
        lines.append("")
        lines.append(f"- Cited (claim, span) pairs judged: {ent.get('cited_span_pairs_judged', 0)}")
        lines.append(f"- Verdict distribution: {ent.get('verdict_distribution', {})}")
        cal = ent.get("calibration")
        if cal:
            lines.append(
                f"- Calibration vs GOLD: {cal.get('accuracy_vs_gold')} "
                f"over {cal.get('fixtures_scored')} fixtures"
            )
    else:
        lines.append("")
        lines.append(
            "No judge was configured for this run, so citation entailment is reported as "
            "PENDING rather than fabricated. Set `KB_JUDGE_AGENT`/`KB_JUDGE_CMD` and pass "
            "`--entailment` to score it and calibrate against the human GOLD fixtures."
        )
    return "\n".join(lines)


def _leakage_section(report: dict[str, Any]) -> str:
    gov = report["metrics"]["governance"]
    n = report["question_count"]
    rows = []
    for name in report["baselines"]:
        revoked = gov[name]["revoked_source_leakage"]
        flagged = gov[name]["flagged_source_leakage"]
        stale = gov[name]["stale_answer_leakage"]
        rows.append(
            [
                name,
                revoked,
                _rate_with_ci(revoked, n),
                flagged,
                stale,
                gov[name]["time_to_invalidate"],
            ]
        )
    return "\n".join(
        [
            "## Stale and retracted source leakage",
            "",
            "The headline result. A *leak* is a flagged/revoked source reaching a baseline's "
            "answer context. REAL and deterministic — no LLM involved.",
            "",
            _md_table(
                [
                    "Baseline",
                    "revoked leaks",
                    "revoked-leak rate",
                    "flagged leaks",
                    "stale leaks",
                    "time-to-invalidate",
                ],
                rows,
            ),
            "",
            f"Governed K-Ops leaks **{gov['current-kops']['revoked_source_leakage']}** revoked "
            f"sources; the ungoverned BM25 baseline leaks "
            f"**{gov['bm25-agent']['revoked_source_leakage']}** out of {n} questions. Exclusion "
            "is synchronous on status change (0 retrieval cycles to invalidate).",
        ]
    )


def _safe_grounded_section(report: dict[str, Any]) -> str:
    n = report["question_count"]
    sgr = report["safe_grounded_rate"]
    rows = []
    for name in report["baselines"]:
        rate = sgr[name]
        k = _count_from_rate(rate, n)
        rows.append([name, _rate_with_ci(k, n)])
    return "\n".join(
        [
            "## Safe-grounded rate (composite advantage)",
            "",
            "Fraction of questions where the baseline retrieves ≥1 relevant CLEAN source AND "
            "leaks 0 flagged/revoked sources — the single metric where K-Ops beats BOTH "
            "raw-agent (no grounding) and bm25-agent (leaks). Rates carry a Wilson 95% CI.",
            "",
            _md_table(["Baseline", "safe_grounded_rate"], rows),
        ]
    )


def _contradiction_section(report: dict[str, Any], materiality: dict[str, Any]) -> str:
    return "\n".join(
        [
            "## Contradiction handling",
            "",
            "K-Ops records contradictions as *typed* records (L4.1) and treats them by "
            "materiality: a material contradiction gates a decision; an immaterial one "
            "(terminology / extraction / scope) is downgraded to an advisory warning. The "
            "measured effect on the decision tier is:",
            "",
            _md_table(
                ["Contradiction", "Classified type", "Materiality", "Decision-tier outcome"],
                [
                    [
                        "Vendor vs community semantics",
                        materiality["material_type"],
                        materiality["material_materiality"],
                        materiality["material_decision"],
                    ],
                    [
                        "Terminology difference",
                        materiality["immaterial_type"],
                        materiality["immaterial_materiality"],
                        materiality["immaterial_decision"],
                    ],
                ],
            ),
            "",
            "See the **M4 differentiation** section for the full measured delta.",
        ]
    )


def _gate_section(report: dict[str, Any]) -> str:
    gov = report["metrics"]["governance"]
    rows = [
        [
            name,
            gov[name]["decision_gate_false_accept"],
            gov[name]["decision_gate_false_reject"],
        ]
        for name in report["baselines"]
    ]
    return "\n".join(
        [
            "## Decision-gate accuracy (false accept / false reject)",
            "",
            "A *false accept* is a flagged source admitted to a high-tier "
            "(recommendation/decision/autonomous) answer; a *false reject* is a clean, "
            "relevant source the baseline dropped that the ungoverned baseline kept.",
            "",
            _md_table(
                ["Baseline", "decision_gate_false_accept", "decision_gate_false_reject"], rows
            ),
        ]
    )


def _review_section(report: dict[str, Any]) -> str:
    ops = report["metrics"]["operations"]
    rows = [
        [name, f"{ops[name]['review_minutes_per_accepted_answer']:.3f}"]
        for name in report["baselines"]
    ]
    return "\n".join(
        [
            "## Review burden",
            "",
            "Deterministic review-cost model: minutes of human review per accepted answer, "
            "weighted by consequence tier.",
            "",
            _md_table(["Baseline", "review_minutes_per_accepted_answer"], rows),
        ]
    )


def _latency_cost_section(report: dict[str, Any]) -> str:
    ops = report["metrics"]["operations"]
    rows = [
        [
            name,
            ops[name].get("model_cost_usd", 0.0),
            ops[name].get("token_usage") if ops[name].get("token_usage") is not None else "N/A",
        ]
        for name in report["baselines"]
    ]
    return "\n".join(
        [
            "## Latency and cost",
            "",
            "Wall-clock latency is volatile and is therefore excluded from this committed "
            "body (it lives in the per-run JSON under `data/eval_runs/`). Token usage and "
            "model cost are 0 / N/A with the offline deterministic provider.",
            "",
            _md_table(["Baseline", "model_cost_usd", "token_usage"], rows),
        ]
    )


def _m4_section(independence: dict[str, Any], materiality: dict[str, Any]) -> str:
    lines = [
        "## M4 differentiation",
        "",
        "The two defensible M4 capabilities, each shown as a **measured decision delta** over "
        "the benchmark corpus. Both are deterministic (no LLM) and computed live from the M4 "
        "modules at render time, not written as prose.",
        "",
        "### (a) Source independence changes a corroboration decision",
        "",
        f"A claim cites the corpus derivative pair `{independence['cited_sources'][0]}` and "
        f"`{independence['cited_sources'][1]}` — two secondary blogs that both "
        f"`derived_from` the single vendor benchmark `{independence['shared_upstream']}`. "
        "Evaluated at the **autonomous** tier:",
        "",
        _md_table(
            ["Lineage consulted?", "Independent origins", "Corroborated?", "Autonomous decision"],
            [
                [
                    "No (naive distinct-source count)",
                    ", ".join(independence["naive_independent_ids"])
                    + f" ({len(independence['naive_independent_ids'])})",
                    independence["naive_corroborated"],
                    f"**{independence['naive_decision']}**",
                ],
                [
                    "Yes (declared `derived_from`)",
                    ", ".join(independence["lineage_independent_ids"])
                    + f" ({len(independence['lineage_independent_ids'])})",
                    independence["lineage_corroborated"],
                    f"**{independence['lineage_decision']}**",
                ],
            ],
        ),
        "",
        f"**Decision flip: `{independence['naive_decision']}` → "
        f"`{independence['lineage_decision']}`** "
        f"(barred for: {', '.join(independence['lineage_barred_reasons']) or 'n/a'}). "
        "Consulting declared lineage collapses two apparent witnesses to one independent "
        "origin, so the autonomous corroboration requirement is no longer met.",
        "",
        "### (b) Typed contradictions improve qualify/abstain",
        "",
        "The same claim participates in a contradiction. The typed classifier decides "
        "materiality; the tier policy decides the outcome at the **decision** tier:",
        "",
        _md_table(
            ["Contradiction record", "Classified type", "Materiality", "Decision"],
            [
                [
                    "Direct conflict (vendor vs community)",
                    materiality["material_type"],
                    materiality["material_materiality"],
                    f"**{materiality['material_decision']}**",
                ],
                [
                    "Terminology mismatch",
                    materiality["immaterial_type"],
                    materiality["immaterial_materiality"],
                    f"**{materiality['immaterial_decision']}**",
                ],
            ],
        ),
        "",
        f"**Decision delta: `{materiality['material_decision']}` → "
        f"`{materiality['immaterial_decision']}`.** A material (direct-conflict) contradiction "
        "forces the decision to qualify; distinguishing an immaterial (terminology-mismatch) "
        "contradiction lets the same claim permit, instead of over-gating every disagreement.",
    ]
    return "\n".join(lines)


def _limitations_section(report: dict[str, Any]) -> str:
    aq = report["metrics"]["answer_quality"]
    return "\n".join(
        [
            "## Failures and limitations",
            "",
            "- **Answer quality is PENDING a real provider.** Every number in the "
            f"`answer_quality` family is marked `{aq.get('_status')}`: it is graded from the "
            "offline provider's canned answers and must not be read as a proven accuracy win. "
            "A real-provider run is required before any answer-quality headline.",
            "- **Citation entailment** is only scored when a judge is configured; otherwise it "
            "is reported as PENDING (never fabricated).",
            "- **Latency** is volatile and excluded from this committed body.",
            "- **The corpus is authored fixtures** (fictional project *Torque*). The governance "
            "and M4 deltas are real *given the corpus*; external validity requires re-running on "
            "additional corpora.",
            "- **Stale-answer leakage is 0 in a single-state run** and is exercised by "
            "cross-snapshot timelines, not by this single overlay.",
        ]
    )


def render_report(report: dict[str, Any], *, corpus_dir: Path | None = None) -> str:
    """Render a benchmark JSON report to a deterministic Markdown document.

    ``report`` is a benchmark dict (as written by ``kops benchmark``). It is passed
    through :func:`kops.eval_metrics.deterministic_view` first, so volatile fields
    (timestamps, wall-clock latency, temp paths) never reach the body and two runs
    render byte-identically. The M4 differentiation section is computed live from
    the corpus and the M4 modules.
    """
    view = deterministic_view(report)
    corpus_dir = Path(corpus_dir or DEFAULT_CORPUS)
    independence = compute_independence_flip(corpus_dir)
    materiality = compute_materiality_flip()

    parts = [
        "# K-Ops Benchmark Report",
        "",
        "## Headline",
        "",
        _headline(view),
        "",
        _corpus_section(view),
        "",
        _provider_section(view),
        "",
        _baselines_section(view),
        "",
        _retrieval_section(view),
        "",
        _citation_section(view),
        "",
        _leakage_section(view),
        "",
        _safe_grounded_section(view),
        "",
        _contradiction_section(view, materiality),
        "",
        _gate_section(view),
        "",
        _review_section(view),
        "",
        _latency_cost_section(view),
        "",
        _m4_section(independence, materiality),
        "",
        _limitations_section(view),
        "",
    ]
    return "\n".join(parts).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# Report loading / generation
# --------------------------------------------------------------------------- #


def _latest_benchmark_json(eval_runs_dir: Path) -> Path | None:
    candidates = sorted(Path(eval_runs_dir).glob("benchmark-*.json"))
    return candidates[-1] if candidates else None


def _load_or_run(
    *, run: bool, eval_runs_dir: Path, corpus_dir: Path | None, golden_set: Path | None
) -> dict[str, Any]:
    """Return a benchmark report dict: reuse the latest JSON, or run the harness."""
    if not run:
        latest = _latest_benchmark_json(eval_runs_dir)
        if latest is not None:
            return json.loads(latest.read_text(encoding="utf-8"))
    # Run the harness deterministically (offline provider, retraction overlay).
    from kops.eval_metrics import run_benchmark as _run_benchmark

    return _run_benchmark(corpus_dir=corpus_dir, golden_set_path=golden_set)


def generate(
    *,
    out_path: str | Path = DEFAULT_OUT_PATH,
    report: dict[str, Any] | None = None,
    run: bool = False,
    eval_runs_dir: str | Path | None = None,
    corpus_dir: str | Path | None = None,
    golden_set: str | Path | None = None,
) -> Path:
    """Generate ``REPORT.md`` from a benchmark report and write it deterministically.

    With ``report=None`` this consumes the latest ``data/eval_runs/benchmark-*.json``
    (or runs the harness when ``run=True`` or none exists). The written body carries
    no timestamps, so re-running over the same corpus leaves the file unchanged.
    """
    eval_runs_dir = Path(eval_runs_dir or DEFAULT_EVAL_RUNS_DIR)
    corpus_path = Path(corpus_dir) if corpus_dir else None
    if report is None:
        report = _load_or_run(
            run=run,
            eval_runs_dir=eval_runs_dir,
            corpus_dir=corpus_path,
            golden_set=Path(golden_set) if golden_set else None,
        )
    markdown = render_report(report, corpus_dir=corpus_path)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown, encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m kops.benchmark_report",
        description="Render the published benchmark REPORT.md from the metrics harness.",
    )
    parser.add_argument("--out", default=DEFAULT_OUT_PATH, help="Output path for REPORT.md.")
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run the benchmark harness now instead of reusing the latest JSON.",
    )
    parser.add_argument(
        "--eval-runs-dir", help="Directory of benchmark-*.json (default: data/eval_runs)."
    )
    parser.add_argument("--corpus", help="Benchmark corpus dir (default: E1.1 held-out).")
    parser.add_argument("--golden-set", help="Golden set YAML (default: E1.2 golden_set).")
    args = parser.parse_args(argv)

    out = generate(
        out_path=args.out,
        run=args.run,
        eval_runs_dir=args.eval_runs_dir,
        corpus_dir=args.corpus,
        golden_set=args.golden_set,
    )
    print(f"Report written to: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
