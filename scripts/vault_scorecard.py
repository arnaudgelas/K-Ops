"""Vault scorecard — compute knowledge-quality metrics across the whole vault.

Reads the vault in read-only mode; builds a structured health report and writes
it to ``data/scorecard.json``.
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

_PROBES_FILE = ROOT / "research" / "evals" / "dev-probes.jsonl"
_EVAL_RUNS_DIR = ROOT / "data" / "eval_runs"
_INLINE_SOURCE_RE = re.compile(r"\(\[\[Sources/(?:[^/]+/)?src-[0-9a-f]{10}")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*\S.*?)\s*$")
_CLAIMS_SECTION_RE = re.compile(r"## Key Claims\s+(.*?)(?:\n## |\Z)", re.DOTALL)
_EVIDENCE_SOURCE_RE = re.compile(r"\[\[Sources/(?:[^/]+/)?(src-[0-9a-f]{10})\|")
_EVIDENCE_SECTION_RE = re.compile(r"## Evidence / Source Basis\s+(.*?)(?:\n## |\Z)", re.DOTALL)
# A11: section-anchor and bare-citation regexes for scorecard metrics
_SECTION_ANCHOR_CITE_RE = re.compile(
    r"\[\[Sources/(?:[^/\]#|]+/)?(src-[0-9a-f]{10})#([^\]|]+)(?:\|[^\]]*)?\]\]"
)
_BARE_CITE_RE = re.compile(r"\[\[Sources/(?:[^/\]#|]+/)?(src-[0-9a-f]{10})\|\1\]\]")
_RAW_DIR = ROOT / "data" / "raw"

_v2_source_ids_cache: set[str] | None = None


def _get_v2_source_ids() -> set[str]:
    """Return the set of source IDs that have a v2 large_source_manifest.json."""
    global _v2_source_ids_cache
    if _v2_source_ids_cache is not None:
        return _v2_source_ids_cache
    _v2_source_ids_cache = set()
    for mf in _RAW_DIR.rglob("large_source_manifest.json"):
        try:
            m = json.loads(mf.read_text(encoding="utf-8"))
            if m.get("large_source_manifest_version") == 2 and m.get("nodes"):
                _v2_source_ids_cache.add(mf.parent.name)
        except Exception:
            pass
    return _v2_source_ids_cache


def _claims_inline_citation_count(body: str) -> tuple[int, int]:
    match = _CLAIMS_SECTION_RE.search(body)
    if not match:
        return 0, 0
    total = 0
    with_citation = 0
    for line in match.group(1).splitlines():
        if _BULLET_RE.match(line):
            total += 1
            if _INLINE_SOURCE_RE.search(line):
                with_citation += 1
    return with_citation, total


def _derive_evidence_status(body: str, concept_stem: str, contested_concepts: set[str]) -> str:
    if concept_stem in contested_concepts:
        return "contested"
    ev_match = _EVIDENCE_SECTION_RE.search(body)
    if not ev_match:
        return "seed"
    source_ids = set(_EVIDENCE_SOURCE_RE.findall(ev_match.group(1)))
    return "synthesized" if len(source_ids) >= 2 else "seed"


def _get_partial_source_ids() -> set[str]:
    partial_ids = set()
    for path in CONFIG.summaries_dir.rglob("src-*.md"):
        try:
            frontmatter, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            strength = frontmatter.get("evidence_strength")
            kind = frontmatter.get("source_kind")
            is_partial = strength == "primary-doc-partial"
            if kind == "github-repo-snapshot":
                sampled = frontmatter.get("sampled_file_count")
                tracked = frontmatter.get("tracked_file_count")
                if sampled is not None and tracked is not None and int(sampled) < int(tracked):
                    is_partial = True
            if is_partial:
                partial_ids.add(path.stem)
        except Exception:
            pass
    return partial_ids


def _score_concepts() -> dict:
    concepts = list(CONFIG.concepts_dir.glob("*.md"))
    quality_counter: Counter = Counter()
    evidence_status_counter: Counter = Counter()
    unsupported = 0
    revalidation_required = 0
    conflicting_no_oq = 0
    bullets_total = 0
    bullets_with_inline = 0
    partial_source_dependencies = 0

    contested_concepts: set[str] = set()
    if _CONTRADICTIONS_PATH.exists():
        try:
            payload = json.loads(_CONTRADICTIONS_PATH.read_text(encoding="utf-8"))
            for rec in payload.get("contradictions", []):
                if rec.get("concept"):
                    contested_concepts.add(str(rec["concept"]))
        except (json.JSONDecodeError, OSError):
            pass

    partial_source_ids = _get_partial_source_ids()

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
        es = frontmatter.get("evidence_status") or _derive_evidence_status(
            body, path.stem, contested_concepts
        )
        evidence_status_counter[es] += 1

        # Count if this concept depends on any partial sources
        # Count only Evidence-section references to partial sources (not Key Claims)
        # A3 gate intent: concepts should not EVIDENCE-back claims with partial sources,
        # but Key Claims may legitimately cite partial sources as claim-level attribution.
        ev_text_for_partial = ev_match.group(1) if ev_match else ""
        ev_refs = set(_EVIDENCE_SOURCE_RE.findall(ev_text_for_partial))
        if ev_refs & partial_source_ids:
            partial_source_dependencies += 1

    return {
        "total": len(concepts),
        "by_claim_quality": dict(quality_counter),
        "by_evidence_status": dict(evidence_status_counter),
        "unsupported": unsupported,
        "revalidation_required": revalidation_required,
        "conflicting_without_open_questions": conflicting_no_oq,
        "claim_bullets_total": bullets_total,
        "claim_bullets_with_inline_citation": bullets_with_inline,
        "inline_citation_rate": round(bullets_with_inline / bullets_total, 3)
        if bullets_total
        else None,
        "partial_source_dependencies": partial_source_dependencies,
    }


def _score_indexes() -> dict:
    indexes = list(CONFIG.indexes_dir.glob("*.md"))
    type_counter: Counter = Counter()
    for path in indexes:
        frontmatter, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        type_counter[str(frontmatter.get("type") or "unknown")] += 1
    return {"total": len(indexes), "by_type": dict(type_counter)}


_REVOKED_SOURCE_STATUSES = {"permission-revoked", "deleted-from-origin", "do-not-use"}


def _score_sources() -> dict:
    sources = list(CONFIG.summaries_dir.rglob("src-*.md"))
    strength_counter: Counter = Counter()
    kind_counter: Counter = Counter()
    status_counter: Counter = Counter()
    partial_source_count = 0

    # Build source_id -> evidence_strength map for concept-level cross-check below
    source_strength_by_id: dict[str, str] = {}
    for path in sources:
        try:
            frontmatter, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            strength = str(frontmatter.get("evidence_strength") or "unknown")
            kind = str(frontmatter.get("source_kind") or "unknown")
            status = str(frontmatter.get("source_status") or "unknown")
            strength_counter[strength] += 1
            kind_counter[kind] += 1
            status_counter[status] += 1
            source_strength_by_id[path.stem] = strength

            is_partial = strength == "primary-doc-partial"
            if kind == "github-repo-snapshot":
                sampled = frontmatter.get("sampled_file_count")
                tracked = frontmatter.get("tracked_file_count")
                if sampled is not None and tracked is not None and int(sampled) < int(tracked):
                    is_partial = True
            if is_partial:
                partial_source_count += 1
        except Exception:
            pass

    total = len(sources)
    stub_count = sum(strength_counter.get(k, 0) for k in ("stub", "citation-only", "image-only"))
    primary_count = sum(
        strength_counter.get(k, 0)
        for k in ("primary-doc", "official-spec", "strong", "primary-doc-partial")
    )
    model_gen_count = strength_counter.get("model-generated", 0) + kind_counter.get(
        "imported_model_report", 0
    )
    revoked_count = sum(status_counter.get(s, 0) for s in _REVOKED_SOURCE_STATUSES)

    # Count supported concepts that cite at least one model-generated source
    model_generated_in_supported_concepts = 0
    _evidence_src_re = re.compile(r"\[\[Sources/(?:[^/]+/)?(src-[0-9a-f]{10})\|")
    _evidence_sec_re = re.compile(r"## Evidence / Source Basis\s+(.*?)(?:\n## |\Z)", re.DOTALL)
    for concept_path in CONFIG.concepts_dir.glob("*.md"):
        try:
            text = concept_path.read_text(encoding="utf-8")
            fm, _ = parse_frontmatter(text)
            if str(fm.get("claim_quality") or "") != "supported":
                continue
            ev_match = _evidence_sec_re.search(text)
            if not ev_match:
                continue
            cited_ids = set(_evidence_src_re.findall(ev_match.group(1)))
            if any(source_strength_by_id.get(sid) == "model-generated" for sid in cited_ids):
                model_generated_in_supported_concepts += 1
        except Exception:
            pass

    return {
        "total": total,
        "by_evidence_strength": dict(strength_counter),
        "by_source_kind": dict(kind_counter),
        "by_source_status": dict(status_counter),
        "stub_count": stub_count,
        "primary_count": primary_count,
        "model_generated_count": model_gen_count,
        "revoked_count": revoked_count,
        "stub_fraction": round(stub_count / total, 3) if total else None,
        "primary_fraction": round(primary_count / total, 3) if total else None,
        "partial_source_count": partial_source_count,
        "model_generated_in_supported_concepts": model_generated_in_supported_concepts,
    }


def _score_claims() -> dict:
    if not _CLAIMS_PATH.exists():
        return {
            "total": 0,
            "by_quality": {},
            "with_sources": 0,
            "without_sources": 0,
            "direct": 0,
            "inherited": 0,
            "unsupported": 0,
            "direct_citation_rate": None,
            "direct_citation_rate_by_quality": {},
            "by_admission_status": {},
            "quarantined": 0,
            "blocked": 0,
            "synthetic_origin": 0,
        }
    payload = json.loads(_CLAIMS_PATH.read_text(encoding="utf-8"))
    claims = payload.get("claims", [])
    total = len(claims)
    with_sources = sum(1 for c in claims if c.get("source_ids"))
    quality_counter: Counter = Counter(str(c.get("claim_quality") or "unknown") for c in claims)
    evidence_counter: Counter = Counter(str(c.get("evidence_status") or "unknown") for c in claims)
    admission_counter: Counter = Counter(
        str(c.get("admission_status") or "unknown") for c in claims
    )
    direct_by_quality: dict[str, float | None] = {}
    for quality in sorted(quality_counter):
        quality_claims = [c for c in claims if str(c.get("claim_quality") or "unknown") == quality]
        direct_count = sum(1 for c in quality_claims if c.get("evidence_status") == "direct")
        direct_by_quality[quality] = (
            round(direct_count / len(quality_claims), 3) if quality_claims else None
        )
    direct = evidence_counter.get("direct", 0)
    inherited = evidence_counter.get("inherited", 0)
    unsupported = evidence_counter.get("unsupported", 0)
    # Anchor coverage by source kind
    try:
        import json as _json

        _registry_path = ROOT / "data" / "registry.json"
        _reg_by_id: dict = {}
        if _registry_path.exists():
            _reg_by_id = {
                r["id"]: r for r in _json.loads(_registry_path.read_text(encoding="utf-8"))
            }

        _anchor_kind_anchored: Counter = Counter()
        _anchor_kind_total: Counter = Counter()
        _span_status_dist: Counter = Counter()

        for c in claims:
            _span_status_dist[str(c.get("span_status") or "missing")] += 1
            _is_anchored = c.get("span_status", "missing") != "missing"
            for sa in c.get("source_anchors", []):
                _sid = sa.get("source_id")
                if _sid:
                    _kind = _reg_by_id.get(_sid, {}).get("kind", "unknown")
                    _anchor_kind_total[_kind] += 1
                    if _is_anchored:
                        _anchor_kind_anchored[_kind] += 1

        _anchor_coverage: dict = {}
        for _k in _anchor_kind_total:
            _tot = _anchor_kind_total[_k]
            _anc = _anchor_kind_anchored.get(_k, 0)
            _anchor_coverage[_k] = round(_anc / _tot, 3) if _tot else None
    except Exception:
        _anchor_coverage = {}
        _span_status_dist = Counter()

    # A11: Compute source_section_anchor_coverage and long_source_bare_citation_count
    # by scanning Key Claims sections across all concept pages
    _v2_ids = _get_v2_source_ids()
    _section_anchored_claims = 0
    _v2_backed_claims = 0
    _long_source_bare_count = 0
    try:
        from utils import CONFIG as _cfg

        for _cp in _cfg.concepts_dir.glob("*.md"):
            try:
                _body = _cp.read_text(encoding="utf-8")
            except OSError:
                continue
            _kc_match = _CLAIMS_SECTION_RE.search(_body)
            if not _kc_match:
                continue
            for _line in _kc_match.group(1).splitlines():
                if not re.match(r"^\s*[-*]\s+", _line):
                    continue
                # Does this bullet cite a v2-manifest source (anchored or bare)?
                _line_v2_bare = {
                    _m.group(1) for _m in _BARE_CITE_RE.finditer(_line) if _m.group(1) in _v2_ids
                }
                _line_v2_anchored = {
                    _m.group(1)
                    for _m in _SECTION_ANCHOR_CITE_RE.finditer(_line)
                    if _m.group(1) in _v2_ids
                }
                _line_v2 = _line_v2_bare | _line_v2_anchored
                if _line_v2:
                    _v2_backed_claims += 1
                    if _line_v2_anchored:
                        _section_anchored_claims += 1
                    else:
                        _long_source_bare_count += 1
    except Exception:
        pass

    _section_anchor_coverage = (
        round(_section_anchored_claims / _v2_backed_claims, 3) if _v2_backed_claims else None
    )

    return {
        "total": total,
        "by_quality": dict(quality_counter),
        "with_sources": with_sources,
        "without_sources": total - with_sources,
        "by_evidence_status": dict(evidence_counter),
        "by_admission_status": dict(admission_counter),
        "direct": direct,
        "inherited": inherited,
        "unsupported": unsupported,
        "quarantined": admission_counter.get("quarantine", 0),
        "blocked": admission_counter.get("blocked", 0),
        "synthetic_origin": sum(1 for c in claims if c.get("synthetic_origin") is True),
        "direct_citation_rate": round(direct / total, 3) if total else None,
        "direct_citation_rate_by_quality": direct_by_quality,
        "span_status_distribution": dict(_span_status_dist),
        "anchor_coverage_by_source_kind": _anchor_coverage,
        "source_section_anchor_coverage": _section_anchor_coverage,
        "long_source_bare_citation_count": _long_source_bare_count,
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


def _score_graph_topology() -> dict:
    """Compute graph-topology health metrics from vault_graph.json."""
    graph_path = ROOT / "data" / "graph" / "vault_graph.json"
    if not graph_path.exists():
        return {"available": False}
    try:
        G = json.loads(graph_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"available": False}

    nodes = G.get("nodes", [])
    edges = G.get("edges", [])

    in_deg: dict[str, int] = {}
    out_deg: dict[str, int] = {}
    for n in nodes:
        in_deg[n["id"]] = 0
        out_deg[n["id"]] = 0
    for e in edges:
        out_deg[e["source"]] = out_deg.get(e["source"], 0) + 1
        in_deg[e["target"]] = in_deg.get(e["target"], 0) + 1

    src_nodes = [n for n in nodes if n.get("kind") == "source"]
    con_nodes = [n for n in nodes if n.get("kind") == "concept"]
    ans_nodes = [n for n in nodes if n.get("kind") == "answer"]
    contra_nodes = [n for n in nodes if n.get("kind") == "contradiction"]

    orphaned_sources = sum(1 for n in src_nodes if in_deg.get(n["id"], 0) == 0)
    isolated_concepts = sum(
        1 for n in con_nodes
        if in_deg.get(n["id"], 0) + out_deg.get(n["id"], 0) == 0
    )
    isolated_answers = sum(1 for n in ans_nodes if out_deg.get(n["id"], 0) == 0)

    return {
        "available": True,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "source_count": len(src_nodes),
        "orphaned_sources": orphaned_sources,
        "orphaned_source_rate": round(orphaned_sources / max(len(src_nodes), 1), 3),
        "isolated_concepts": isolated_concepts,
        "isolated_answers": isolated_answers,
        "contradiction_nodes": len(contra_nodes),
    }


def _score_schema_compliance() -> dict:
    """Count schema violations across source notes, concept pages, and answer memos."""
    try:
        from kb_schema import Validator
        from utils import parse_frontmatter as _pfm
    except ImportError:
        return {"error_count": -1, "missing_fields": {}, "note": "kb_schema not available"}

    validator = Validator()
    error_count = 0
    missing_fields: Counter = Counter()

    for path in sorted(CONFIG.summaries_dir.rglob("src-*.md")):
        fm, _ = _pfm(path.read_text(encoding="utf-8"))
        for issue in validator.validate_source_note(fm, path):
            if issue.severity == "error":
                error_count += 1
                missing_fields[issue.field] += 1

    for path in sorted(CONFIG.concepts_dir.glob("*.md")):
        fm, _ = _pfm(path.read_text(encoding="utf-8"))
        for issue in validator.validate_concept_page(fm, path):
            if issue.severity == "error":
                error_count += 1
                missing_fields[issue.field] += 1

    for path in sorted(CONFIG.answers_dir.glob("*.md")):
        fm, _ = _pfm(path.read_text(encoding="utf-8"))
        for issue in validator.validate_answer_memo(fm, path):
            if issue.severity == "error":
                error_count += 1
                missing_fields[issue.field] += 1

    return {"error_count": error_count, "missing_fields": dict(missing_fields)}


def _score_probes() -> dict:
    """Count probes by review_status and compute coverage by concept quality tier."""
    # Identify supported and provisional concepts from the vault
    supported_concepts: set[str] = set()
    provisional_concepts: set[str] = set()
    for path in CONFIG.concepts_dir.glob("*.md"):
        try:
            frontmatter, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            cq = str(frontmatter.get("claim_quality") or "")
            if cq == "supported":
                supported_concepts.add(path.stem)
            elif cq == "provisional":
                provisional_concepts.add(path.stem)
        except Exception:
            pass

    if not _PROBES_FILE.exists():
        return {
            "total": 0,
            "by_review_status": {},
            "by_status": {},
            "concepts_with_approved": 0,
            "concepts_without_approved": [],
            "coverage": {
                "supported_with_probe": 0,
                "supported_total": len(supported_concepts),
                "provisional_with_probe": 0,
                "provisional_total": len(provisional_concepts),
            },
        }
    status_counter: Counter = Counter()
    concepts_with_approved: set[str] = set()
    concepts_with_probes: set[str] = set()
    try:
        for line in _PROBES_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                p = json.loads(line)
            except Exception:
                continue
            status = str(p.get("review_status") or "unreviewed")
            status_counter[status] += 1
            concept = p.get("concept")
            if concept:
                concepts_with_probes.add(concept)
                if status == "approved":
                    concepts_with_approved.add(concept)
    except Exception:
        pass
    concepts_without_approved = sorted(concepts_with_probes - concepts_with_approved)
    supported_with_probe = len(concepts_with_probes & supported_concepts)
    provisional_with_probe = len(concepts_with_probes & provisional_concepts)
    return {
        "total": sum(status_counter.values()),
        "by_review_status": dict(status_counter),
        "by_status": dict(status_counter),
        "approved": status_counter.get("approved", 0),
        "concepts_with_approved": len(concepts_with_approved),
        "concepts_without_approved": concepts_without_approved,
        "coverage": {
            "supported_with_probe": supported_with_probe,
            "supported_total": len(supported_concepts),
            "provisional_with_probe": provisional_with_probe,
            "provisional_total": len(provisional_concepts),
        },
    }


def _score_eval_runs() -> dict:
    """Summarise the most recent data/eval_runs/*.jsonl file."""
    _CATASTROPHIC = {"fabricated-citation", "wrong-source", "contradicted-by-source"}

    if not _EVAL_RUNS_DIR.exists():
        return {
            "latest_run": None,
            "catastrophic_failure_rate": None,
            "pass_rate_by_mode": {},
        }

    run_files = sorted(_EVAL_RUNS_DIR.glob("*.jsonl"))
    if not run_files:
        return {
            "latest_run": None,
            "catastrophic_failure_rate": None,
            "pass_rate_by_mode": {},
        }

    latest = run_files[-1]
    latest_date = latest.stem  # YYYYMMDD

    records: list[dict] = []
    try:
        for line in latest.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass

    if not records:
        return {
            "latest_run": latest_date,
            "catastrophic_failure_rate": None,
            "pass_rate_by_mode": {},
        }

    # Catastrophic failure rate: share of probes (by probe_id) where ANY mode
    # produced a catastrophic failure.
    probe_ids = list({r["probe_id"] for r in records})
    catastrophic_probes = {r["probe_id"] for r in records if r.get("result") in _CATASTROPHIC}
    catastrophic_rate = round(len(catastrophic_probes) / len(probe_ids), 3) if probe_ids else None

    # Pass rate by mode
    pass_rate_by_mode: dict[str, float | None] = {}
    modes = sorted({r.get("mode", "") for r in records} - {""})
    for mode in modes:
        mode_records = [r for r in records if r.get("mode") == mode]
        if mode_records:
            passed = sum(1 for r in mode_records if r.get("result") == "pass")
            pass_rate_by_mode[mode] = round(passed / len(mode_records), 3)
        else:
            pass_rate_by_mode[mode] = None

    return {
        "latest_run": latest_date,
        "catastrophic_failure_rate": catastrophic_rate,
        "pass_rate_by_mode": pass_rate_by_mode,
    }


def _score_research() -> dict:
    if not _RESEARCH_DIR.exists():
        return {"active": 0, "by_phase": {}, "archived": 0}
    phase_counter: Counter = Counter()
    active = (
        list((_RESEARCH_DIR / "notes").glob("*-status.md"))
        if (_RESEARCH_DIR / "notes").exists()
        else []
    )
    archived = (
        list((_RESEARCH_DIR / "archive").rglob("*-status.md"))
        if (_RESEARCH_DIR / "archive").exists()
        else []
    )
    for path in active:
        frontmatter, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        phase_counter[str(frontmatter.get("phase") or "unknown")] += 1
    return {"active": len(active), "by_phase": dict(phase_counter), "archived": len(archived)}


def _compute_signals(
    concepts: dict,
    sources: dict,
    claims: dict,
    answers: dict,
    contradictions: dict | None = None,
    probes: dict | None = None,
    graph_topo: dict | None = None,
) -> list[dict]:
    signals: list[dict] = []

    if sources["total"] > 0:
        if (sources["stub_fraction"] or 0.0) > 0.3:
            signals.append(
                {
                    "code": "high-stub-fraction",
                    "severity": "warning",
                    "message": f"{sources['stub_fraction']:.0%} of sources are stubs/citation-only (>30% threshold)",
                }
            )
        if (sources["primary_fraction"] or 1.0) < 0.2 and sources["total"] >= 5:
            signals.append(
                {
                    "code": "low-primary-coverage",
                    "severity": "warning",
                    "message": f"Only {sources['primary_fraction']:.0%} of sources are primary/official (want ≥20%)",
                }
            )
        model_frac = sources["model_generated_count"] / sources["total"]
        if model_frac > 0.5:
            signals.append(
                {
                    "code": "model-report-dominance",
                    "severity": "warning",
                    "message": f"{model_frac:.0%} of sources are model-generated — verify against primary sources",
                }
            )

    if concepts["revalidation_required"] > 0:
        signals.append(
            {
                "code": "revalidation-backlog",
                "severity": "warning",
                "message": f"{concepts['revalidation_required']} concept(s) are flagged for revalidation; run 'stale-impact' to review, 'clear-stale-flags' when done",
            }
        )

    if concepts["conflicting_without_open_questions"] > 0:
        signals.append(
            {
                "code": "undocumented-conflicts",
                "severity": "warning",
                "message": f"{concepts['conflicting_without_open_questions']} concept(s) have claim_quality: conflicting without an ## Open Questions section",
            }
        )

    if claims["total"] > 0 and claims["with_sources"] == 0:
        signals.append(
            {
                "code": "claims-without-sources",
                "severity": "warning",
                "message": "Claim registry contains no source-linked claims",
            }
        )
    if claims["total"] > 0 and claims.get("inherited", 0) > 0:
        signals.append(
            {
                "code": "inherited-claim-evidence",
                "severity": "warning",
                "message": f"{claims['inherited']} claim(s) rely on page-level inherited evidence",
            }
        )
    if claims.get("unsupported", 0) > 0:
        signals.append(
            {
                "code": "unsupported-claims",
                "severity": "warning",
                "message": f"{claims['unsupported']} claim(s) have no direct or page-level source evidence",
            }
        )
    if claims.get("quarantined", 0) > 0:
        signals.append(
            {
                "code": "quarantined-claims",
                "severity": "warning",
                "message": f"{claims['quarantined']} claim(s) depend on weak, synthetic, deprecated, or unverified sources",
            }
        )
    if claims.get("blocked", 0) > 0:
        signals.append(
            {
                "code": "blocked-claims",
                "severity": "error",
                "message": f"{claims['blocked']} claim(s) depend on revoked, do-not-use, or adversarial sources",
            }
        )

    if answers["revalidation_required"] > 0:
        signals.append(
            {
                "code": "answer-revalidation-backlog",
                "severity": "warning",
                "message": f"{answers['revalidation_required']} answer(s) are flagged for revalidation",
            }
        )

    if graph_topo and graph_topo.get("available"):
        orphan_rate = graph_topo.get("orphaned_source_rate", 0)
        if orphan_rate > 0.5:
            signals.append(
                {
                    "code": "orphaned-sources",
                    "severity": "warning",
                    "message": (
                        f"{graph_topo['orphaned_sources']} source(s) ({orphan_rate:.0%}) have no inbound"
                        " citations — run build-graph after adding inline citations"
                    ),
                }
            )
        if graph_topo.get("isolated_concepts", 0) > 0:
            signals.append(
                {
                    "code": "isolated-concepts",
                    "severity": "warning",
                    "message": (
                        f"{graph_topo['isolated_concepts']} concept(s) have no graph connections"
                        " — add Related Concepts wikilinks"
                    ),
                }
            )
        if graph_topo.get("isolated_answers", 0) > 0:
            signals.append(
                {
                    "code": "isolated-answers",
                    "severity": "info",
                    "message": (
                        f"{graph_topo['isolated_answers']} answer(s) have no outbound concept links"
                        " — add Vault Updates section or archive"
                    ),
                }
            )

    if contradictions and contradictions.get("undocumented", 0) > 0:
        signals.append(
            {
                "code": "undocumented-contradictions",
                "severity": "warning",
                "message": f"{contradictions['undocumented']} conflicting concept(s) have no Open Questions bullet — run 'extract-contradictions' then add an ## Open Questions section",
            }
        )

    if probes:
        unreviewed = (probes.get("by_status") or {}).get("unreviewed", 0)
        if unreviewed > 0:
            signals.append(
                {
                    "code": "unreviewed-probes",
                    "severity": "warning",
                    "message": f"{unreviewed} probe(s) are unreviewed — run the Probe Review checklist before counting toward probe_coverage_by_concept_quality",
                }
            )
        no_approved = probes.get("concepts_without_approved") or []
        if no_approved:
            signals.append(
                {
                    "code": "concepts-without-approved-probes",
                    "severity": "warning",
                    "message": f"{len(no_approved)} concept(s) have no approved probes: {', '.join(no_approved[:5])}{'...' if len(no_approved) > 5 else ''}",
                }
            )

    return signals


def compute_scorecard() -> dict:
    concepts = _score_concepts()
    indexes = _score_indexes()
    sources = _score_sources()
    claims = _score_claims()
    answers = _score_answers()
    contradictions = _score_contradictions()
    probes = _score_probes()
    research = _score_research()
    eval_runs = _score_eval_runs()
    schema_compliance = _score_schema_compliance()
    graph_topo = _score_graph_topology()
    signals = _compute_signals(concepts, sources, claims, answers, contradictions, probes, graph_topo)
    # Add schema-drift health signal
    err_count = schema_compliance.get("error_count", 0)
    if err_count > 200:
        signals.append(
            {
                "code": "schema-drift-critical",
                "severity": "error",
                "message": f"{err_count} schema violations detected — run 'kb.py migrate-source-fields' then 'validate --strict'",
            }
        )
    elif err_count > 50:
        signals.append(
            {
                "code": "schema-drift",
                "severity": "warning",
                "message": f"{err_count} schema violations detected — run 'validate --strict' to review",
            }
        )
    # Load evaluation stats from research/evals/evaluation-results.jsonl if they exist
    evals_path = ROOT / "research" / "evals" / "evaluation-results.jsonl"
    eval_pass_rate = None
    catastrophic_failure_count = 0
    if evals_path.exists():
        try:
            records = []
            for line in evals_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    records.append(json.loads(line))
            if records:
                passed = sum(1 for r in records if r.get("pass_fail") is True)
                eval_pass_rate = round(passed / len(records), 3)
                catastrophic_failure_count = sum(
                    1
                    for r in records
                    if any(
                        reason in r.get("failure_reasons", [])
                        for reason in ("contradiction_missed", "unsupported_claim")
                    )
                )
        except Exception:
            pass

    return {
        "project": CONFIG.project_name,
        "generated_at": dt.datetime.now().replace(microsecond=0).isoformat(),
        "eval_pass_rate": eval_pass_rate,
        "catastrophic_failure_count": catastrophic_failure_count,
        "concepts": concepts,
        "indexes": indexes,
        "sources": sources,
        "claims": claims,
        "answers": answers,
        "probes": probes,
        "research": research,
        "contradictions": contradictions,
        "schema_compliance": schema_compliance,
        "graph_topology": graph_topo,
        "eval": eval_runs,
        "health_signals": signals,
    }


def is_scorecard_equal(s1: dict, s2: dict) -> bool:
    # Compare keys except generated_at
    keys1 = set(s1.keys()) - {"generated_at"}
    keys2 = set(s2.keys()) - {"generated_at"}
    if keys1 != keys2:
        return False
    for k in keys1:
        if s1[k] != s2[k]:
            return False
    return True


def run(output: str | None = None, check: bool = False, dry_run: bool = False) -> dict:
    scorecard = compute_scorecard()
    output_path = Path(output).resolve() if output else SCORECARD_PATH
    ensure_dir(output_path.parent)

    out_of_sync = True
    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            if is_scorecard_equal(existing, scorecard):
                out_of_sync = False
        except Exception:
            pass

    if out_of_sync:
        if check:
            print("Scorecard is out of sync!")
            import sys

            sys.exit(1)
        elif dry_run:
            print(f"[DRY-RUN] Scorecard would be updated: {output_path}")
        else:
            content = json.dumps(scorecard, indent=2, ensure_ascii=False) + "\n"
            output_path.write_text(content, encoding="utf-8")
            print(f"Scorecard updated: {output_path}")
    else:
        print(f"Scorecard unchanged: {output_path}")

    return scorecard


def print_summary(scorecard: dict) -> None:
    c = scorecard["concepts"]
    i = scorecard.get("indexes", {})
    s = scorecard["sources"]
    cl = scorecard["claims"]
    a = scorecard["answers"]
    r = scorecard["research"]
    ct = scorecard.get("contradictions", {})

    print(f"\n=== {scorecard['project']} Vault Scorecard ({scorecard['generated_at']}) ===\n")
    print("Concepts")
    print(
        f"  total: {c['total']}  |  by claim quality: {', '.join(f'{k}:{v}' for k, v in sorted(c['by_claim_quality'].items()))}"
    )
    print(
        f"  evidence status: {', '.join(f'{k}:{v}' for k, v in sorted((c.get('by_evidence_status') or {}).items()))}"
    )
    print(
        f"  unsupported: {c['unsupported']}  |  revalidation backlog: {c['revalidation_required']}"
    )
    print(f"  conflicting without Open Questions: {c['conflicting_without_open_questions']}")
    print(f"  depending on partial sources: {c.get('partial_source_dependencies', 0)}")
    if c["claim_bullets_total"]:
        print(
            f"  claim bullets with inline citation: {c['claim_bullets_with_inline_citation']}/{c['claim_bullets_total']} ({c['inline_citation_rate']:.0%})"
        )

    print("\nIndexes")
    print(
        f"  total: {i.get('total', 0)}  |  by type: {', '.join(f'{k}:{v}' for k, v in sorted((i.get('by_type') or {}).items()))}"
    )

    print("\nSources")
    print(
        f"  total: {s['total']}  |  primary fraction: {s['primary_fraction'] if s['primary_fraction'] is not None else 'n/a'}  |  stub fraction: {s['stub_fraction'] if s['stub_fraction'] is not None else 'n/a'}"
    )
    print(f"  partial sources: {s.get('partial_source_count', 0)}")
    print(
        f"  by evidence strength: {', '.join(f'{k}:{v}' for k, v in sorted(s['by_evidence_strength'].items()))}"
    )

    print("\nClaims")
    print(
        f"  total: {cl['total']}  |  with sources: {cl['with_sources']}  |  without sources: {cl['without_sources']}"
    )
    if cl.get("direct_citation_rate") is not None:
        print(
            "  direct evidence: "
            f"{cl.get('direct', 0)} direct, {cl.get('inherited', 0)} inherited, "
            f"{cl.get('unsupported', 0)} unsupported "
            f"({cl['direct_citation_rate']:.0%} direct)"
        )
    if cl.get("by_admission_status"):
        print(
            "  admission status: "
            + ", ".join(
                f"{k}:{v}" for k, v in sorted((cl.get("by_admission_status") or {}).items())
            )
        )
    _sac = cl.get("source_section_anchor_coverage")
    _lsbc = cl.get("long_source_bare_citation_count", 0)
    print(
        f"  section-anchor coverage (v2-manifest sources): "
        f"{'n/a' if _sac is None else f'{_sac:.1%}'}  |  "
        f"bare citations to v2-manifest sources: {_lsbc}"
    )

    print("\nAnswers")
    print(
        f"  total: {a['total']}  |  with provenance: {a['with_provenance']}  |  revalidation backlog: {a['revalidation_required']}"
    )

    print("\nResearch")
    print(
        f"  active: {r['active']}  |  archived: {r['archived']}  |  by phase: {', '.join(f'{k}:{v}' for k, v in sorted(r['by_phase'].items()))}"
    )

    print("\nContradictions")
    print(
        f"  total: {ct.get('total', 0)}  |  documented: {ct.get('documented', 0)}  |  undocumented: {ct.get('undocumented', 0)}"
    )

    pr = scorecard.get("probes", {})
    if pr:
        print("\nProbes")
        by_status = pr.get("by_status") or {}
        print(
            f"  total: {pr.get('total', 0)}  |  "
            + "  ".join(f"{k}:{v}" for k, v in sorted(by_status.items()))
        )
        no_approved = pr.get("concepts_without_approved") or []
        if no_approved:
            print(f"  concepts without approved probes: {len(no_approved)}")
        # Note: only approved probes count toward probe_coverage_by_concept_quality
        approved = pr.get("approved", 0)
        print(f"  approved (count toward coverage): {approved}")

    print("\nEvaluation")
    print(
        f"  pass rate: {scorecard.get('eval_pass_rate') if scorecard.get('eval_pass_rate') is not None else 'n/a'}  |  catastrophic failures: {scorecard.get('catastrophic_failure_count', 0)}"
    )
    ev = scorecard.get("eval") or {}
    if ev.get("latest_run"):
        print(f"\nEval Runs (latest: {ev['latest_run']})")
        cfr = ev.get("catastrophic_failure_rate")
        print(f"  catastrophic_failure_rate: {cfr if cfr is not None else 'n/a'}")
        pbm = ev.get("pass_rate_by_mode") or {}
        for mode, rate in sorted(pbm.items()):
            print(f"  pass_rate[{mode}]: {rate if rate is not None else 'n/a'}")

    if scorecard["health_signals"]:
        print("\nHealth signals")
        for signal in scorecard["health_signals"]:
            print(f"  - [{signal['severity']}] {signal['code']}: {signal['message']}")
    else:
        print("\nHealth signals: none")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Compute vault health scorecard.")
    parser.add_argument("--output", help="Override output path.")
    parser.add_argument("--check", action="store_true", help="Fail if scorecard is out of sync.")
    parser.add_argument("--dry-run", action="store_true", help="Run without mutating files.")
    args = parser.parse_args()
    scorecard = run(output=args.output, check=args.check, dry_run=args.dry_run)
    print_summary(scorecard)


if __name__ == "__main__":
    main()
