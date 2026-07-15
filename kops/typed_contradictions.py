"""Typed contradiction records (M4 task L4.1).

Contradictions in the vault are not all equal: an immaterial terminology
mismatch (two notes using different words for the same thing) should not gate a
decision, while a material direct conflict must. This module gives every
contradiction record a *type* and the governance fields needed to reason about
it, using a **deterministic** heuristic over the record's ``open_question`` text
plus its participating claims and sources.

Design
------
* :class:`Contradiction` — a frozen, ``SCHEMA_VERSION``-stamped dataclass that
  carries the eight original envelope fields (``id``, ``concept``,
  ``concept_path``, ``open_question``, ``documented``, ``claim_ids``,
  ``source_ids``, ``created_at``; plus optional ``source`` for maintenance
  records) alongside the new typed fields. ``to_dict`` merges both so it can
  replace the plain record in ``data/contradictions.json`` additively.
* :func:`classify_contradiction` — pure ``record -> Contradiction`` classifier.
  Optional ``claims_by_id`` / ``sources_by_id`` lookups let it inspect the
  participating claims/sources (e.g. a synthetic source) without importing the
  registries.
* :func:`material_contradiction_ids` — the dependency-light pure helper the
  tier-policy integration consults: the set of claim ids that participate in an
  **unresolved, material** contradiction.

Determinism
-----------
No timestamps, randomness, or dict-ordering sensitivity enters classification,
so ``contradiction_registry.run(check=True)`` stays stable across runs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, ClassVar

from kops.evidence_model import SCHEMA_VERSION

# --------------------------------------------------------------------------- #
# The 9 canonical contradiction types
# --------------------------------------------------------------------------- #

CONTRADICTION_TYPES: tuple[str, ...] = (
    "direct-conflict",
    "temporal-supersession",
    "scope-mismatch",
    "terminology-mismatch",
    "methodological-disagreement",
    "evidence-quality-disagreement",
    "interpretation-disagreement",
    "synthetic-or-derivative-contamination",
    "extraction-error",
)

# Materiality is type-driven. Immaterial types describe reconcilable or
# mechanical disagreements that do not, on their own, gate a decision.
IMMATERIAL_TYPES: frozenset[str] = frozenset(
    {"terminology-mismatch", "extraction-error", "scope-mismatch"}
)
# Material types describe substantive disagreements that (on a decision-relevant
# record) force qualify/abstain.
MATERIAL_TYPES: frozenset[str] = frozenset(
    {
        "direct-conflict",
        "temporal-supersession",
        "evidence-quality-disagreement",
        "methodological-disagreement",
        "interpretation-disagreement",
        "synthetic-or-derivative-contamination",
    }
)

# --------------------------------------------------------------------------- #
# Deterministic cue vocabularies
# --------------------------------------------------------------------------- #

_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_DATE_RANGE_RE = re.compile(r"\b(?:19|20)\d{2}\b\s*(?:-|–|—|to|through|until)\s*\b(?:19|20)\d{2}\b")

_SYNTHETIC_CUES = (
    "synthetic",
    "model-generated",
    "model generated",
    "ai-generated",
    "ai generated",
    "llm-generated",
    "hallucin",
    "derivative",
    "derived from a model",
    "generated report",
    "imported model report",
)
_EXTRACTION_CUES = (
    "extraction error",
    "extraction artifact",
    "mis-extract",
    "misextract",
    "misquot",
    "quote does not",
    "quote not found",
    "does not appear in the source",
    "garbled",
    "ocr",
    "parsing error",
    "span mismatch",
    "wrong page",
    "citation does not match",
)
_TEMPORAL_CUES = (
    "supersede",
    "superseded",
    "replaced by",
    "no longer",
    "deprecat",
    "obsolet",
    "outdated",
    "out of date",
    "as of",
    "newer",
    "older",
    "updated",
    "revised",
    "since ",
    "version",
    "changed in",
    "prior to",
)
_SUPERSESSION_CUES = (
    "supersede",
    "superseded",
    "replaced by",
    "no longer",
    "deprecat",
    "obsolet",
    "obsoletes",
)
_METHOD_CUES = (
    "methodolog",
    "method ",
    "benchmark",
    "protocol",
    "procedure",
    "measured",
    "measurement",
    "experimental setup",
    "how it was tested",
    "how it was measured",
    "test harness",
)
_EVIDENCE_QUALITY_CUES = (
    "evidence quality",
    "weak evidence",
    "strong evidence",
    "unreliable",
    "unsupported",
    "reliability",
    "primary source",
    "secondary source",
    "poorly sourced",
    "well sourced",
    "low-quality source",
    "weaker source",
)
_TERM_CUES = (
    "terminolog",
    "term ",
    "the term",
    "definition",
    "defined as",
    "means the same",
    " means ",
    "same thing",
    "different name",
    "naming",
    "what we call",
    "refers to the same",
    "wording",
)
_SCOPE_CUES = (
    "scope",
    "only applies",
    "applies only",
    "in the context of",
    "specific to",
    "restricted to",
    "limited to",
    "edge case",
    "general case",
    "under conditions",
    "for the special case",
)
_INTERPRETATION_CUES = (
    "interpret",
    "interpretation",
    "reading of",
    "read differently",
    "understood as",
    "construe",
    "implies",
    "read as",
)


def _contains_any(text: str, cues: tuple[str, ...]) -> bool:
    return any(cue in text for cue in cues)


# --------------------------------------------------------------------------- #
# Structural signals over participating claims / sources
# --------------------------------------------------------------------------- #

_SYNTHETIC_STRENGTHS = frozenset({"model-generated", "synthetic", "stub", "model-report"})


def _has_synthetic_evidence(claims: list[dict], sources: list[dict]) -> bool:
    """True if any participating claim or source is synthetic/model-derived."""
    for claim in claims:
        if claim.get("synthetic_origin"):
            return True
    for source in sources:
        if source.get("synthetic_origin"):
            return True
        if source.get("derived_from"):
            return True
        strength = str(source.get("evidence_strength") or "").lower()
        if strength in _SYNTHETIC_STRENGTHS or "model-generated" in strength:
            return True
    return False


def _claim_text(claim: dict) -> str:
    return str(claim.get("claim_text") or claim.get("text") or "")


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


def _classify_type(open_question: str, claims: list[dict], sources: list[dict]) -> str:
    """Deterministic type heuristic. Checked in a fixed priority order.

    Priority (most specific / most severe first):
    synthetic-or-derivative-contamination, extraction-error,
    temporal-supersession, methodological-disagreement,
    evidence-quality-disagreement, terminology-mismatch, scope-mismatch,
    interpretation-disagreement, then default direct-conflict.
    """
    haystack = " ".join([open_question or "", *(_claim_text(c) for c in claims)]).lower()

    # 1. Contaminated evidence — structural signal wins, then text cue.
    if _has_synthetic_evidence(claims, sources) or _contains_any(haystack, _SYNTHETIC_CUES):
        return "synthetic-or-derivative-contamination"

    # 2. Mechanical extraction/OCR/quote anomalies.
    if _contains_any(haystack, _EXTRACTION_CUES):
        return "extraction-error"

    # 3. One claim supersedes another over time.
    if _DATE_RANGE_RE.search(haystack) or _contains_any(haystack, _TEMPORAL_CUES):
        return "temporal-supersession"

    # 4. Disagreement about how something was measured / benchmarked.
    if _contains_any(haystack, _METHOD_CUES):
        return "methodological-disagreement"

    # 5. Disagreement about the quality / reliability of the evidence.
    if _contains_any(haystack, _EVIDENCE_QUALITY_CUES):
        return "evidence-quality-disagreement"

    # 6. Same concept, different words / definitions.
    if _contains_any(haystack, _TERM_CUES):
        return "terminology-mismatch"

    # 7. Both true, but over different scopes / conditions.
    if _contains_any(haystack, _SCOPE_CUES):
        return "scope-mismatch"

    # 8. Same evidence, read differently.
    if _contains_any(haystack, _INTERPRETATION_CUES):
        return "interpretation-disagreement"

    # 9. Genuine head-to-head disagreement (also the ambiguous default).
    return "direct-conflict"


def _materiality(contradiction_type: str, decision_relevant: bool) -> str:
    """``material`` vs ``immaterial`` — type-driven, gated on decision relevance.

    Immaterial types are always immaterial. Material types are material only when
    the record is decision-relevant (has at least one participating claim or
    source); a material-type record with nothing attached cannot yet gate a
    decision and is treated as immaterial.
    """
    if contradiction_type in IMMATERIAL_TYPES:
        return "immaterial"
    if contradiction_type in MATERIAL_TYPES and decision_relevant:
        return "material"
    return "immaterial"


def _resolution_state(contradiction_type: str, open_question: str, claims: list[dict]) -> str:
    """``unresolved`` (default), ``resolved``, or ``superseded``.

    ``superseded`` is derived only for a temporal-supersession that carries a
    clear supersession cue (a newer claim explicitly supplants an older one).
    ``resolved`` is never auto-derived — it requires a recorded reviewer
    decision, kept out of the deterministic extraction path.
    """
    if contradiction_type == "temporal-supersession":
        text = " ".join([open_question or "", *(_claim_text(c) for c in claims)]).lower()
        if _contains_any(text, _SUPERSESSION_CUES):
            return "superseded"
    return "unresolved"


def _severity(contradiction_type: str, materiality: str) -> str:
    """Coarse ordinal severity: ``high`` | ``medium`` | ``low``."""
    if materiality == "immaterial":
        return "low"
    if contradiction_type in ("synthetic-or-derivative-contamination", "direct-conflict"):
        return "high"
    return "medium"


def _extract_time_interval(open_question: str) -> dict | None:
    """Best-effort ``{start,end}`` / ``{as_of}`` from year mentions; else ``None``."""
    text = open_question or ""
    range_match = _DATE_RANGE_RE.search(text)
    if range_match:
        years = _YEAR_RE.findall(range_match.group(0))
        if len(years) >= 2:
            lo, hi = sorted(years)[0], sorted(years)[-1]
            return {"start": lo, "end": hi}
    years = _YEAR_RE.findall(text)
    if len(years) >= 2:
        ordered = sorted(years)
        return {"start": ordered[0], "end": ordered[-1]}
    if len(years) == 1:
        return {"as_of": years[0]}
    return None


_SCOPE_PHRASE_RE = re.compile(
    r"(?:in the context of|only applies to|applies only to|specific to|"
    r"restricted to|limited to|scoped to)\s+([^.,;]{2,60})",
    re.IGNORECASE,
)


def _extract_scope(open_question: str) -> str | None:
    """Best-effort scope phrase (e.g. the text after ``in the context of``)."""
    match = _SCOPE_PHRASE_RE.search(open_question or "")
    if match:
        return " ".join(match.group(1).split())
    return None


def _supporting_evidence(claim_ids: list[str], source_ids: list[str]) -> list[dict]:
    """Typed references to participating claims/sources.

    Derived purely from the record's own ids so it is deterministic and free of
    external lookups. A content-hashed ``clm-`` id *is* the claim version (per
    the vault's claim-versioning convention), so it doubles as ``version``.
    """
    refs: list[dict] = []
    for cid in claim_ids:
        refs.append({"ref_type": "claim", "id": cid, "version": cid})
    for sid in source_ids:
        refs.append({"ref_type": "source", "id": sid})
    return refs


# --------------------------------------------------------------------------- #
# Contradiction dataclass
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Contradiction:
    """A typed, ``SCHEMA_VERSION``-stamped contradiction record.

    Carries the original envelope fields plus the L4.1 typed fields. ``to_dict``
    merges both so the result can replace the plain registry record additively
    (every original key is preserved).
    """

    OBJECT_TYPE: ClassVar[str] = "contradiction"

    # Original envelope fields (unchanged semantics).
    id: str
    concept: str
    concept_path: str
    open_question: str | None
    documented: bool
    claim_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    created_at: str = ""
    source: str | None = None  # only present on maintenance records

    # Typed L4.1 fields.
    contradiction_type: str = "direct-conflict"
    scope: str | None = None
    time_interval: dict | None = None
    severity: str = "medium"
    materiality: str = "material"
    resolution_state: str = "unresolved"
    supporting_evidence: list[dict] = field(default_factory=list)
    reviewer_decision: dict | None = None
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        data: dict[str, Any] = {
            "id": self.id,
            "concept": self.concept,
            "concept_path": self.concept_path,
            "open_question": self.open_question,
            "documented": self.documented,
            "claim_ids": list(self.claim_ids),
            "source_ids": list(self.source_ids),
            "created_at": self.created_at,
        }
        # Preserve the exact original shape: maintenance records carry ``source``
        # after ``created_at``; concept records never had the key.
        if self.source is not None:
            data["source"] = self.source
        data.update(
            {
                "contradiction_type": self.contradiction_type,
                "scope": self.scope,
                "time_interval": self.time_interval,
                "severity": self.severity,
                "materiality": self.materiality,
                "resolution_state": self.resolution_state,
                "supporting_evidence": self.supporting_evidence,
                "reviewer_decision": self.reviewer_decision,
                "schema_version": self.schema_version,
            }
        )
        return data

    @classmethod
    def from_dict(cls, data: dict) -> Contradiction:
        return cls(
            id=str(data.get("id") or ""),
            concept=str(data.get("concept") or ""),
            concept_path=str(data.get("concept_path") or ""),
            open_question=data.get("open_question"),
            documented=bool(data.get("documented")),
            claim_ids=tuple(str(c) for c in (data.get("claim_ids") or ())),
            source_ids=tuple(str(s) for s in (data.get("source_ids") or ())),
            created_at=str(data.get("created_at") or ""),
            source=data.get("source"),
            contradiction_type=str(data.get("contradiction_type") or "direct-conflict"),
            scope=data.get("scope"),
            time_interval=data.get("time_interval"),
            severity=str(data.get("severity") or "medium"),
            materiality=str(data.get("materiality") or "material"),
            resolution_state=str(data.get("resolution_state") or "unresolved"),
            supporting_evidence=list(data.get("supporting_evidence") or []),
            reviewer_decision=data.get("reviewer_decision"),
            schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
        )


def classify_contradiction(
    record: dict,
    claims_by_id: dict[str, dict] | None = None,
    sources_by_id: dict[str, dict] | None = None,
) -> Contradiction:
    """Classify a plain contradiction record into a typed :class:`Contradiction`.

    ``record`` is a registry record (the eight-key shape). Optional
    ``claims_by_id`` / ``sources_by_id`` let the classifier inspect participating
    claims/sources (for synthetic-contamination detection); when omitted the
    classifier degrades to text-only cues.
    """
    claims_by_id = claims_by_id or {}
    sources_by_id = sources_by_id or {}

    claim_ids = [str(c) for c in (record.get("claim_ids") or [])]
    source_ids = [str(s) for s in (record.get("source_ids") or [])]
    claims = [claims_by_id[c] for c in claim_ids if c in claims_by_id]
    sources = [sources_by_id[s] for s in source_ids if s in sources_by_id]
    open_question = record.get("open_question") or ""

    contradiction_type = _classify_type(open_question, claims, sources)
    decision_relevant = bool(claim_ids or source_ids)
    materiality = _materiality(contradiction_type, decision_relevant)
    resolution_state = _resolution_state(contradiction_type, open_question, claims)
    severity = _severity(contradiction_type, materiality)

    return Contradiction(
        id=str(record.get("id") or ""),
        concept=str(record.get("concept") or ""),
        concept_path=str(record.get("concept_path") or ""),
        open_question=record.get("open_question"),
        documented=bool(record.get("documented")),
        claim_ids=tuple(claim_ids),
        source_ids=tuple(source_ids),
        created_at=str(record.get("created_at") or ""),
        source=record.get("source"),
        contradiction_type=contradiction_type,
        scope=_extract_scope(open_question),
        time_interval=_extract_time_interval(open_question),
        severity=severity,
        materiality=materiality,
        resolution_state=resolution_state,
        supporting_evidence=_supporting_evidence(claim_ids, source_ids),
        reviewer_decision=None,
    )


def material_contradiction_ids(
    claims: Any,
    contradictions: list[dict] | None = None,
) -> set[str]:
    """Claim ids that participate in an **unresolved, material** contradiction.

    This is the pure helper the tier-policy integration consults to decide
    qualify/abstain. ``claims`` is an iterable of claim dicts (used both to scope
    the result to known claims and to detect synthetic origin). When
    ``contradictions`` is ``None`` the current registry is loaded lazily.
    """
    claims_by_id: dict[str, dict] = {}
    for claim in claims or []:
        cid = str(claim.get("claim_id") or claim.get("id") or "")
        if cid:
            claims_by_id[cid] = claim

    if contradictions is None:
        from kops.contradiction_registry import load_contradictions

        contradictions = load_contradictions()

    result: set[str] = set()
    for record in contradictions or []:
        typed = classify_contradiction(record, claims_by_id=claims_by_id)
        if typed.resolution_state != "unresolved" or typed.materiality != "material":
            continue
        for cid in record.get("claim_ids") or []:
            cid = str(cid)
            if not claims_by_id or cid in claims_by_id:
                result.add(cid)
    return result


__all__ = [
    "CONTRADICTION_TYPES",
    "IMMATERIAL_TYPES",
    "MATERIAL_TYPES",
    "Contradiction",
    "classify_contradiction",
    "material_contradiction_ids",
]
