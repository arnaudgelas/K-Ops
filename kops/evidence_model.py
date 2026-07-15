"""Canonical, typed, versioned evidence objects (M1 task D1.1).

A single, additive representation of the evidence chain that later M1 tasks
(entailment judge, metrics, context packages) build on. This module does **not**
rewrite the existing registries — it provides typed *views* over them plus a few
greenfield objects, all stamped with a schema version and content-addressable
hashes.

The eight canonical objects
----------------------------
================  ==========================================================
Object            Relationship to what already exists
================  ==========================================================
Source            Typed view over ``notes/Sources/src-*.md`` frontmatter and
                  ``data/registry.json`` entries.
SourceVersion     GREENFIELD. Immutable, append-only ``(source_id,
                  content_hash, captured_at, provenance)`` record. Prior
                  versions are never overwritten.
SourceSpan        Unifies claim ``source_anchors`` (claim_registry) and
                  large-source manifest nodes (fetch_sources) into one
                  identity handle + coordinates + content hash.
AtomicClaim       Typed view over ``data/claims.json`` entries. Keeps the
                  ``clm-`` id format.
ClaimEvidenceLink Standalone extraction of the ``source_ids`` /
                  ``source_anchors`` / ``evidence_status`` that today live
                  *inside* a claim: claim <-> source_version <-> span.
ValidationEvent   GREENFIELD. Immutable, timestamped per-object judgement:
                  object identity+version, validator, result, model/prompt/
                  policy fingerprints, prior->new status, reason, timestamp.
ContextPackage    GREENFIELD. Frozen, content-addressed retrieval package
                  (question, tier, claim ids, spans, trust states, source
                  versions, freshness, excluded claims + reasons, retrieval
                  trace, policy version, package hash).
AnswerMemo        JSON view over the ``answer_memo`` note type carrying
                  ``retrieval_path`` / ``sources_consulted`` and a link to its
                  ContextPackage.
================  ==========================================================

Hashing convention
------------------
Two, and only two, hash shapes are used, resolving the pre-existing
inconsistency where some hashes were full SHA-256 and some ``[:10]``:

* **content hashes** — full 64-char hex SHA-256 (:func:`content_hash`). Used
  for source/claim/span *content* and every append-only version record.
* **stable ids** — a short 10-char SHA-256 prefix of a type-specific key
  (:func:`short_hash`), rendered with a typed prefix (``srcv-``, ``spn-``,
  ``evl-``, ``vev-``, ``ans-``). Existing ``clm-`` and ``src-`` id formats are
  preserved untouched.

Dependency edges reuse the graph relation vocabulary defined for retraction
blast-radius (:data:`EDGE_RELATIONS`).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, ClassVar

from kops.utils import short_hash

# --------------------------------------------------------------------------- #
# Versioning, edges, hashing
# --------------------------------------------------------------------------- #

# There is deliberately no schema_version anywhere else in the vault today.
# Every object and store envelope produced here is stamped with this constant.
SCHEMA_VERSION = "1.0.0"

# Dependency-edge vocabulary, reused verbatim from retract_source.build_impact_adjacency.
EDGE_RELATIONS: tuple[str, ...] = (
    "supported_by",
    "cites_source",
    "derived_from",
    "updates",
    "mentions",
)

_ID_LEN = 10


def content_hash(text: str) -> str:
    """Canonical content hash: full 64-char hex SHA-256 of ``text``."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(obj: Any) -> str:
    """Deterministic JSON encoding (sorted keys, compact) for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hash_payload(obj: Any) -> str:
    """Full SHA-256 over the canonical JSON encoding of ``obj``."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def stable_id(prefix: str, *parts: Any) -> str:
    """Typed stable id: ``<prefix>-`` + 10-char SHA-256 prefix over ``parts``."""
    key = "\x1f".join("" if p is None else str(p) for p in parts)
    return f"{prefix}-{short_hash(key, _ID_LEN)}"


def model_fingerprint(agent: str, base_cmd: list[str], model: str | None, prompt: str) -> str:
    """Model/prompt fingerprint. Delegates to the canonical judge algorithm.

    Reuses ``kops.runners._fingerprint`` rather than duplicating the hashing so
    a ValidationEvent fingerprint is comparable to a JudgeResult fingerprint.
    """
    from kops.runners import _fingerprint

    return _fingerprint(agent, base_cmd, model, prompt)


def _clean(value: Any) -> Any:
    """Drop ``None`` list/tuple members and normalise containers for hashing."""
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    return value


# --------------------------------------------------------------------------- #
# SourceSpan
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SourceSpan:
    """Exact evidence coordinates within a source (identity + coords + hash).

    Unifies two pre-existing shapes: claim ``source_anchors`` (quote/page/line/
    section/segment) and large-source manifest nodes (start_char/end_char/
    page_start/page_end/content_hash).
    """

    OBJECT_TYPE: ClassVar[str] = "source_span"

    source_id: str
    quote: str | None = None
    page: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    section: str | None = None
    segment_id: str | None = None
    start_char: int | None = None
    end_char: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    anchor: str | None = None
    path: str | None = None
    commit: str | None = None
    extraction_confidence: float | None = None
    content_hash: str | None = None
    schema_version: str = SCHEMA_VERSION

    @property
    def span_id(self) -> str:
        """Stable handle derived from the source and its exact coordinates."""
        return stable_id(
            "spn",
            self.source_id,
            self.quote,
            self.page,
            self.line_start,
            self.line_end,
            self.section,
            self.segment_id,
            self.start_char,
            self.end_char,
            self.page_start,
            self.page_end,
            self.anchor,
        )

    @classmethod
    def from_anchor(cls, anchor: dict) -> SourceSpan:
        """Build from a claim ``source_anchors`` entry (claim_registry shape)."""
        quote = anchor.get("quote")
        return cls(
            source_id=str(anchor.get("source_id") or ""),
            quote=quote,
            page=anchor.get("page"),
            line_start=anchor.get("line_start"),
            line_end=anchor.get("line_end"),
            section=anchor.get("section"),
            segment_id=anchor.get("segment_id"),
            anchor=anchor.get("anchor"),
            path=anchor.get("path"),
            commit=anchor.get("commit"),
            extraction_confidence=anchor.get("extraction_confidence"),
            content_hash=content_hash(quote) if quote else None,
        )

    @classmethod
    def from_manifest_node(cls, node: dict) -> SourceSpan:
        """Build from a large-source manifest node (fetch_sources shape)."""
        return cls(
            source_id=str(node.get("source_id") or node.get("node_id") or ""),
            section=node.get("title"),
            segment_id=node.get("node_id"),
            start_char=node.get("start_char"),
            end_char=node.get("end_char"),
            page_start=node.get("page_start"),
            page_end=node.get("page_end"),
            anchor=node.get("anchor"),
            content_hash=node.get("content_hash"),
        )

    def to_dict(self) -> dict:
        data = {
            "object_type": self.OBJECT_TYPE,
            "schema_version": self.schema_version,
            "span_id": self.span_id,
            "source_id": self.source_id,
            "quote": self.quote,
            "page": self.page,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "section": self.section,
            "segment_id": self.segment_id,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "anchor": self.anchor,
            "path": self.path,
            "commit": self.commit,
            "extraction_confidence": self.extraction_confidence,
            "content_hash": self.content_hash,
        }
        return data

    @classmethod
    def from_dict(cls, data: dict) -> SourceSpan:
        return cls(
            source_id=str(data.get("source_id") or ""),
            quote=data.get("quote"),
            page=data.get("page"),
            line_start=data.get("line_start"),
            line_end=data.get("line_end"),
            section=data.get("section"),
            segment_id=data.get("segment_id"),
            start_char=data.get("start_char"),
            end_char=data.get("end_char"),
            page_start=data.get("page_start"),
            page_end=data.get("page_end"),
            anchor=data.get("anchor"),
            path=data.get("path"),
            commit=data.get("commit"),
            extraction_confidence=data.get("extraction_confidence"),
            content_hash=data.get("content_hash"),
            schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
        )


# --------------------------------------------------------------------------- #
# Source
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Source:
    """Typed view over a source note's frontmatter / registry entry."""

    OBJECT_TYPE: ClassVar[str] = "source"

    source_id: str
    title: str
    source_url: str
    source_kind: str
    evidence_strength: str
    source_status: str
    ingested_at: str
    content_hash: str | None = None
    tags: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    @classmethod
    def from_frontmatter(cls, fm: dict) -> Source:
        tags = fm.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        return cls(
            source_id=str(fm.get("source_id") or ""),
            title=str(fm.get("title") or ""),
            source_url=str(fm.get("source_url") or ""),
            source_kind=str(fm.get("source_kind") or ""),
            evidence_strength=str(fm.get("evidence_strength") or ""),
            source_status=str(fm.get("source_status") or ""),
            ingested_at=str(fm.get("ingested_at") or ""),
            content_hash=(str(fm["content_hash"]) if fm.get("content_hash") else None),
            tags=tuple(str(t) for t in tags),
        )

    # Registry entries share the frontmatter field names.
    from_registry_entry = from_frontmatter

    def to_dict(self) -> dict:
        return {
            "object_type": self.OBJECT_TYPE,
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "title": self.title,
            "source_url": self.source_url,
            "source_kind": self.source_kind,
            "evidence_strength": self.evidence_strength,
            "source_status": self.source_status,
            "ingested_at": self.ingested_at,
            "content_hash": self.content_hash,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Source:
        return cls(
            source_id=str(data.get("source_id") or ""),
            title=str(data.get("title") or ""),
            source_url=str(data.get("source_url") or ""),
            source_kind=str(data.get("source_kind") or ""),
            evidence_strength=str(data.get("evidence_strength") or ""),
            source_status=str(data.get("source_status") or ""),
            ingested_at=str(data.get("ingested_at") or ""),
            content_hash=data.get("content_hash"),
            tags=tuple(data.get("tags") or ()),
            schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
        )


# --------------------------------------------------------------------------- #
# SourceVersion (greenfield, immutable + append-only)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SourceVersion:
    """An immutable snapshot of a source's raw content at one point in time.

    The version id is derived purely from ``(source_id, content_hash)`` so the
    same content always maps to the same version; a changed hash is a new
    version. The append-only store never overwrites a prior version.
    """

    OBJECT_TYPE: ClassVar[str] = "source_version"

    source_id: str
    content_hash: str
    captured_at: str
    provenance: str
    git_commit: str | None = None
    raw_path: str | None = None
    schema_version: str = SCHEMA_VERSION

    @property
    def version_id(self) -> str:
        return stable_id("srcv", self.source_id, self.content_hash)

    def to_dict(self) -> dict:
        return {
            "object_type": self.OBJECT_TYPE,
            "schema_version": self.schema_version,
            "version_id": self.version_id,
            "source_id": self.source_id,
            "content_hash": self.content_hash,
            "captured_at": self.captured_at,
            "provenance": self.provenance,
            "git_commit": self.git_commit,
            "raw_path": self.raw_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SourceVersion:
        return cls(
            source_id=str(data.get("source_id") or ""),
            content_hash=str(data.get("content_hash") or ""),
            captured_at=str(data.get("captured_at") or ""),
            provenance=str(data.get("provenance") or ""),
            git_commit=data.get("git_commit"),
            raw_path=data.get("raw_path"),
            schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
        )


# --------------------------------------------------------------------------- #
# AtomicClaim (typed view over data/claims.json)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AtomicClaim:
    """Typed view over a claims.json registry entry. Keeps the ``clm-`` id."""

    OBJECT_TYPE: ClassVar[str] = "atomic_claim"

    claim_id: str
    claim_text: str
    concept: str | None = None
    source_ids: tuple[str, ...] = ()
    evidence_status: str | None = None
    admission_status: str | None = None
    claim_quality: str | None = None
    confidence: float | None = None
    spans: tuple[SourceSpan, ...] = ()
    content_hash: str | None = None
    schema_version: str = SCHEMA_VERSION

    @classmethod
    def from_registry_dict(cls, d: dict) -> AtomicClaim:
        text = str(d.get("claim_text") or d.get("text") or "")
        anchors = d.get("source_anchors") or []
        spans = tuple(SourceSpan.from_anchor(a) for a in anchors if a.get("source_id"))
        return cls(
            claim_id=str(d.get("claim_id") or d.get("id") or ""),
            claim_text=text,
            concept=d.get("concept"),
            source_ids=tuple(str(s) for s in (d.get("source_ids") or ())),
            evidence_status=d.get("evidence_status"),
            admission_status=d.get("admission_status"),
            claim_quality=d.get("claim_quality"),
            confidence=d.get("confidence"),
            spans=spans,
            content_hash=content_hash(text) if text else None,
        )

    def to_dict(self) -> dict:
        return {
            "object_type": self.OBJECT_TYPE,
            "schema_version": self.schema_version,
            "claim_id": self.claim_id,
            "claim_text": self.claim_text,
            "concept": self.concept,
            "source_ids": list(self.source_ids),
            "evidence_status": self.evidence_status,
            "admission_status": self.admission_status,
            "claim_quality": self.claim_quality,
            "confidence": self.confidence,
            "spans": [s.to_dict() for s in self.spans],
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AtomicClaim:
        return cls(
            claim_id=str(data.get("claim_id") or ""),
            claim_text=str(data.get("claim_text") or ""),
            concept=data.get("concept"),
            source_ids=tuple(data.get("source_ids") or ()),
            evidence_status=data.get("evidence_status"),
            admission_status=data.get("admission_status"),
            claim_quality=data.get("claim_quality"),
            confidence=data.get("confidence"),
            spans=tuple(SourceSpan.from_dict(s) for s in (data.get("spans") or ())),
            content_hash=data.get("content_hash"),
            schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
        )


# --------------------------------------------------------------------------- #
# ClaimEvidenceLink (extracted from inside a claim)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ClaimEvidenceLink:
    """Standalone claim <-> source_version <-> span link with evidence status."""

    OBJECT_TYPE: ClassVar[str] = "claim_evidence_link"

    claim_id: str
    source_id: str
    span: SourceSpan | None = None
    evidence_status: str | None = None
    source_version_id: str | None = None
    relation: str = "supported_by"
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.relation not in EDGE_RELATIONS:
            raise ValueError(f"relation {self.relation!r} not in edge vocabulary {EDGE_RELATIONS}")

    @property
    def link_id(self) -> str:
        span_part = self.span.span_id if self.span else ""
        return stable_id("evl", self.claim_id, self.source_id, span_part, self.relation)

    @classmethod
    def links_from_claim(
        cls,
        claim: dict,
        source_versions: dict[str, str] | None = None,
    ) -> list[ClaimEvidenceLink]:
        """Extract one link per cited source from a claims.json entry.

        ``source_versions`` optionally maps ``source_id -> version_id`` to pin
        each link to an immutable SourceVersion.
        """
        source_versions = source_versions or {}
        claim_id = str(claim.get("claim_id") or claim.get("id") or "")
        evidence_status = claim.get("evidence_status")
        anchors_by_source: dict[str, SourceSpan] = {}
        for anchor in claim.get("source_anchors") or []:
            sid = anchor.get("source_id")
            if sid and sid not in anchors_by_source:
                anchors_by_source[sid] = SourceSpan.from_anchor(anchor)
        links: list[ClaimEvidenceLink] = []
        for source_id in claim.get("source_ids") or []:
            source_id = str(source_id)
            links.append(
                cls(
                    claim_id=claim_id,
                    source_id=source_id,
                    span=anchors_by_source.get(source_id),
                    evidence_status=evidence_status,
                    source_version_id=source_versions.get(source_id),
                )
            )
        return links

    def to_dict(self) -> dict:
        return {
            "object_type": self.OBJECT_TYPE,
            "schema_version": self.schema_version,
            "link_id": self.link_id,
            "claim_id": self.claim_id,
            "source_id": self.source_id,
            "span": self.span.to_dict() if self.span else None,
            "evidence_status": self.evidence_status,
            "source_version_id": self.source_version_id,
            "relation": self.relation,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ClaimEvidenceLink:
        span = data.get("span")
        return cls(
            claim_id=str(data.get("claim_id") or ""),
            source_id=str(data.get("source_id") or ""),
            span=SourceSpan.from_dict(span) if span else None,
            evidence_status=data.get("evidence_status"),
            source_version_id=data.get("source_version_id"),
            relation=str(data.get("relation") or "supported_by"),
            schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
        )


# --------------------------------------------------------------------------- #
# ValidationEvent (greenfield, immutable + append-only)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ValidationEvent:
    """An immutable, timestamped judgement about one object at one version."""

    OBJECT_TYPE: ClassVar[str] = "validation_event"

    target_id: str
    target_type: str
    validator: str
    result: str
    occurred_at: str
    target_version: str | None = None
    prior_status: str | None = None
    new_status: str | None = None
    reason: str | None = None
    fingerprint: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    policy_version: str | None = None
    schema_version: str = SCHEMA_VERSION

    @property
    def event_id(self) -> str:
        return stable_id(
            "vev",
            self.target_id,
            self.target_version,
            self.validator,
            self.result,
            self.occurred_at,
            self.fingerprint,
        )

    def to_dict(self) -> dict:
        return {
            "object_type": self.OBJECT_TYPE,
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "target_id": self.target_id,
            "target_type": self.target_type,
            "target_version": self.target_version,
            "validator": self.validator,
            "result": self.result,
            "prior_status": self.prior_status,
            "new_status": self.new_status,
            "reason": self.reason,
            "fingerprint": self.fingerprint,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "policy_version": self.policy_version,
            "occurred_at": self.occurred_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ValidationEvent:
        return cls(
            target_id=str(data.get("target_id") or ""),
            target_type=str(data.get("target_type") or ""),
            validator=str(data.get("validator") or ""),
            result=str(data.get("result") or ""),
            occurred_at=str(data.get("occurred_at") or ""),
            target_version=data.get("target_version"),
            prior_status=data.get("prior_status"),
            new_status=data.get("new_status"),
            reason=data.get("reason"),
            fingerprint=data.get("fingerprint"),
            model=data.get("model"),
            prompt_version=data.get("prompt_version"),
            policy_version=data.get("policy_version"),
            schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
        )


# --------------------------------------------------------------------------- #
# ContextPackage (greenfield, frozen + content-addressed)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ContextPackage:
    """A frozen, content-addressed retrieval package for one question.

    ``package_hash`` covers the *retrieval content* (question, tier, claims,
    spans, trust states, source versions, freshness, exclusions, trace, policy)
    but deliberately excludes ``built_at`` so two builds of identical content
    hash equal — the package is content-addressed, not time-addressed.
    """

    OBJECT_TYPE: ClassVar[str] = "context_package"

    question: str
    tier: str
    claim_ids: tuple[str, ...] = ()
    spans: tuple[SourceSpan, ...] = ()
    trust_states: dict = field(default_factory=dict)
    source_version_ids: tuple[str, ...] = ()
    freshness: dict = field(default_factory=dict)
    excluded_claims: tuple = ()
    retrieval_trace: tuple = ()
    policy_version: str = ""
    built_at: str = ""
    schema_version: str = SCHEMA_VERSION

    def _hash_payload(self) -> dict:
        return _clean(
            {
                "question": self.question,
                "tier": self.tier,
                "claim_ids": list(self.claim_ids),
                "spans": [s.to_dict() for s in self.spans],
                "trust_states": self.trust_states,
                "source_version_ids": list(self.source_version_ids),
                "freshness": self.freshness,
                "excluded_claims": list(self.excluded_claims),
                "retrieval_trace": list(self.retrieval_trace),
                "policy_version": self.policy_version,
                "schema_version": self.schema_version,
            }
        )

    @property
    def package_hash(self) -> str:
        return hash_payload(self._hash_payload())

    def to_dict(self) -> dict:
        return {
            "object_type": self.OBJECT_TYPE,
            "schema_version": self.schema_version,
            "package_hash": self.package_hash,
            "question": self.question,
            "tier": self.tier,
            "claim_ids": list(self.claim_ids),
            "spans": [s.to_dict() for s in self.spans],
            "trust_states": self.trust_states,
            "source_version_ids": list(self.source_version_ids),
            "freshness": self.freshness,
            "excluded_claims": list(self.excluded_claims),
            "retrieval_trace": list(self.retrieval_trace),
            "policy_version": self.policy_version,
            "built_at": self.built_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ContextPackage:
        return cls(
            question=str(data.get("question") or ""),
            tier=str(data.get("tier") or ""),
            claim_ids=tuple(data.get("claim_ids") or ()),
            spans=tuple(SourceSpan.from_dict(s) for s in (data.get("spans") or ())),
            trust_states=dict(data.get("trust_states") or {}),
            source_version_ids=tuple(data.get("source_version_ids") or ()),
            freshness=dict(data.get("freshness") or {}),
            excluded_claims=tuple(data.get("excluded_claims") or ()),
            retrieval_trace=tuple(data.get("retrieval_trace") or ()),
            policy_version=str(data.get("policy_version") or ""),
            built_at=str(data.get("built_at") or ""),
            schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
        )


# --------------------------------------------------------------------------- #
# AnswerMemo (JSON view over the answer_memo note type)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AnswerMemo:
    """JSON view over an ``answer_memo`` note, linked to its ContextPackage."""

    OBJECT_TYPE: ClassVar[str] = "answer_memo"

    title: str
    asked_at: str
    query_class: str = ""
    answer_quality: str = ""
    scope: str = ""
    retrieval_path: tuple = ()
    sources_consulted: tuple = ()
    fetch_required: bool = False
    context_package_hash: str | None = None
    schema_version: str = SCHEMA_VERSION

    @property
    def memo_id(self) -> str:
        return stable_id("ans", self.title, self.asked_at)

    @classmethod
    def from_frontmatter(cls, fm: dict, context_package_hash: str | None = None) -> AnswerMemo:
        return cls(
            title=str(fm.get("title") or ""),
            asked_at=str(fm.get("asked_at") or ""),
            query_class=str(fm.get("query_class") or ""),
            answer_quality=str(fm.get("answer_quality") or ""),
            scope=str(fm.get("scope") or ""),
            retrieval_path=tuple(fm.get("retrieval_path") or ()),
            sources_consulted=tuple(fm.get("sources_consulted") or ()),
            fetch_required=bool(fm.get("fetch_required") or False),
            context_package_hash=context_package_hash,
        )

    def to_dict(self) -> dict:
        return {
            "object_type": self.OBJECT_TYPE,
            "schema_version": self.schema_version,
            "memo_id": self.memo_id,
            "title": self.title,
            "asked_at": self.asked_at,
            "query_class": self.query_class,
            "answer_quality": self.answer_quality,
            "scope": self.scope,
            "retrieval_path": list(self.retrieval_path),
            "sources_consulted": list(self.sources_consulted),
            "fetch_required": self.fetch_required,
            "context_package_hash": self.context_package_hash,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AnswerMemo:
        return cls(
            title=str(data.get("title") or ""),
            asked_at=str(data.get("asked_at") or ""),
            query_class=str(data.get("query_class") or ""),
            answer_quality=str(data.get("answer_quality") or ""),
            scope=str(data.get("scope") or ""),
            retrieval_path=tuple(data.get("retrieval_path") or ()),
            sources_consulted=tuple(data.get("sources_consulted") or ()),
            fetch_required=bool(data.get("fetch_required") or False),
            context_package_hash=data.get("context_package_hash"),
            schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
        )


__all__ = [
    "SCHEMA_VERSION",
    "EDGE_RELATIONS",
    "content_hash",
    "canonical_json",
    "hash_payload",
    "stable_id",
    "model_fingerprint",
    "Source",
    "SourceVersion",
    "SourceSpan",
    "AtomicClaim",
    "ClaimEvidenceLink",
    "ValidationEvent",
    "ContextPackage",
    "AnswerMemo",
]
