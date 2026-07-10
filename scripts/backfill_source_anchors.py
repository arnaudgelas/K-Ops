"""T5: Source-span anchor backfill for data/claims.json.

Strategy:
- github_repo_snapshot: fill commit from repo_manifest.json, mark partial-anchor.
- All source kinds with extracted text: find a verbatim supporting span in
  normalized.md (or the best raw text fallback) and store char offsets + quote.
- url/file/web-page/website/article/preprint: retain heading fallback when no
  reliable verbatim span is found.
- PDF/arxiv-paper without extracted text: mark missing-pdf-anchor.
- Claims with no source_anchors get them created from source_ids.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).parent.parent
CLAIMS_PATH = ROOT / "data" / "claims.json"
REGISTRY_PATH = ROOT / "data" / "registry.json"
RAW_DIR = ROOT / "data" / "raw"

HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
PATH_RE = re.compile(
    r"(?<![\w/.-])("
    r"(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.(?:md|mdx|py|ts|tsx|js|jsx|rs|go|json|ya?ml|toml|sh|rb|java|c|cc|cpp|h|hpp|proto|sql|tf|txt)"
    r"|Dockerfile|Makefile|LICENSE|README(?:\.md)?"
    r")"
)
QUOTE_PATH_RE = re.compile(r"(?:^|\n)-?\s*Path:\s*`([^`]+)`")

GITHUB_KINDS = {"github_repo_snapshot", "github-repo-snapshot"}
PDF_KINDS = {"paper-pdf", "arxiv-paper", "preprint"}
TEXT_KINDS = {"url", "file", "web-page", "website", "article", "blog", "document", "repo"}
SPAN_SOURCE_KINDS = GITHUB_KINDS | PDF_KINDS | TEXT_KINDS | {""}
MAX_QUOTE_CHARS = 900
MIN_SPAN_SCORE = 4.0
MIN_CLAIM_WORD_COVERAGE = 0.18
STOPWORDS = {
    "that",
    "this",
    "with",
    "from",
    "have",
    "been",
    "they",
    "their",
    "which",
    "when",
    "will",
    "than",
    "more",
    "also",
    "into",
    "some",
    "used",
    "uses",
    "using",
    "through",
    "these",
    "those",
    "both",
    "about",
    "such",
    "each",
    "only",
    "over",
    "can",
    "are",
    "for",
    "the",
    "and",
    "not",
    "but",
    "its",
    "may",
    "all",
    "any",
    "within",
    "onto",
}


def _read_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _load_repo_manifest(src_id: str) -> dict:
    path = RAW_DIR / src_id / "repo_manifest.json"
    return _read_json(path)


def _load_raw_metadata(src_id: str) -> dict:
    return _read_json(RAW_DIR / src_id / "metadata.json")


def _load_normalized_headings(src_id: str) -> list[str]:
    path = RAW_DIR / src_id / "normalized.md"
    if not path.exists():
        # Try original.md as fallback
        path = RAW_DIR / src_id / "original.md"
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return HEADING_RE.findall(text)
    except Exception:
        return []


def _keyword_match(claim_text: str, headings: list[str]) -> str | None:
    """Return the best matching heading for a claim text using keyword overlap."""
    if not headings or not claim_text:
        return None
    # Extract meaningful words from claim text (>3 chars, not stopwords)
    claim_words = _claim_words(claim_text)
    if not claim_words:
        return None
    best_heading = None
    best_score = 0
    for h in headings:
        h_words = set(w.lower() for w in re.findall(r"[a-zA-Z]{4,}", h))
        score = len(claim_words & h_words)
        if score > best_score:
            best_score = score
            best_heading = h
    # Only use if there's at least one keyword match
    return best_heading if best_score >= 1 else None


def _claim_words(claim_text: str) -> set[str]:
    return {
        w.lower()
        for w in re.findall(r"[a-zA-Z]{4,}", claim_text or "")
        if w.lower() not in STOPWORDS
    }


def _normalize_match_text(value: str) -> str:
    """Normalize text for candidate scoring without changing stored quotes."""
    value = unicodedata.normalize("NFKC", value or "").lower()
    value = value.replace("’", "'").replace("‘", "'")
    value = value.replace("“", '"').replace("”", '"')
    value = re.sub(r"[\u2010-\u2015]", "-", value)
    return value


def _claim_terms(claim_text: str) -> list[str]:
    normalized = _normalize_match_text(claim_text)
    return [w for w in re.findall(r"[a-z0-9][a-z0-9_+-]{2,}", normalized) if w not in STOPWORDS]


def _source_text_path(src_id: str, src_info: dict) -> Path | None:
    metadata = _load_raw_metadata(src_id)
    candidates: list[str] = []
    for key in ("normalized_path", "original_path"):
        value = metadata.get(key) or src_info.get(key)
        if value:
            candidates.append(value)

    raw_root = RAW_DIR / src_id
    candidates.extend(
        [
            str(raw_root / "normalized.md"),
            str(raw_root / "original.md"),
        ]
    )
    candidates.extend(str(path) for path in sorted(raw_root.glob("original.*")))

    for candidate in candidates:
        path = Path(candidate)
        if not path.is_absolute():
            path = ROOT / path
        if path.exists() and path.is_file():
            return path
    return None


def _load_source_text(src_id: str, src_info: dict) -> tuple[str, str | None]:
    path = _source_text_path(src_id, src_info)
    if path is None:
        return "", None
    try:
        return path.read_text(encoding="utf-8", errors="ignore"), str(path.relative_to(ROOT))
    except Exception:
        return "", str(path)


def _iter_sentence_spans(text: str, start: int, end: int):
    segment = text[start:end]
    cursor = 0
    for match in re.finditer(r"[^.!?\n]+(?:[.!?]+|$)", segment):
        raw = match.group(0)
        if not raw.strip():
            continue
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw.rstrip())
        span_start = start + match.start() + leading
        span_end = start + match.start() + trailing
        if span_end > span_start:
            yield span_start, span_end
        cursor = match.end()
    if cursor == 0 and segment.strip():
        leading = len(segment) - len(segment.lstrip())
        trailing = len(segment.rstrip())
        yield start + leading, start + trailing


def _iter_candidate_spans(text: str):
    """Yield exact source-text spans suitable for quotes."""
    for match in re.finditer(r"\S[\s\S]*?(?=\n\s*\n|\Z)", text):
        raw = match.group(0)
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw.rstrip())
        start = match.start() + leading
        end = match.start() + trailing
        if end <= start:
            continue

        if end - start <= MAX_QUOTE_CHARS:
            yield start, end
            continue

        line_spans = []
        for line_match in re.finditer(r"[^\n]+", text[start:end]):
            line = line_match.group(0)
            if not line.strip():
                continue
            line_start = start + line_match.start() + len(line) - len(line.lstrip())
            line_end = start + line_match.start() + len(line.rstrip())
            if line_end > line_start:
                line_spans.append((line_start, line_end))

        if line_spans and max(e - s for s, e in line_spans) <= MAX_QUOTE_CHARS:
            yield from line_spans
        else:
            yield from _iter_sentence_spans(text, start, end)


def _score_span(claim_text: str, quote: str) -> tuple[float, float]:
    claim_terms = _claim_terms(claim_text)
    if not claim_terms:
        return 0.0, 0.0
    quote_norm = _normalize_match_text(quote)
    quote_terms = set(_claim_terms(quote))
    claim_term_set = set(claim_terms)
    overlap = claim_term_set & quote_terms
    coverage = len(overlap) / max(len(claim_term_set), 1)

    score = float(len(overlap))
    for term in overlap:
        if re.search(rf"\b{re.escape(term)}\b", quote_norm):
            score += 0.15
    if any(ch.isdigit() for ch in quote) and any(ch.isdigit() for ch in claim_text):
        score += 0.75
    if any(ch in quote for ch in "`/_.-") and any(ch in claim_text for ch in "`/_.-"):
        score += 0.5
    if len(quote) > MAX_QUOTE_CHARS:
        score -= 2.0
    return score, coverage


def _find_verbatim_span(claim_text: str, source_text: str) -> dict | None:
    """Select a source span, then return exact offsets and quote.

    Selection is heuristic, but the returned quote is always a verbatim slice of
    source_text and can be mechanically verified with char_start/char_end.
    """
    if not claim_text or not source_text:
        return None

    claim = claim_text.strip()
    exact_pos = source_text.find(claim)
    if exact_pos >= 0:
        return {
            "char_start": exact_pos,
            "char_end": exact_pos + len(claim),
            "quote": source_text[exact_pos : exact_pos + len(claim)],
            "extraction_confidence": "exact-claim",
        }

    best: tuple[float, float, int, int] | None = None
    for start, end in _iter_candidate_spans(source_text):
        quote = source_text[start:end].strip()
        if len(quote) < 24:
            continue
        score, coverage = _score_span(claim_text, quote)
        if score < MIN_SPAN_SCORE or coverage < MIN_CLAIM_WORD_COVERAGE:
            continue
        candidate = (score, coverage, start, end)
        if best is None or candidate[:2] > best[:2]:
            best = candidate

    if best is None:
        return None

    score, coverage, start, end = best
    quote = source_text[start:end]
    confidence = "verbatim-high" if coverage >= 0.35 and score >= 7 else "verbatim-medium"
    return {
        "char_start": start,
        "char_end": end,
        "quote": quote,
        "extraction_confidence": confidence,
    }


def _extract_path_from_quote(quote: str | None) -> str | None:
    if not quote:
        return None
    match = QUOTE_PATH_RE.search(quote)
    return match.group(1) if match else None


def _tokenize_path(path: str) -> set[str]:
    parts = re.split(r"[./_-]+", path.lower())
    return {part for part in parts if len(part) >= 3 and part not in STOPWORDS}


def _load_source_note(src_info: dict) -> str:
    note_path = src_info.get("notes_path")
    if note_path:
        path = ROOT / note_path
        if path.exists():
            try:
                return path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass
    return ""


def _extract_repo_path_candidates(
    note_text: str, sampled_paths: list[str]
) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    if note_text:
        for line in note_text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("-"):
                continue
            body = stripped.lstrip("-").strip()
            m = PATH_RE.match(body)
            if m:
                path = m.group(1)
                if path not in seen:
                    candidates.append((path, body))
                    seen.add(path)
            for match in PATH_RE.finditer(body):
                path = match.group(1)
                if path not in seen:
                    candidates.append((path, body))
                    seen.add(path)
    for path in sampled_paths:
        if path not in seen:
            candidates.append((path, ""))
            seen.add(path)
    return candidates


def _score_repo_candidate(claim_text: str, candidate_path: str, candidate_context: str) -> int:
    claim_terms = _claim_words(claim_text)
    if not claim_terms:
        return 0
    score = len(claim_terms & _tokenize_path(candidate_path))
    if candidate_context:
        score += len(claim_terms & _claim_words(candidate_context))
    # Prefer concrete evidence files over top-level docs when scores tie.
    if "/" in candidate_path:
        score += 1
    if candidate_path.lower().startswith(("readme", "docs/", "doc/")):
        score += 1
    return score


def _serialize_anchor_fields(anchor: dict) -> str | None:
    parts: list[str] = []
    if anchor.get("char_start") is not None and anchor.get("char_end") is not None:
        parts.append(f"char_start={anchor['char_start']}")
        parts.append(f"char_end={anchor['char_end']}")
    if anchor.get("section"):
        parts.append(f"section={anchor['section']}")
    if anchor.get("page") is not None:
        parts.append(f"page={anchor['page']}")
    if anchor.get("paragraph") is not None:
        parts.append(f"paragraph={anchor['paragraph']}")
    if anchor.get("path"):
        parts.append(f"path={anchor['path']}")
    if anchor.get("source_text_path"):
        parts.append(f"source_text_path={anchor['source_text_path']}")
    if anchor.get("commit"):
        parts.append(f"commit={anchor['commit']}")
    if anchor.get("line_start") is not None:
        parts.append(f"line_start={anchor['line_start']}")
    if anchor.get("line_end") is not None:
        parts.append(f"line_end={anchor['line_end']}")
    if anchor.get("segment_id"):
        parts.append(f"segment_id={anchor['segment_id']}")
    return "&".join(parts) or None


def _make_blank_anchor(src_id: str) -> dict:
    return {
        "source_id": src_id,
        "anchor": None,
        "page": None,
        "section": None,
        "paragraph": None,
        "quote": None,
        "char_start": None,
        "char_end": None,
        "source_text_path": None,
        "path": None,
        "line_start": None,
        "line_end": None,
        "commit": None,
        "extraction_confidence": None,
        "segment_id": None,
    }


def backfill(claims_data: dict, registry: list[dict]) -> dict:
    reg_by_id = {r["id"]: r for r in registry}
    # Cache for manifests and headings (avoid re-reading per claim)
    manifest_cache: dict[str, dict] = {}
    headings_cache: dict[str, list[str]] = {}
    text_cache: dict[str, tuple[str, str | None]] = {}
    source_note_cache: dict[str, str] = {}
    repo_path_cache: dict[str, list[tuple[str, str]]] = {}

    claims = claims_data["claims"]
    pre_anchored = sum(1 for c in claims if c.get("span_status") != "missing")

    for claim in claims:
        claim_text = claim.get("claim_text") or claim.get("text") or ""

        # Build source_anchors from source_ids if empty
        if not claim.get("source_anchors"):
            src_ids = claim.get("source_ids") or []
            claim["source_anchors"] = [_make_blank_anchor(sid) for sid in src_ids]

        for sa in claim["source_anchors"]:
            src_id = sa.get("source_id")
            if not src_id:
                continue
            src_info = reg_by_id.get(src_id, {})
            kind = src_info.get("kind", "")

            if kind in SPAN_SOURCE_KINDS:
                if src_id not in text_cache:
                    text_cache[src_id] = _load_source_text(src_id, src_info)
                source_text, source_text_path = text_cache[src_id]

                existing_quote = sa.get("quote")
                if existing_quote and source_text:
                    quote_start = source_text.find(existing_quote)
                    if quote_start >= 0:
                        sa["char_start"] = quote_start
                        sa["char_end"] = quote_start + len(existing_quote)
                        sa["extraction_confidence"] = (
                            sa.get("extraction_confidence") or "existing-verbatim"
                        )
                        if source_text_path:
                            sa["source_text_path"] = source_text_path
                        quote_path = _extract_path_from_quote(existing_quote)
                        if quote_path:
                            sa["path"] = quote_path
                elif not existing_quote and source_text:
                    span = _find_verbatim_span(claim_text, source_text)
                    if span:
                        sa["char_start"] = span["char_start"]
                        sa["char_end"] = span["char_end"]
                        sa["quote"] = span["quote"]
                        sa["extraction_confidence"] = span["extraction_confidence"]
                        if source_text_path:
                            sa["source_text_path"] = source_text_path
                        quote_path = _extract_path_from_quote(span["quote"])
                        if quote_path:
                            sa["path"] = quote_path
                        sa["anchor"] = _serialize_anchor_fields(sa)

            if kind in GITHUB_KINDS:
                # Load manifest
                if src_id not in manifest_cache:
                    manifest_cache[src_id] = _load_repo_manifest(src_id)
                manifest = manifest_cache[src_id]
                commit = manifest.get("git_commit") or src_info.get("git_commit")
                if commit and commit != "unknown":
                    if not sa.get("commit"):
                        sa["commit"] = commit
                    if not sa.get("path"):
                        if src_id not in source_note_cache:
                            source_note_cache[src_id] = _load_source_note(src_info)
                        if src_id not in repo_path_cache:
                            repo_path_cache[src_id] = _extract_repo_path_candidates(
                                source_note_cache[src_id], manifest.get("sampled_paths", [])
                            )
                        candidates = repo_path_cache[src_id]
                        best_path = None
                        best_score = -1
                        for candidate_path, candidate_context in candidates:
                            score = _score_repo_candidate(
                                claim_text, candidate_path, candidate_context
                            )
                            if score > best_score:
                                best_score = score
                                best_path = candidate_path
                        if best_path and best_score > 0:
                            sa["path"] = best_path
                    if not sa.get("anchor"):
                        sa["anchor"] = _serialize_anchor_fields(sa)
                    # Commit/path set; span_status determined below from has_commit

            elif kind in PDF_KINDS:
                # Span matching above handles PDFs/arXiv sources with extracted
                # normalized text. Sources without extracted text are handled by
                # the claim-level missing-pdf-anchor status below.
                # span_status handled at claim level
                pass

            elif kind in TEXT_KINDS or kind == "":
                # Try to find heading in normalized.md
                if src_id not in headings_cache:
                    headings_cache[src_id] = _load_normalized_headings(src_id)
                headings = headings_cache[src_id]
                if headings:
                    best = _keyword_match(claim_text, headings)
                    if best and not sa.get("section"):
                        sa["section"] = best
                if not sa.get("anchor"):
                    sa["anchor"] = _serialize_anchor_fields(sa)

            if (
                sa.get("quote")
                and sa.get("char_start") is not None
                and sa.get("char_end") is not None
            ):
                sa["anchor"] = _serialize_anchor_fields(sa)

        # Determine span_status for this claim
        # Check per-anchor after processing
        has_exact_span = any(
            sa.get("quote") and sa.get("char_start") is not None and sa.get("char_end") is not None
            for sa in claim["source_anchors"]
        )
        all_exact_span = (
            all(
                sa.get("quote")
                and sa.get("char_start") is not None
                and sa.get("char_end") is not None
                for sa in claim["source_anchors"]
            )
            and claim["source_anchors"]
        )
        has_commit = any(sa.get("commit") for sa in claim["source_anchors"])
        has_section = any(sa.get("section") for sa in claim["source_anchors"])
        has_path = any(sa.get("path") for sa in claim["source_anchors"])
        all_sources_pdf = (
            all(
                reg_by_id.get(sa.get("source_id", ""), {}).get("kind", "") in PDF_KINDS
                for sa in claim["source_anchors"]
                if sa.get("source_id")
            )
            and claim["source_anchors"]
        )

        if all_exact_span:
            claim["span_status"] = "exact-span"
        elif has_exact_span:
            claim["span_status"] = "partial-span"
        elif has_commit and has_path and has_section:
            claim["span_status"] = "partial-anchor"
        elif has_commit and has_path:
            claim["span_status"] = "partial-anchor"
        elif has_section:
            claim["span_status"] = "heading-anchor"
        elif all_sources_pdf:
            claim["span_status"] = "missing-pdf-anchor"
        else:
            claim["span_status"] = "missing"

    post_anchored = sum(1 for c in claims if c.get("span_status") != "missing")
    print(f"Pre-backfill non-missing: {pre_anchored}")
    print(f"Post-backfill non-missing: {post_anchored}")

    from collections import Counter

    dist = Counter(c.get("span_status", "") for c in claims)
    print(f"span_status distribution: {dict(dist)}")

    claims_data["claims"] = claims
    return claims_data


def main():
    with open(CLAIMS_PATH) as f:
        claims_data = json.load(f)
    with open(REGISTRY_PATH) as f:
        registry = json.load(f)

    updated = backfill(claims_data, registry)

    with open(CLAIMS_PATH, "w") as f:
        json.dump(updated, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Written {CLAIMS_PATH}")


if __name__ == "__main__":
    main()
