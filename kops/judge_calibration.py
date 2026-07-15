"""Calibrate the entailment judge (M1 roadmap task J1.2).

The J1.1 :mod:`kops.entailment_judge` produces verdicts. This module answers a
different, safety-critical question: *is that judge trustworthy enough to gate
decision-tier outputs?* It never presents an uncalibrated judge as calibrated.

What it computes
----------------
Given a hand-authored labeled set of ``(claim, span, context, GOLD verdict)``
pairs (``research/benchmarks/held-out/entailment_calibration.jsonl``) and a
judge, it reports:

* **confusion matrix** overall and **by claim type** (predicted vs gold);
* **false-support rate** — the safety metric: the fraction of gold
  ``unsupported`` / ``contradicted`` / ``not_evaluable`` cases the judge called
  ``supported`` / ``partial``. A judge that fabricates support is worse than one
  that abstains, so this number is reported first and loudest;
* **agreement vs gold**, overall and *per adversarial category* (a single
  headline number is explicitly insufficient — roadmap J1.2);
* **model / prompt drift**: the judge fingerprint + policy version are recorded
  with every run and compared across runs; a change is flagged as drift;
* **inter-annotator agreement (Cohen's kappa)**: computed from TWO human
  annotators' label files. There are no human annotators in-session, so with
  fewer than two files supplied the harness reports
  ``PENDING: 2 human annotations required`` rather than inventing labels.

Honesty constraints
-------------------
* GOLD labels are human-authored ground truth in the fixture file.
* Human inter-annotator agreement and a real-provider false-support number are
  **PENDING** until real annotators / a real judge run exist. This module refuses
  to fabricate either. See ``research/benchmarks/CALIBRATION.md`` for the gate
  rule and the PENDING expansion tasks.

Entry point
-----------
``python -m kops.judge_calibration`` (deliberately NOT a ``kb.py`` subcommand).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from kops.entailment_judge import (
    CONTRADICTED,
    ENTAILMENT_POLICY_VERSION,
    NOT_EVALUABLE,
    PARTIAL,
    SUPPORTED,
    UNSUPPORTED,
    VERDICTS,
    EntailmentCache,
    judge,
)
from kops.evidence_model import AtomicClaim, SourceSpan
from kops.kb_paths import ROOT

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

DEFAULT_LABELED_SET = ROOT / "research" / "benchmarks" / "held-out" / "entailment_calibration.jsonl"
EVAL_RUNS_DIR = ROOT / "data" / "eval_runs"

# The eight adversarial failure types the roadmap requires the set to cover.
ADVERSARIAL_TYPES: tuple[str, ...] = (
    "correct-quote-wrong-claim",
    "partial-quote",
    "reversed-causality",
    "omitted-qualifier",
    "wrong-temporal-scope",
    "discussing-not-supporting",
    "front-matter-as-evidence",
    "derivative-as-corroboration",
)

# A judge that returns one of these on a gold-negative case has fabricated
# support — the failure mode false-support-rate is designed to catch.
SUPPORTIVE_VERDICTS: frozenset[str] = frozenset({SUPPORTED, PARTIAL})
# Gold cases that a trustworthy judge must NOT call supportive.
NON_SUPPORTIVE_VERDICTS: frozenset[str] = frozenset({UNSUPPORTED, CONTRADICTED, NOT_EVALUABLE})

REQUIRED_ANNOTATORS = 2
# Minimum stratified pairs required before entailment may gate decision-tier
# outputs (roadmap J1.2). The in-session seed set is below this on purpose.
DECISION_GATE_MIN_PAIRS = 150


# --------------------------------------------------------------------------- #
# Labeled pair
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LabeledPair:
    """One hand-authored calibration fixture with a GOLD ground-truth verdict."""

    pair_id: str
    claim_type: str
    category: str
    adversarial_type: str | None
    claim_text: str
    claim_id: str
    span: dict | None
    context: str
    source_metadata: dict
    gold_verdict: str
    note: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> LabeledPair:
        claim = d.get("claim") or {}
        return cls(
            pair_id=str(d.get("pair_id") or ""),
            claim_type=str(d.get("claim_type") or "unspecified"),
            category=str(d.get("category") or ""),
            adversarial_type=d.get("adversarial_type"),
            claim_text=str(claim.get("claim_text") or ""),
            claim_id=str(claim.get("claim_id") or ""),
            span=d.get("span"),
            context=str(d.get("context") or ""),
            source_metadata=dict(d.get("source_metadata") or {}),
            gold_verdict=str(d.get("gold_verdict") or ""),
            note=str(d.get("note") or ""),
        )

    def as_claim(self) -> AtomicClaim:
        return AtomicClaim(
            claim_id=self.claim_id or self.pair_id,
            claim_text=self.claim_text,
            concept=self.claim_type,
        )

    def as_span(self) -> SourceSpan | None:
        if not self.span:
            return None
        return SourceSpan(
            source_id=str(self.span.get("source_id") or ""),
            quote=self.span.get("quote"),
            section=self.span.get("section"),
        )


def load_labeled_set(path: Path | str = DEFAULT_LABELED_SET) -> list[LabeledPair]:
    """Parse the JSONL calibration set. Lines whose keys start with ``_`` (the
    header / schema comment) are skipped."""
    path = Path(path)
    pairs: list[LabeledPair] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        obj = json.loads(raw)
        if not isinstance(obj, dict) or "pair_id" not in obj:
            # Header / metadata line (e.g. {"_comment": ...}).
            continue
        pair = LabeledPair.from_dict(obj)
        if pair.gold_verdict not in VERDICTS:
            raise ValueError(
                f"pair {pair.pair_id!r} has gold_verdict {pair.gold_verdict!r} "
                f"not in the verdict enum {VERDICTS}"
            )
        pairs.append(pair)
    return pairs


def validate_coverage(pairs: Iterable[LabeledPair]) -> dict:
    """Report category / adversarial-type coverage of a labeled set."""
    pairs = list(pairs)
    adv_present = {p.adversarial_type for p in pairs if p.adversarial_type}
    missing_adv = [a for a in ADVERSARIAL_TYPES if a not in adv_present]
    return {
        "n_pairs": len(pairs),
        "by_category": dict(Counter(p.category for p in pairs)),
        "by_gold": dict(Counter(p.gold_verdict for p in pairs)),
        "by_claim_type": dict(Counter(p.claim_type for p in pairs)),
        "by_adversarial_type": dict(
            Counter(p.adversarial_type for p in pairs if p.adversarial_type)
        ),
        "adversarial_types_missing": missing_adv,
        "all_adversarial_types_present": not missing_adv,
        "meets_decision_gate_size": len(pairs) >= DECISION_GATE_MIN_PAIRS,
        "decision_gate_min_pairs": DECISION_GATE_MIN_PAIRS,
    }


# --------------------------------------------------------------------------- #
# Prediction (real judge, or an injected stub for tests)
# --------------------------------------------------------------------------- #

PredictFn = Callable[[LabeledPair], str]


class JudgeRunner:
    """Default predictor: runs the real J1.1 judge and collects fingerprints.

    Uses a throwaway cache so a calibration run never pollutes the persistent
    verdict cache, and records the distinct judge fingerprints observed so the
    run can be checked for model/prompt drift.
    """

    def __init__(
        self, *, agent: str | None = None, model: str | None = None, cache_dir: Path | None = None
    ) -> None:
        self.agent = agent
        self.model = model
        import tempfile

        self._cache = EntailmentCache(
            cache_dir or Path(tempfile.mkdtemp(prefix="kops-calib-cache-"))
        )
        self.fingerprints: set[str] = set()
        self.models: set[str] = set()

    def predict(self, pair: LabeledPair) -> str:
        verdict = judge(
            pair.as_claim(),
            pair.as_span(),
            context=pair.context,
            source_metadata=pair.source_metadata,
            agent=self.agent,
            model=self.model,
            cache=self._cache,
        )
        if verdict.judge_prompt_fingerprint:
            self.fingerprints.add(verdict.judge_prompt_fingerprint)
        if verdict.judge_model:
            self.models.add(verdict.judge_model)
        return verdict.verdict

    def fingerprint(self) -> str:
        """A stable digest of the distinct provider fingerprints seen this run.

        Empty (no provider was ever invoked — e.g. an all-not_evaluable slice)
        yields ``"no-provider-invoked"`` rather than a misleading blank.
        """
        if not self.fingerprints:
            return "no-provider-invoked"
        from kops.evidence_model import content_hash

        return content_hash("\x1f".join(sorted(self.fingerprints)))


# --------------------------------------------------------------------------- #
# Confusion matrix + metrics
# --------------------------------------------------------------------------- #


def confusion_matrix(pairs: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    """Build a ``gold -> predicted -> count`` matrix over ``(gold, pred)`` pairs.

    Every verdict label appears as a key in both dimensions so cells are stable
    and directly assertable (missing combinations are explicit zeros).
    """
    matrix: dict[str, dict[str, int]] = {g: {p: 0 for p in VERDICTS} for g in VERDICTS}
    for gold, pred in pairs:
        if gold not in matrix:
            matrix[gold] = {p: 0 for p in VERDICTS}
        if pred not in matrix[gold]:
            matrix[gold][pred] = 0
        matrix[gold][pred] += 1
    return matrix


def false_support(rows: list[dict]) -> dict:
    """Compute the false-support rate over prediction rows.

    A false support is a gold-negative case (``unsupported`` / ``contradicted``
    / ``not_evaluable``) that the judge called ``supported`` or ``partial``.
    """
    negatives = [r for r in rows if r["gold"] in NON_SUPPORTIVE_VERDICTS]
    offenders = [r for r in negatives if r["predicted"] in SUPPORTIVE_VERDICTS]
    n_neg = len(negatives)
    rate = (len(offenders) / n_neg) if n_neg else 0.0
    return {
        "n_gold_negative": n_neg,
        "n_false_support": len(offenders),
        "false_support_rate": rate,
        "offending_pair_ids": [r["pair_id"] for r in offenders],
    }


def _agreement(rows: list[dict]) -> dict:
    n = len(rows)
    correct = sum(1 for r in rows if r["correct"])
    return {"n": n, "n_correct": correct, "agreement": (correct / n) if n else 0.0}


# --------------------------------------------------------------------------- #
# Cohen's kappa (stdlib only)
# --------------------------------------------------------------------------- #


def cohen_kappa(labels_a: list[str], labels_b: list[str]) -> float:
    """Cohen's kappa for two annotators over aligned label lists.

    ``kappa = (p_o - p_e) / (1 - p_e)`` where ``p_o`` is observed agreement and
    ``p_e`` is the agreement expected by chance from each annotator's marginals.
    When chance agreement is total (``p_e == 1``) kappa is defined here as
    ``1.0`` iff the annotators agreed on everything, else ``0.0``.
    """
    if len(labels_a) != len(labels_b):
        raise ValueError("annotator label lists must be the same length")
    n = len(labels_a)
    if n == 0:
        raise ValueError("cannot compute kappa over zero items")
    agree = sum(1 for a, b in zip(labels_a, labels_b) if a == b)
    p_o = agree / n
    count_a = Counter(labels_a)
    count_b = Counter(labels_b)
    labels = set(count_a) | set(count_b)
    p_e = sum((count_a[label] / n) * (count_b[label] / n) for label in labels)
    if p_e >= 1.0:
        return 1.0 if p_o >= 1.0 else 0.0
    return (p_o - p_e) / (1.0 - p_e)


def load_annotations(path: Path | str) -> dict[str, str]:
    """Load one annotator's labels: a JSONL/JSON of ``{pair_id, verdict}``.

    Accepts ``verdict`` or ``label`` as the label field. Returns a
    ``pair_id -> verdict`` mapping.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8").strip()
    out: dict[str, str] = {}
    if text.startswith("["):
        rows = json.loads(text)
    else:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    for row in rows:
        pid = str(row.get("pair_id") or "")
        label = row.get("verdict") or row.get("label")
        if pid and label:
            out[pid] = str(label)
    return out


def inter_annotator_agreement(annotator_paths: list[Path | str] | None) -> dict:
    """Cohen's kappa between two human annotators, or a PENDING report.

    With fewer than :data:`REQUIRED_ANNOTATORS` annotator files supplied, no
    number is invented: the result is a PENDING status. This is the honest path
    while there are no human annotators in-session.
    """
    paths = list(annotator_paths or [])
    if len(paths) < REQUIRED_ANNOTATORS:
        return {
            "status": "PENDING",
            "required_annotators": REQUIRED_ANNOTATORS,
            "provided": len(paths),
            "cohen_kappa": None,
            "message": (
                f"PENDING: {REQUIRED_ANNOTATORS} human annotations required; "
                f"{len(paths)} supplied. Inter-annotator agreement is not computed "
                "and MUST NOT be assumed."
            ),
        }
    ann_a = load_annotations(paths[0])
    ann_b = load_annotations(paths[1])
    shared = sorted(set(ann_a) & set(ann_b))
    if not shared:
        return {
            "status": "PENDING",
            "required_annotators": REQUIRED_ANNOTATORS,
            "provided": len(paths),
            "cohen_kappa": None,
            "message": "PENDING: the two annotator files share no pair_ids.",
        }
    labels_a = [ann_a[p] for p in shared]
    labels_b = [ann_b[p] for p in shared]
    kappa = cohen_kappa(labels_a, labels_b)
    raw = sum(1 for a, b in zip(labels_a, labels_b) if a == b) / len(shared)
    return {
        "status": "computed",
        "required_annotators": REQUIRED_ANNOTATORS,
        "provided": len(paths),
        "n_items": len(shared),
        "cohen_kappa": kappa,
        "raw_agreement": raw,
        "extra_annotators_ignored": len(paths) - REQUIRED_ANNOTATORS,
    }


# --------------------------------------------------------------------------- #
# Calibration run
# --------------------------------------------------------------------------- #


@dataclass
class CalibrationResult:
    run_date: str
    policy_version: str
    judge_fingerprint: str
    judge_models: tuple[str, ...]
    coverage: dict
    rows: list[dict]
    confusion_overall: dict
    confusion_by_claim_type: dict
    false_support: dict
    agreement_overall: dict
    agreement_by_adversarial: dict
    inter_annotator: dict
    provider_invoked: bool

    def run_metadata(self) -> dict:
        """The fields drift is measured against."""
        return {
            "run_date": self.run_date,
            "policy_version": self.policy_version,
            "judge_fingerprint": self.judge_fingerprint,
            "judge_models": list(self.judge_models),
        }

    def to_records(self) -> list[dict]:
        """One meta record followed by one record per predicted pair (jsonl)."""
        meta = {
            "record_type": "calibration_run",
            "run_date": self.run_date,
            "policy_version": self.policy_version,
            "judge_fingerprint": self.judge_fingerprint,
            "judge_models": list(self.judge_models),
            "provider_invoked": self.provider_invoked,
            "n_pairs": self.coverage["n_pairs"],
            "coverage": self.coverage,
            "false_support": self.false_support,
            "agreement_overall": self.agreement_overall,
            "agreement_by_adversarial": self.agreement_by_adversarial,
            "confusion_overall": self.confusion_overall,
            "confusion_by_claim_type": self.confusion_by_claim_type,
            "inter_annotator": self.inter_annotator,
        }
        records = [meta]
        for r in self.rows:
            records.append({"record_type": "prediction", **r})
        return records


def run_calibration(
    pairs: list[LabeledPair],
    predict: PredictFn | None = None,
    *,
    judge_fingerprint: str | None = None,
    judge_models: Iterable[str] | None = None,
    policy_version: str = ENTAILMENT_POLICY_VERSION,
    annotator_paths: list[Path | str] | None = None,
    run_date: str | None = None,
) -> CalibrationResult:
    """Run the judge over the labeled set and compute all calibration metrics.

    ``predict`` maps a :class:`LabeledPair` to a predicted verdict string. When
    omitted, the real J1.1 judge is used via :class:`JudgeRunner` (which requires
    a configured provider). Tests inject a deterministic ``predict`` and an
    explicit ``judge_fingerprint`` so exact matrix cells are assertable.
    """
    runner: JudgeRunner | None = None
    if predict is None:
        runner = JudgeRunner()
        predict = runner.predict

    rows: list[dict] = []
    for pair in pairs:
        predicted = predict(pair)
        rows.append(
            {
                "pair_id": pair.pair_id,
                "claim_type": pair.claim_type,
                "category": pair.category,
                "adversarial_type": pair.adversarial_type,
                "gold": pair.gold_verdict,
                "predicted": predicted,
                "correct": predicted == pair.gold_verdict,
            }
        )

    # Fingerprint + models: prefer what the real runner observed; else the
    # explicitly injected values (tests); else a neutral placeholder.
    if runner is not None:
        fingerprint = runner.fingerprint()
        models = tuple(sorted(runner.models))
        provider_invoked = bool(runner.fingerprints)
    else:
        fingerprint = judge_fingerprint or "injected-predictor"
        models = tuple(judge_models or ())
        provider_invoked = judge_fingerprint is not None

    by_claim_type: dict[str, dict] = {}
    for claim_type in sorted({r["claim_type"] for r in rows}):
        subset = [(r["gold"], r["predicted"]) for r in rows if r["claim_type"] == claim_type]
        by_claim_type[claim_type] = confusion_matrix(subset)

    agreement_by_adv: dict[str, dict] = {}
    for adv in ADVERSARIAL_TYPES:
        subset = [r for r in rows if r["adversarial_type"] == adv]
        if subset:
            agreement_by_adv[adv] = _agreement(subset)

    return CalibrationResult(
        run_date=run_date or _dt.date.today().isoformat(),
        policy_version=policy_version,
        judge_fingerprint=fingerprint,
        judge_models=models,
        coverage=validate_coverage(pairs),
        rows=rows,
        confusion_overall=confusion_matrix([(r["gold"], r["predicted"]) for r in rows]),
        confusion_by_claim_type=by_claim_type,
        false_support=false_support(rows),
        agreement_overall=_agreement(rows),
        agreement_by_adversarial=agreement_by_adv,
        inter_annotator=inter_annotator_agreement(annotator_paths),
        provider_invoked=provider_invoked,
    )


# --------------------------------------------------------------------------- #
# Drift
# --------------------------------------------------------------------------- #


def detect_drift(previous: dict, current: dict) -> dict:
    """Flag model/prompt drift between two run-metadata dicts.

    Drift is any change to ``policy_version`` or ``judge_fingerprint``: the two
    runs are no longer comparable, and any calibration conclusion carried across
    the boundary is stale. Accepts :meth:`CalibrationResult.run_metadata` dicts.
    """
    changes: list[dict] = []
    for field_name in ("policy_version", "judge_fingerprint"):
        prev_val = previous.get(field_name)
        curr_val = current.get(field_name)
        if prev_val != curr_val:
            changes.append({"field": field_name, "previous": prev_val, "current": curr_val})
    return {
        "drifted": bool(changes),
        "changes": changes,
        "message": (
            "DRIFT: judge fingerprint or policy changed between runs; prior "
            "calibration numbers no longer apply."
            if changes
            else "no drift: fingerprint and policy version unchanged."
        ),
    }


# --------------------------------------------------------------------------- #
# Report artifacts
# --------------------------------------------------------------------------- #


def _find_previous_run(out_dir: Path, current_name: str) -> Path | None:
    if not out_dir.exists():
        return None
    prior = sorted(
        p for p in out_dir.glob("entailment-calibration-*.jsonl") if p.name != current_name
    )
    return prior[-1] if prior else None


def _load_run_metadata(path: Path) -> dict | None:
    try:
        first = path.read_text(encoding="utf-8").splitlines()[0]
        meta = json.loads(first)
    except (OSError, IndexError, json.JSONDecodeError):
        return None
    if meta.get("record_type") != "calibration_run":
        return None
    return {
        "run_date": meta.get("run_date"),
        "policy_version": meta.get("policy_version"),
        "judge_fingerprint": meta.get("judge_fingerprint"),
        "judge_models": meta.get("judge_models") or [],
    }


def write_report(
    result: CalibrationResult,
    out_dir: Path | str = EVAL_RUNS_DIR,
    *,
    date: str | None = None,
) -> Path:
    """Write the dated jsonl artifact (+ a human-readable ``.md`` sibling).

    Mirrors the ``data/eval_runs/<date>.jsonl`` convention. Returns the jsonl
    path. If a prior calibration run exists in ``out_dir`` a drift check against
    it is embedded in the summary.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = (date or result.run_date).replace("-", "")
    jsonl_path = out_dir / f"entailment-calibration-{stamp}.jsonl"

    prev = _find_previous_run(out_dir, jsonl_path.name)
    drift = None
    if prev is not None:
        prev_meta = _load_run_metadata(prev)
        if prev_meta is not None:
            drift = detect_drift(prev_meta, result.run_metadata())

    records = result.to_records()
    if drift is not None:
        records[0]["drift_vs_previous"] = {"previous_run": prev.name, **drift}
    jsonl_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    md_path = out_dir / f"entailment-calibration-{stamp}.md"
    md_path.write_text(format_summary(result, drift=drift), encoding="utf-8")
    return jsonl_path


def format_summary(result: CalibrationResult, *, drift: dict | None = None) -> str:
    """Human-readable summary. False-support rate is reported first and loudest."""
    fs = result.false_support
    lines: list[str] = []
    lines.append(f"# Entailment judge calibration — {result.run_date}")
    lines.append("")
    lines.append(f"- policy version: `{result.policy_version}`")
    lines.append(f"- judge fingerprint: `{result.judge_fingerprint}`")
    lines.append(f"- provider invoked: {result.provider_invoked}")
    if result.judge_models:
        lines.append(f"- judge models: {', '.join(result.judge_models)}")
    lines.append(f"- pairs judged: {result.coverage['n_pairs']}")
    lines.append("")
    lines.append("## SAFETY METRIC — false-support rate")
    lines.append("")
    lines.append(
        f"**false-support rate: {fs['false_support_rate']:.3f}** "
        f"({fs['n_false_support']} of {fs['n_gold_negative']} gold-negative cases "
        "were called supported/partial)."
    )
    if fs["offending_pair_ids"]:
        lines.append(f"- offending pairs: {', '.join(fs['offending_pair_ids'])}")
    lines.append("")
    ao = result.agreement_overall
    lines.append("## Agreement vs gold")
    lines.append("")
    lines.append(
        f"- overall: {ao['agreement']:.3f} ({ao['n_correct']}/{ao['n']}) — "
        "a single headline number is insufficient; see per-category below."
    )
    for adv, agg in sorted(result.agreement_by_adversarial.items()):
        lines.append(f"- {adv}: {agg['agreement']:.3f} ({agg['n_correct']}/{agg['n']})")
    lines.append("")
    lines.append("## Confusion matrix (overall) — rows=gold, cols=predicted")
    lines.append("")
    header = "| gold \\ pred | " + " | ".join(VERDICTS) + " |"
    lines.append(header)
    lines.append("|" + "---|" * (len(VERDICTS) + 1))
    for gold in VERDICTS:
        cells = " | ".join(str(result.confusion_overall[gold][p]) for p in VERDICTS)
        lines.append(f"| {gold} | {cells} |")
    lines.append("")
    lines.append("## Inter-annotator agreement (Cohen's kappa)")
    lines.append("")
    ia = result.inter_annotator
    if ia.get("status") == "computed":
        lines.append(
            f"- Cohen's kappa: {ia['cohen_kappa']:.3f} over {ia['n_items']} items "
            f"(raw agreement {ia['raw_agreement']:.3f})."
        )
    else:
        lines.append(f"- {ia.get('message')}")
    lines.append("")
    lines.append("## Drift vs previous run")
    lines.append("")
    if drift is None:
        lines.append("- no previous calibration run found for comparison.")
    else:
        lines.append(f"- {drift['message']}")
        for ch in drift["changes"]:
            lines.append(f"  - `{ch['field']}`: `{ch['previous']}` -> `{ch['current']}`")
    lines.append("")
    if not result.provider_invoked:
        lines.append(
            "> NOTE: no real judge provider was invoked in this run, so the "
            "false-support number above reflects an injected/stub predictor, not "
            "a calibrated model. A real-provider run is PENDING (see CALIBRATION.md)."
        )
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI (module entrypoint only — deliberately NOT a kb.py subcommand)
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m kops.judge_calibration",
        description=(
            "Calibrate the entailment judge against a hand-authored labeled set. "
            "Reports false-support rate, confusion matrix by claim type, per-category "
            "agreement, drift, and inter-annotator kappa (PENDING without annotators)."
        ),
    )
    parser.add_argument(
        "--labeled-set", default=str(DEFAULT_LABELED_SET), help="Path to the calibration JSONL."
    )
    parser.add_argument(
        "--annotator",
        action="append",
        default=[],
        help="Human annotator label file (repeatable). Two required for kappa.",
    )
    parser.add_argument("--agent", help="Judge provider (default: KB_JUDGE_AGENT).")
    parser.add_argument("--model", help="Judge model.")
    parser.add_argument("--out-dir", default=str(EVAL_RUNS_DIR), help="Report output directory.")
    parser.add_argument(
        "--coverage-only",
        action="store_true",
        help="Only report labeled-set coverage; do not invoke the judge.",
    )
    parser.add_argument("--no-write", action="store_true", help="Do not write the report artifact.")
    args = parser.parse_args(argv)

    pairs = load_labeled_set(args.labeled_set)

    if args.coverage_only:
        print(json.dumps(validate_coverage(pairs), indent=2, ensure_ascii=False))
        return 0

    runner = JudgeRunner(agent=args.agent, model=args.model)
    result = run_calibration(pairs, runner.predict, annotator_paths=args.annotator)
    # Backfill runner-derived fingerprint/models (run_calibration only does this
    # when it constructs its own runner).
    result.judge_fingerprint = runner.fingerprint()
    result.judge_models = tuple(sorted(runner.models))
    result.provider_invoked = bool(runner.fingerprints)

    if not args.no_write:
        path = write_report(result, args.out_dir)
        print(f"wrote {path}")
    print(format_summary(result))
    return 0


__all__ = [
    "ADVERSARIAL_TYPES",
    "SUPPORTIVE_VERDICTS",
    "NON_SUPPORTIVE_VERDICTS",
    "REQUIRED_ANNOTATORS",
    "DECISION_GATE_MIN_PAIRS",
    "DEFAULT_LABELED_SET",
    "LabeledPair",
    "CalibrationResult",
    "JudgeRunner",
    "load_labeled_set",
    "validate_coverage",
    "confusion_matrix",
    "false_support",
    "cohen_kappa",
    "load_annotations",
    "inter_annotator_agreement",
    "run_calibration",
    "detect_drift",
    "write_report",
    "format_summary",
]


if __name__ == "__main__":
    sys.exit(main())
