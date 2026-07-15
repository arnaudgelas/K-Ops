"""Pure entailment judge (M1 roadmap task J1.1).

Classify whether an exact evidence span *supports* an atomic claim. This module
is a **pure classifier**: it holds no repo write access of its own and never
spawns a provider subprocess directly. Every model invocation goes through the
sandboxed :func:`kops.runners.judge_run` primitive (roadmap S0.2), which runs
the provider in a throwaway temp dir, enforces a timeout and bounded I/O, and
validates the output against a strict JSON schema.

What it produces
----------------
For an ``(atomic claim, span)`` pair the judge returns a structured
:class:`EntailmentVerdict`::

    {
      "verdict": "supported | partial | unsupported | contradicted | not_evaluable",
      "rationale": "...",
      "missing_information": [],
      "judge_model": "...",
      "judge_prompt_fingerprint": "...",
      "claim_hash": "...",
      "span_hash": "...",
      ...
    }

``verdict``, ``rationale`` and ``missing_information`` come from the provider;
``judge_model`` / ``judge_prompt_fingerprint`` come from the ``judge_run``
result; ``claim_hash`` / ``span_hash`` are computed with the canonical D1.1
:func:`kops.evidence_model.content_hash` helper (never reinvented here).

``not_evaluable`` is first-class
--------------------------------
A claim that lacks an *exact* span — or a claim that is not atomic (compound) —
never reaches the provider and is returned as ``not_evaluable`` with an
explanatory rationale. Such verdicts remain visible in batch results: they are
returned, not dropped, so that evaluation coverage stays honest.

Caching
-------
Verdicts are cached, content-addressed, keyed by
``(claim_hash, span_hash, prompt_fingerprint, model, policy_version)``. A cache
hit never re-invokes the provider. Changing the span (new ``span_hash``) or
bumping :data:`ENTAILMENT_POLICY_VERSION` invalidates the entry and forces a
fresh judgement.

Non-gating
----------
Per the roadmap, entailment must **not** gate generic compilation CI. This
module produces verdicts for evaluation and calibration only; it is deliberately
not wired into any compile/heal gate.

Running with a real provider
----------------------------
The provider is injected through ``judge_run`` and configured independently of
the generator::

    export KB_JUDGE_AGENT=codex          # or claude / gemini
    export KB_JUDGE_MODEL=gpt-5-mini     # codex model (optional)
    # KB_JUDGE_CMD overrides the base command outright (used by tests for a stub)
    python -m kops.entailment_judge --input pair.json

``pair.json`` holds ``{"claim": {...}, "span": {...}, "context": "...",
"source_metadata": {...}}`` (claim/span in the D1.1 registry/anchor shapes).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from kops.atomic_claims import analyze_claim
from kops.evidence_model import (
    AtomicClaim,
    SourceSpan,
    ValidationEvent,
    content_hash,
    model_fingerprint,
)
from kops.evidence_store import EvidenceStore
from kops.kb_paths import ROOT
from kops.runners import (
    resolve_judge_agent,
    resolve_judge_command,
)
from kops.runners import (
    judge_run as _judge_run,
)
from kops.utils import ensure_dir

# --------------------------------------------------------------------------- #
# Policy + vocabulary
# --------------------------------------------------------------------------- #

# Bumping this string invalidates every cached verdict: the judging *policy*
# (prompt shape, rubric, verdict semantics) has changed, so prior verdicts are
# no longer comparable. It participates in the cache key and is recorded on
# every result and ValidationEvent.
ENTAILMENT_POLICY_VERSION = "1.0.0"

VALIDATOR_NAME = "entailment_judge"

SUPPORTED = "supported"
PARTIAL = "partial"
UNSUPPORTED = "unsupported"
CONTRADICTED = "contradicted"
NOT_EVALUABLE = "not_evaluable"

VERDICTS: tuple[str, ...] = (
    SUPPORTED,
    PARTIAL,
    UNSUPPORTED,
    CONTRADICTED,
    NOT_EVALUABLE,
)

# Bound the surrounding context handed to the provider (defence in depth on top
# of judge_run's own byte bounds).
MAX_CONTEXT_CHARS = 4000

# Strict schema the *provider* must satisfy. The hashes/fingerprint/model are
# added by this module, not asked of the provider.
PROVIDER_SCHEMA: dict = {
    "required": ["verdict", "rationale"],
    "properties": {
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "rationale": {"type": "string"},
        "missing_information": {"type": "array"},
    },
}


# --------------------------------------------------------------------------- #
# Result object
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EntailmentVerdict:
    """Structured verdict for one (claim, span) pair.

    ``not_evaluable`` verdicts carry the same shape as any other so they remain
    fully visible in batch output; ``judge_prompt_fingerprint`` / ``judge_model``
    are empty when no provider was invoked.
    """

    verdict: str
    rationale: str
    claim_id: str
    claim_hash: str
    span_id: str | None
    span_hash: str
    policy_version: str = ENTAILMENT_POLICY_VERSION
    missing_information: tuple[str, ...] = ()
    judge_model: str | None = None
    judge_prompt_fingerprint: str = ""
    cached: bool = False

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "rationale": self.rationale,
            "missing_information": list(self.missing_information),
            "judge_model": self.judge_model,
            "judge_prompt_fingerprint": self.judge_prompt_fingerprint,
            "claim_hash": self.claim_hash,
            "span_hash": self.span_hash,
            "claim_id": self.claim_id,
            "span_id": self.span_id,
            "policy_version": self.policy_version,
            "cached": self.cached,
        }

    @classmethod
    def from_dict(cls, data: dict) -> EntailmentVerdict:
        return cls(
            verdict=str(data.get("verdict") or NOT_EVALUABLE),
            rationale=str(data.get("rationale") or ""),
            claim_id=str(data.get("claim_id") or ""),
            claim_hash=str(data.get("claim_hash") or ""),
            span_id=data.get("span_id"),
            span_hash=str(data.get("span_hash") or ""),
            policy_version=str(data.get("policy_version") or ENTAILMENT_POLICY_VERSION),
            missing_information=tuple(data.get("missing_information") or ()),
            judge_model=data.get("judge_model"),
            judge_prompt_fingerprint=str(data.get("judge_prompt_fingerprint") or ""),
            cached=bool(data.get("cached") or False),
        )


# --------------------------------------------------------------------------- #
# Content-addressed verdict cache
# --------------------------------------------------------------------------- #


class EntailmentCache:
    """Deterministic, content-addressed verdict cache under ``data/``.

    The key is a SHA-256 over ``(claim_hash, span_hash, prompt_fingerprint,
    model, policy_version)``; the file at ``<base_dir>/<key>.json`` holds the
    serialized verdict. Same inputs -> same file -> a hit that never re-invokes
    the provider.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else (ROOT / "data" / "entailment_cache")

    @staticmethod
    def key(
        claim_hash: str,
        span_hash: str,
        prompt_fingerprint: str,
        model: str | None,
        policy_version: str,
    ) -> str:
        raw = "\x1f".join([claim_hash, span_hash, prompt_fingerprint, model or "", policy_version])
        return content_hash(raw)

    def _path(self, key: str) -> Path:
        return self.base_dir / f"{key}.json"

    def get(self, key: str) -> EntailmentVerdict | None:
        path = self._path(key)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return EntailmentVerdict.from_dict(data)

    def put(self, key: str, verdict: EntailmentVerdict) -> None:
        ensure_dir(self.base_dir)
        payload = verdict.to_dict()
        payload["cached"] = True  # a loaded copy is, by definition, a cache hit
        self._path(key).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )


# --------------------------------------------------------------------------- #
# Coercion helpers (accept typed objects or registry/anchor dicts)
# --------------------------------------------------------------------------- #


def _as_claim(claim: AtomicClaim | dict) -> AtomicClaim:
    if isinstance(claim, AtomicClaim):
        return claim
    return AtomicClaim.from_registry_dict(claim)


def _as_span(span: SourceSpan | dict | None) -> SourceSpan | None:
    if span is None:
        return None
    if isinstance(span, SourceSpan):
        return span
    # Accept either a serialized SourceSpan or a raw claim source-anchor dict.
    if "quote" in span or "span_id" in span or "content_hash" in span:
        try:
            return SourceSpan.from_dict(span)
        except Exception:  # pragma: no cover - defensive
            return SourceSpan.from_anchor(span)
    return SourceSpan.from_anchor(span)


def _is_exact_span(span: SourceSpan | None) -> bool:
    """An *exact* span carries a non-empty verbatim quote to judge against."""
    return span is not None and bool((span.quote or "").strip())


# --------------------------------------------------------------------------- #
# Prompt
# --------------------------------------------------------------------------- #


def build_prompt(
    claim: AtomicClaim,
    span: SourceSpan,
    context: str,
    source_metadata: dict | None,
) -> str:
    """Render the judge prompt. Deterministic given its inputs."""
    context = (context or "").strip()
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + " …[truncated]"
    meta_lines = []
    for key in sorted((source_metadata or {}).keys()):
        meta_lines.append(f"- {key}: {source_metadata[key]}")
    meta_block = "\n".join(meta_lines) if meta_lines else "- (none provided)"

    return f"""You are a strict, literal entailment judge. Decide whether the EVIDENCE SPAN,
read within its surrounding CONTEXT, supports the atomic CLAIM.

Verdict definitions (choose exactly one):
- supported: the span directly and fully supports the claim.
- partial: the span supports part of the claim but omits a necessary element
  (e.g. a qualifier, scope, or quantity).
- unsupported: the span neither supports nor contradicts the claim; it does not
  bear on it, or merely mentions the topic without asserting the claim.
- contradicted: the span asserts something incompatible with the claim.
- not_evaluable: the span or context is insufficient to make any judgement.

Be literal. Do not use outside knowledge. A quote that merely discusses the
topic is NOT support. Watch for reversed causality, omitted qualifiers, wrong
temporal scope, and front matter mistaken for evidence.

CLAIM:
{claim.claim_text}

EVIDENCE SPAN (verbatim quote):
\"\"\"
{span.quote}
\"\"\"

SURROUNDING CONTEXT:
\"\"\"
{context or "(none provided)"}
\"\"\"

SOURCE METADATA:
{meta_block}

Respond with a single JSON object and nothing else:
{{"verdict": "<supported|partial|unsupported|contradicted|not_evaluable>",
  "rationale": "<one or two sentences>",
  "missing_information": ["<what would be needed, if partial/not_evaluable>"]}}
"""


# --------------------------------------------------------------------------- #
# not_evaluable construction
# --------------------------------------------------------------------------- #


def _not_evaluable(
    claim: AtomicClaim,
    span: SourceSpan | None,
    reason: str,
) -> EntailmentVerdict:
    return EntailmentVerdict(
        verdict=NOT_EVALUABLE,
        rationale=reason,
        claim_id=claim.claim_id,
        claim_hash=content_hash(claim.claim_text) if claim.claim_text else "",
        span_id=span.span_id if span is not None else None,
        span_hash=content_hash(span.quote) if _is_exact_span(span) else "",
        missing_information=("exact evidence span",) if not _is_exact_span(span) else (),
        judge_model=None,
        judge_prompt_fingerprint="",
        cached=False,
    )


# --------------------------------------------------------------------------- #
# Core judge
# --------------------------------------------------------------------------- #


def judge(
    claim: AtomicClaim | dict,
    span: SourceSpan | dict | None,
    *,
    context: str = "",
    source_metadata: dict | None = None,
    agent: str | None = None,
    model: str | None = None,
    cache: EntailmentCache | None = None,
    store: EvidenceStore | None = None,
    check_atomic: bool = True,
    timeout: int | None = None,
) -> EntailmentVerdict:
    """Judge whether ``span`` supports ``claim``.

    Returns a fully populated :class:`EntailmentVerdict`. Claims without an exact
    span, and non-atomic (compound) claims, are returned as ``not_evaluable``
    without invoking the provider. Everything else goes through the sandboxed
    :func:`kops.runners.judge_run`.

    A cache hit (same claim_hash/span_hash/prompt_fingerprint/model/policy) is
    returned without re-invoking the provider. When ``store`` is given, every
    judgement is recorded as a D1.1 :class:`ValidationEvent`.
    """
    claim = _as_claim(claim)
    span = _as_span(span)
    cache = cache or EntailmentCache()

    # 1. Guard: an atomic claim is a precondition for entailment.
    if check_atomic:
        analysis = analyze_claim(claim)
        if not analysis["atomic"]:
            cats = ", ".join(sorted({r["category"] for r in analysis["reasons"]}))
            verdict = _not_evaluable(
                claim, span, f"claim is not atomic (compound: {cats}); decompose first"
            )
            _maybe_record(store, verdict)
            return verdict

    # 2. Guard: an exact span is required to judge anything.
    if not _is_exact_span(span):
        verdict = _not_evaluable(claim, span, "no exact evidence span to evaluate")
        _maybe_record(store, verdict)
        return verdict

    assert span is not None  # narrowed by _is_exact_span

    claim_hash = content_hash(claim.claim_text) if claim.claim_text else ""
    span_hash = content_hash(span.quote or "")

    # 3. Precompute the prompt fingerprint exactly as judge_run will, so the
    #    cache can be consulted *before* any provider invocation.
    resolved_agent = resolve_judge_agent(agent)
    resolved_model = model
    if resolved_agent == "codex":
        import os

        resolved_model = resolved_model or os.environ.get("KB_JUDGE_MODEL")
    base_cmd = resolve_judge_command(resolved_agent)
    prompt = build_prompt(claim, span, context, source_metadata)
    fingerprint = model_fingerprint(resolved_agent, base_cmd, resolved_model, prompt)

    cache_key = EntailmentCache.key(
        claim_hash, span_hash, fingerprint, resolved_model, ENTAILMENT_POLICY_VERSION
    )
    hit = cache.get(cache_key)
    if hit is not None:
        # A cache hit MUST NOT re-invoke the provider.
        return hit

    # 4. Cache miss: invoke the sandboxed judge. Any schema/parse failure
    #    propagates as runners.JudgeError (never a silent pass).
    kwargs: dict = {"agent": resolved_agent, "model": resolved_model}
    if timeout is not None:
        kwargs["timeout"] = timeout
    result = _judge_run(prompt, PROVIDER_SCHEMA, **kwargs)
    payload = result.verdict

    verdict = EntailmentVerdict(
        verdict=str(payload["verdict"]),
        rationale=str(payload.get("rationale") or ""),
        claim_id=claim.claim_id,
        claim_hash=claim_hash,
        span_id=span.span_id,
        span_hash=span_hash,
        policy_version=ENTAILMENT_POLICY_VERSION,
        missing_information=tuple(payload.get("missing_information") or ()),
        judge_model=result.model,
        judge_prompt_fingerprint=result.fingerprint,
        cached=False,
    )
    cache.put(cache_key, verdict)
    _maybe_record(store, verdict)
    return verdict


def judge_batch(
    pairs: list[tuple[AtomicClaim | dict, SourceSpan | dict | None]],
    *,
    agent: str | None = None,
    model: str | None = None,
    cache: EntailmentCache | None = None,
    store: EvidenceStore | None = None,
    check_atomic: bool = True,
) -> list[EntailmentVerdict]:
    """Judge many pairs, one verdict per input.

    Every input yields exactly one verdict — ``not_evaluable`` ones included, so
    they stay visible in the results and coverage is not silently reduced.
    """
    cache = cache or EntailmentCache()
    out: list[EntailmentVerdict] = []
    for claim, span in pairs:
        out.append(
            judge(
                claim,
                span,
                agent=agent,
                model=model,
                cache=cache,
                store=store,
                check_atomic=check_atomic,
            )
        )
    return out


def _maybe_record(store: EvidenceStore | None, verdict: EntailmentVerdict) -> None:
    """Record the judgement as a D1.1 ValidationEvent, if a store is provided."""
    if store is None:
        return
    event = ValidationEvent(
        target_id=verdict.claim_id,
        target_type=AtomicClaim.OBJECT_TYPE,
        validator=VALIDATOR_NAME,
        result=verdict.verdict,
        occurred_at=_dt.datetime.now().replace(microsecond=0).isoformat(),
        target_version=verdict.claim_hash or None,
        reason=verdict.rationale or None,
        fingerprint=verdict.judge_prompt_fingerprint or None,
        model=verdict.judge_model,
        prompt_version=verdict.judge_prompt_fingerprint or None,
        policy_version=verdict.policy_version,
    )
    store.append_validation_event(event)


# --------------------------------------------------------------------------- #
# CLI (module entrypoint only — deliberately NOT a kb.py subcommand)
# --------------------------------------------------------------------------- #


@dataclass
class _CliPair:
    claim: dict
    span: dict | None = None
    context: str = ""
    source_metadata: dict = field(default_factory=dict)


def _load_input(path: Path) -> list[_CliPair]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else [data]
    pairs: list[_CliPair] = []
    for item in items:
        pairs.append(
            _CliPair(
                claim=item.get("claim") or {},
                span=item.get("span"),
                context=str(item.get("context") or ""),
                source_metadata=dict(item.get("source_metadata") or {}),
            )
        )
    return pairs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m kops.entailment_judge",
        description=(
            "Pure entailment judge: classify whether an evidence span supports an "
            "atomic claim. Runs the judge via the sandboxed judge_run primitive."
        ),
    )
    parser.add_argument(
        "--input",
        required=True,
        help="JSON file with one object (or a list) of {claim, span, context, source_metadata}.",
    )
    parser.add_argument("--agent", help="Judge provider (default: KB_JUDGE_AGENT or codex).")
    parser.add_argument("--model", help="Judge model (codex).")
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Use a throwaway cache directory (do not read or persist verdicts).",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="Record each judgement as a ValidationEvent in the evidence store.",
    )
    args = parser.parse_args(argv)

    pairs = _load_input(Path(args.input))
    cache = None
    if args.no_cache:
        import tempfile

        cache = EntailmentCache(Path(tempfile.mkdtemp(prefix="kops-entail-nocache-")))
    store = EvidenceStore() if args.record else None

    results: list[dict] = []
    for p in pairs:
        verdict = judge(
            p.claim,
            p.span,
            context=p.context,
            source_metadata=p.source_metadata,
            agent=args.agent,
            model=args.model,
            cache=cache,
            store=store,
        )
        results.append(verdict.to_dict())

    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


__all__ = [
    "ENTAILMENT_POLICY_VERSION",
    "VALIDATOR_NAME",
    "VERDICTS",
    "SUPPORTED",
    "PARTIAL",
    "UNSUPPORTED",
    "CONTRADICTED",
    "NOT_EVALUABLE",
    "PROVIDER_SCHEMA",
    "EntailmentVerdict",
    "EntailmentCache",
    "build_prompt",
    "judge",
    "judge_batch",
]


if __name__ == "__main__":
    sys.exit(main())
