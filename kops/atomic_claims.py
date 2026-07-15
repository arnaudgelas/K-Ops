"""Enforce atomic claims (M1 task D1.2).

A claim can only be judged for entailment if it asserts exactly **one**
independently verifiable proposition. This module is an *additive* layer over
the claim registry and the canonical evidence objects (task D1.1): it detects
**compound** claims with deterministic, explainable heuristics and, where it is
safe, decomposes them into candidate atomic sub-claims that carry provenance
back to their parent ``clm-`` id.

It builds ON :mod:`kops.evidence_model` (it does not fork it):

* sub-claims are :class:`~kops.evidence_model.AtomicClaim`-shaped registry
  dicts, convertible via :func:`to_atomic_claim`;
* the parent -> child link reuses the ``derived_from`` relation from
  :data:`~kops.evidence_model.EDGE_RELATIONS`;
* stable sub-claim ids are minted with
  :func:`~kops.evidence_model.stable_id` (``clm-`` + 10-char SHA-256).

Four compound categories are flagged (roadmap D1.2):

1. ``multiple-predicates`` — two or more independent finite clauses joined by a
   coordinating conjunction or a semicolon;
2. ``mixed-temporal`` — two or more distinct temporal references;
3. ``comparison-plus-causal`` — a comparison cue together with a causal cue;
4. ``recommendation-plus-fact`` — a recommendation cue together with a
   supporting factual clause.

Decomposition is **conservative**: when the boundaries cannot be split into
clean, verb-bearing fragments, the claim is flagged-for-review
(``needs_review``) rather than silently mangled.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from kops.evidence_model import EDGE_RELATIONS, AtomicClaim, stable_id

# --------------------------------------------------------------------------- #
# Category constants
# --------------------------------------------------------------------------- #

MULTI_PREDICATE = "multiple-predicates"
MIXED_TEMPORAL = "mixed-temporal"
COMPARISON_CAUSAL = "comparison-plus-causal"
RECOMMENDATION_FACT = "recommendation-plus-fact"

CATEGORIES: tuple[str, ...] = (
    MULTI_PREDICATE,
    MIXED_TEMPORAL,
    COMPARISON_CAUSAL,
    RECOMMENDATION_FACT,
)

# Parent -> child edge for a decomposed sub-claim. Reuses the evidence-model
# edge vocabulary rather than inventing a parallel relation name.
PARENT_CHILD_RELATION = "derived_from"
assert PARENT_CHILD_RELATION in EDGE_RELATIONS

# --------------------------------------------------------------------------- #
# Lexicons (deterministic, explainable — no NLP deps)
# --------------------------------------------------------------------------- #

# Finite verbs / auxiliaries used to decide whether a fragment is an
# independent clause. Base and 3rd-person-singular forms are both listed. This
# set is intentionally curated (not inferred) so detection stays precise and
# errs toward *not* flagging when a verb is unrecognised.
_AUX_VERBS = {
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "am",
    "has",
    "have",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "shall",
    "should",
    "can",
    "could",
    "may",
    "might",
    "must",
    "ought",
}
_LEXICAL_VERBS = {
    "write",
    "writes",
    "check",
    "checks",
    "use",
    "uses",
    "provide",
    "provides",
    "require",
    "requires",
    "cause",
    "causes",
    "lead",
    "leads",
    "result",
    "results",
    "become",
    "becomes",
    "remain",
    "remains",
    "include",
    "includes",
    "contain",
    "contains",
    "enable",
    "enables",
    "produce",
    "produces",
    "improve",
    "improves",
    "reduce",
    "reduces",
    "increase",
    "increases",
    "decrease",
    "decreases",
    "support",
    "supports",
    "outperform",
    "outperforms",
    "exceed",
    "exceeds",
    "define",
    "defines",
    "map",
    "maps",
    "split",
    "splits",
    "flag",
    "flags",
    "catch",
    "catches",
    "adopt",
    "adopts",
    "run",
    "runs",
    "process",
    "processes",
    "return",
    "returns",
    "reach",
    "reaches",
    "cache",
    "caches",
    "detect",
    "detects",
    "handle",
    "handles",
    "generate",
    "generates",
    "ingest",
    "ingests",
    "compile",
    "compiles",
    "lint",
    "lints",
    "verify",
    "verifies",
    "cover",
    "covers",
    "show",
    "shows",
    "report",
    "reports",
    "make",
    "makes",
    "take",
    "takes",
    "give",
    "gives",
    "work",
    "works",
    "help",
    "helps",
    "allow",
    "allows",
    "prevent",
    "prevents",
    "ensure",
    "ensures",
    "track",
    "tracks",
    "store",
    "stores",
    "load",
    "loads",
    "build",
    "builds",
    "add",
    "adds",
    "remove",
    "removes",
    "update",
    "updates",
    "occur",
    "occurs",
    "exist",
    "exists",
    "apply",
    "applies",
    "drive",
    "drives",
    "meet",
    "meets",
    "fail",
    "fails",
    "pass",
    "passes",
    "count",
    "counts",
    "measure",
    "measures",
    "rise",
    "rises",
    "grow",
    "grows",
    "fall",
    "falls",
    "runs",
}
_VERBS = _AUX_VERBS | _LEXICAL_VERBS

# Coordinating separators between independent clauses. ``\b`` guards mean words
# like "understand" or "command" never match the "and" alternative.
_CLAUSE_SEP_RE = re.compile(r"\s*;\s*|\s*,?\s+(?:and|but|while|whereas|yet)\s+", re.IGNORECASE)

# Temporal references. A single reference is fine; two *distinct* references are
# a mixed temporal scope.
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_TEMPORAL_WORDS = {
    "now",
    "currently",
    "today",
    "yesterday",
    "tomorrow",
    "previously",
    "formerly",
    "recently",
    "then",
    "later",
    "earlier",
    "ago",
    "nowadays",
    "historically",
    "initially",
    "originally",
    "subsequently",
    "since",
}
_MONTHS = {
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
}

# Comparison cues.
_COMPARISON_WORDS = {
    "more",
    "less",
    "fewer",
    "greater",
    "higher",
    "lower",
    "faster",
    "slower",
    "better",
    "worse",
    "larger",
    "smaller",
    "stronger",
    "weaker",
    "cheaper",
    "costlier",
    "bigger",
    "wider",
    "narrower",
}
_COMPARISON_PHRASE_RE = re.compile(
    r"\bcompared (?:to|with)\b|\brelative to\b|\bversus\b|\bvs\.?\b|"
    r"\boutperforms?\b|\boutpaces?\b|\bexceeds?\b",
    re.IGNORECASE,
)
# "-er than" comparatives, excluding non-comparative false friends.
_ER_THAN_RE = re.compile(r"\b(\w+er)\s+than\b", re.IGNORECASE)
_ER_THAN_BLOCK = {"other", "rather", "further", "another", "either", "neither"}

# Causal cues.
_CAUSAL_PHRASE_RE = re.compile(
    r"\bbecause(?:\s+of)?\b|\bdue to\b|\bowing to\b|\bas a result(?:\s+of)?\b|"
    r"\btherefore\b|\bthus\b|\bhence\b|\bconsequently\b|\bleads? to\b|"
    r"\bresults? in\b|\bcaused by\b|\bso that\b|\bresulting in\b",
    re.IGNORECASE,
)

# Recommendation cues.
_RECOMMEND_RE = re.compile(
    r"\bshould\b|\bmust\b|\bought to\b|\bshall\b|\brecommend(?:s|ed)?\b|"
    r"\badvise[sd]?\b|\bsuggest(?:s|ed)?\b|\bbest practice\b",
    re.IGNORECASE,
)

# Causal connective usable as a *split boundary* (cause follows the connective).
# "since" is deliberately excluded — it is ambiguous with the temporal sense.
_CAUSAL_SPLIT_RE = re.compile(
    r"\s+(?:because(?:\s+of)?|due to|owing to|as a result of)\s+", re.IGNORECASE
)


# --------------------------------------------------------------------------- #
# Tokenisation / clause helpers
# --------------------------------------------------------------------------- #


def _tokens(fragment: str) -> list[str]:
    out: list[str] = []
    for word in fragment.split():
        cleaned = re.sub(r"[^\w%$-]", "", word).lower()
        if cleaned:
            out.append(cleaned)
    return out


def _first_verb_index(tokens: list[str]) -> int | None:
    for i, tok in enumerate(tokens):
        if tok in _VERBS:
            return i
    return None


def _is_independent_clause(fragment: str) -> bool:
    """A fragment is an independent clause if a finite verb follows a subject.

    The verb must appear after the first token (so a subject precedes it). This
    also tolerates verb/noun homographs used as the subject — e.g. "Ingest" and
    "compile" in "Ingest writes evidence; compile writes summaries" — because
    the *real* finite verb ("writes") still sits at index >= 1.
    """
    tokens = _tokens(fragment)
    if len(tokens) < 2:
        return False
    return any(tok in _VERBS for tok in tokens[1:])


def _has_verb(fragment: str) -> bool:
    return _first_verb_index(_tokens(fragment)) is not None


def _split_clauses(text: str) -> list[str]:
    return [frag.strip() for frag in _CLAUSE_SEP_RE.split(text) if frag.strip()]


def _independent_clauses(text: str) -> list[str]:
    """Return the coordinate fragments *iff* every one is an independent clause.

    Returning ``[]`` when any fragment is a bare noun-phrase is the core
    false-positive guard: ``"compile writes summaries and concept pages"`` has a
    non-clausal ``"concept pages"`` fragment and so is *not* multi-predicate.
    """
    fragments = _split_clauses(text)
    if len(fragments) >= 2 and all(_is_independent_clause(f) for f in fragments):
        return fragments
    return []


def _temporal_references(text: str) -> list[str]:
    refs: list[str] = []
    refs.extend(_YEAR_RE.findall(text))
    lowered = text.lower()
    for word in _TEMPORAL_WORDS | _MONTHS:
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            refs.append(word)
    # Distinct references, order-stable.
    seen: set[str] = set()
    unique: list[str] = []
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            unique.append(ref)
    return unique


def _comparison_cues(text: str) -> list[str]:
    cues: list[str] = []
    lowered = text.lower()
    for word in _COMPARISON_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            cues.append(word)
    cues.extend(m.group(0) for m in _COMPARISON_PHRASE_RE.finditer(text))
    for m in _ER_THAN_RE.finditer(text):
        if m.group(1).lower() not in _ER_THAN_BLOCK:
            cues.append(m.group(0))
    return cues


def _causal_cues(text: str) -> list[str]:
    return [m.group(0).strip() for m in _CAUSAL_PHRASE_RE.finditer(text)]


def _recommendation_cues(text: str) -> list[str]:
    return [m.group(0) for m in _RECOMMEND_RE.finditer(text)]


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #


def detect_compound(text: str) -> list[dict[str, str]]:
    """Return the explainable reason(s) a claim is compound (empty => atomic)."""
    text = (text or "").strip()
    reasons: list[dict[str, str]] = []
    if not text:
        return reasons

    clauses = _independent_clauses(text)
    if clauses:
        reasons.append(
            {
                "category": MULTI_PREDICATE,
                "detail": f"{len(clauses)} independent clauses: "
                + " | ".join(repr(c) for c in clauses),
            }
        )

    temporal = _temporal_references(text)
    if len(temporal) >= 2:
        reasons.append(
            {
                "category": MIXED_TEMPORAL,
                "detail": "temporal references: " + ", ".join(temporal),
            }
        )

    comparison = _comparison_cues(text)
    causal = _causal_cues(text)
    if comparison and causal:
        reasons.append(
            {
                "category": COMPARISON_CAUSAL,
                "detail": f"comparison cue {comparison[0]!r} + causal cue {causal[0]!r}",
            }
        )

    recommend = _recommendation_cues(text)
    # A recommendation is compound only when it also carries a supporting fact:
    # either an explicit causal clause or a second independent clause. A bare
    # recommendation ("teams should run lint after edits") is atomic.
    if recommend and (causal or clauses):
        support = f"causal cue {causal[0]!r}" if causal else "a second independent clause"
        reasons.append(
            {
                "category": RECOMMENDATION_FACT,
                "detail": f"recommendation cue {recommend[0]!r} + supporting fact via {support}",
            }
        )

    return reasons


# --------------------------------------------------------------------------- #
# Decomposition
# --------------------------------------------------------------------------- #


def _clean_fragment(fragment: str) -> str | None:
    """Normalise one candidate sub-claim, or ``None`` if it looks mangled."""
    text = fragment.strip().strip(",;:").strip()
    # Strip a leading dangling conjunction if one survived the split.
    text = re.sub(r"^(?:and|but|while|whereas|yet|because|so)\s+", "", text, flags=re.IGNORECASE)
    text = text.strip()
    if len(_tokens(text)) < 2 or not _has_verb(text):
        return None
    text = text[0].upper() + text[1:]
    if text[-1] not in ".!?":
        text += "."
    return text


def _split_on_causal(text: str) -> tuple[str, str] | None:
    parts = _CAUSAL_SPLIT_RE.split(text, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return parts[0].strip(), parts[1].strip()
    return None


def decompose_text(text: str, categories: set[str]) -> list[str]:
    """Best-effort deterministic split into atomic fragments.

    Returns ``[]`` when the claim is compound but cannot be split cleanly, so
    the caller can flag it for human review instead of emitting mangled text.
    """
    fragments: list[str] | None = None

    if MULTI_PREDICATE in categories:
        clauses = _independent_clauses(text)
        if clauses:
            fragments = clauses

    if fragments is None and (COMPARISON_CAUSAL in categories or RECOMMENDATION_FACT in categories):
        causal_split = _split_on_causal(text)
        if causal_split:
            fragments = list(causal_split)
        else:
            clauses = _independent_clauses(text)
            if clauses:
                fragments = clauses

    if not fragments:
        return []

    cleaned = [_clean_fragment(f) for f in fragments]
    if any(c is None for c in cleaned):
        return []
    return [c for c in cleaned if c is not None]


# --------------------------------------------------------------------------- #
# Claim I/O + provenance
# --------------------------------------------------------------------------- #


def _unpack(claim: AtomicClaim | dict) -> dict[str, Any]:
    if isinstance(claim, AtomicClaim):
        anchors = [
            {
                "source_id": s.source_id,
                "quote": s.quote,
                "anchor": s.anchor,
                "page": s.page,
                "section": s.section,
                "segment_id": s.segment_id,
            }
            for s in claim.spans
        ]
        return {
            "claim_id": claim.claim_id,
            "claim_text": claim.claim_text,
            "concept": claim.concept,
            "source_ids": list(claim.source_ids),
            "source_anchors": anchors,
            "evidence_status": claim.evidence_status,
            "admission_status": claim.admission_status,
        }
    return {
        "claim_id": str(claim.get("claim_id") or claim.get("id") or ""),
        "claim_text": str(claim.get("claim_text") or claim.get("text") or ""),
        "concept": claim.get("concept"),
        "source_ids": list(claim.get("source_ids") or ()),
        "source_anchors": list(claim.get("source_anchors") or ()),
        "evidence_status": claim.get("evidence_status"),
        "admission_status": claim.get("admission_status"),
    }


def _build_subclaims(parent: dict[str, Any], texts: list[str]) -> list[dict[str, Any]]:
    concept = parent["concept"] or ""
    parent_id = parent["claim_id"]
    subs: list[dict[str, Any]] = []
    for idx, text in enumerate(texts, start=1):
        cid = stable_id("clm", concept, text)
        subs.append(
            {
                "id": cid,
                "claim_id": cid,
                "text": text,
                "claim_text": text,
                "concept": parent["concept"],
                "source_ids": list(parent["source_ids"]),
                "source_anchors": list(parent["source_anchors"]),
                "evidence_status": parent["evidence_status"],
                "admission_status": parent["admission_status"],
                # Provenance back to the compound parent (evidence-model edge).
                "parent_claim_id": parent_id,
                "derived_from": parent_id,
                "relation": PARENT_CHILD_RELATION,
                "sub_index": idx,
            }
        )
    return subs


def to_atomic_claim(sub_claim: dict[str, Any]) -> AtomicClaim:
    """Convert a decomposed sub-claim dict to a typed :class:`AtomicClaim`."""
    return AtomicClaim.from_registry_dict(sub_claim)


def analyze_claim(claim: AtomicClaim | dict) -> dict[str, Any]:
    """Classify one claim as atomic/compound and (if safe) decompose it."""
    parent = _unpack(claim)
    reasons = detect_compound(parent["claim_text"])
    atomic = not reasons

    sub_claims: list[dict[str, Any]] = []
    needs_review = False
    if reasons:
        categories = {r["category"] for r in reasons}
        fragments = decompose_text(parent["claim_text"], categories)
        if fragments:
            sub_claims = _build_subclaims(parent, fragments)
        else:
            needs_review = True

    return {
        "claim_id": parent["claim_id"],
        "claim_text": parent["claim_text"],
        "concept": parent["concept"],
        "atomic": atomic,
        "reasons": reasons,
        "sub_claims": sub_claims,
        "needs_review": needs_review,
    }


def analyze_claims(claims: list[AtomicClaim | dict]) -> list[dict[str, Any]]:
    return [analyze_claim(c) for c in claims]


def load_claims_file(path: str | Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return data.get("claims", [])


def _default_claims_path() -> Path:
    from kops.claim_registry import CLAIMS_PATH

    return CLAIMS_PATH


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def run(
    check: bool = False,
    dry_run: bool = False,
    claims_path: str | Path | None = None,
    claims: list[AtomicClaim | dict] | None = None,
    as_json: bool = False,
) -> list[dict[str, Any]]:
    if claims is None:
        path = Path(claims_path) if claims_path else _default_claims_path()
        if not path.exists():
            print(f"No claims file at {path}")
            if check:
                return []
            return []
        claims = load_claims_file(path)

    results = analyze_claims(claims)
    compounds = [r for r in results if not r["atomic"]]

    if as_json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return results

    if check:
        if compounds:
            for r in compounds:
                cats = ", ".join(sorted({x["category"] for x in r["reasons"]}))
                print(f"  {r['claim_id']} [{cats}]: {r['claim_text']}")
            print(f"{len(compounds)} compound claim(s) must be decomposed before entailment.")
            sys.exit(1)
        print(f"All {len(results)} claim(s) are atomic.")
        return results

    n_review = sum(1 for r in results if r["needs_review"])
    n_split = sum(len(r["sub_claims"]) for r in results)
    if dry_run:
        print("[DRY-RUN] atomic-claims analysis (no files written)")
    print(
        f"{len(results)} claim(s): {len(compounds)} compound "
        f"({n_split} candidate sub-claim(s), {n_review} flagged for review)."
    )
    for r in compounds:
        cats = ", ".join(sorted({x["category"] for x in r["reasons"]}))
        marker = "review" if r["needs_review"] else f"{len(r['sub_claims'])} sub-claim(s)"
        print(f"  {r['claim_id']} [{cats}] -> {marker}")
    return results


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Detect and decompose compound claims into atomic propositions."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if any compound (non-atomic) claims exist.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report without writing files.")
    parser.add_argument("--claims", help="Path to a claims.json (defaults to data/claims.json).")
    parser.add_argument("--json", action="store_true", help="Emit full JSON analysis.")
    args = parser.parse_args()
    run(check=args.check, dry_run=args.dry_run, claims_path=args.claims, as_json=args.json)


__all__ = [
    "CATEGORIES",
    "MULTI_PREDICATE",
    "MIXED_TEMPORAL",
    "COMPARISON_CAUSAL",
    "RECOMMENDATION_FACT",
    "PARENT_CHILD_RELATION",
    "detect_compound",
    "decompose_text",
    "analyze_claim",
    "analyze_claims",
    "to_atomic_claim",
    "load_claims_file",
    "run",
]


if __name__ == "__main__":
    main()
