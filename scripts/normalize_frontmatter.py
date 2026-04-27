from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from utils import CONFIG, ROOT, parse_frontmatter

FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
TAG_RE = re.compile(r"^tags:\s*\n((?:  -[^\n]*\n?)+)", re.MULTILINE)
TAG_LINE_RE = re.compile(r"^\s*-\s+(.+)$", re.MULTILINE)

VALID_CLAIM_QUALITIES = {"supported", "provisional", "weak", "conflicting", "stale"}
VALID_CONCEPT_TYPES = {"concept", "redirect", "index", "stub"}

_KB_NAMESPACE_MAP = {
    "concept": "kb/concept",
    "source": "kb/source",
    "answer": "kb/answer",
    "index": "kb/index",
    "redirect": "kb/redirect",
}


def _normalize_tags(raw_tags: list[str], page_type: str) -> list[str]:
    out = []
    for tag in raw_tags:
        tag = tag.strip()
        if not tag:
            continue
        # Ensure kb/ namespace for kb-typed tags
        if tag in _KB_NAMESPACE_MAP:
            tag = _KB_NAMESPACE_MAP[tag]
        out.append(tag)
    # Ensure the type tag is present
    if page_type and page_type in _KB_NAMESPACE_MAP:
        ns_tag = _KB_NAMESPACE_MAP[page_type]
        if ns_tag not in out:
            out.insert(0, ns_tag)
    return sorted(set(out))


def _add_updated_timestamp(text: str, mtime: float) -> str:
    dt = datetime.utcfromtimestamp(mtime).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Already present?
    if re.search(r"^updated:", text, re.MULTILINE):
        return text
    # Insert after ingested_at or created or title
    for anchor in ("ingested_at:", "created:", "title:"):
        m = re.search(rf"^{re.escape(anchor)}[^\n]*\n", text, re.MULTILINE)
        if m:
            return text[: m.end()] + f"updated: {dt}\n" + text[m.end() :]
    # Insert at end of frontmatter
    return text


def normalize_file(path: Path, dry_run: bool = False) -> bool:
    text = path.read_text(encoding="utf-8")
    fm_match = FRONT_RE.match(text)
    if not fm_match:
        return False

    fm_block = fm_match.group(1)
    body = text[fm_match.end():]
    changed = False

    # Parse type
    type_m = re.search(r"^type:\s*(\S+)", fm_block, re.MULTILINE)
    page_type = type_m.group(1).strip('"\'') if type_m else ""

    # Normalize claim_quality
    cq_m = re.search(r"^claim_quality:\s*(.+)$", fm_block, re.MULTILINE)
    if cq_m:
        cq_raw = cq_m.group(1).strip().strip('"\'')
        if cq_raw in VALID_CLAIM_QUALITIES and cq_raw != cq_m.group(1).strip():
            fm_block = fm_block[:cq_m.start(1)] + cq_raw + fm_block[cq_m.end(1):]
            changed = True

    # Normalize tags
    tag_m = TAG_RE.search(fm_block)
    if tag_m:
        raw_tags = TAG_LINE_RE.findall(tag_m.group(1))
        normalized = _normalize_tags(raw_tags, page_type)
        new_tag_block = "tags:\n" + "".join(f"  - {t}\n" for t in normalized)
        if new_tag_block != "tags:\n" + tag_m.group(1):
            fm_block = fm_block[:tag_m.start()] + new_tag_block + fm_block[tag_m.end():]
            changed = True

    # Add updated timestamp for concept/answer pages
    if page_type in ("concept", "answer") and "updated:" not in fm_block:
        mtime = path.stat().st_mtime
        dt = datetime.utcfromtimestamp(mtime).strftime("%Y-%m-%dT%H:%M:%SZ")
        for anchor in ("ingested_at:", "created:", "title:"):
            am = re.search(rf"^{re.escape(anchor)}[^\n]*\n", fm_block, re.MULTILINE)
            if am:
                fm_block = fm_block[:am.end()] + f"updated: {dt}\n" + fm_block[am.end():]
                changed = True
                break

    if not changed:
        return False

    new_text = f"---\n{fm_block}\n---\n{body}"
    if not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return True


def run_normalize_frontmatter(dry_run: bool = False) -> None:
    fixed = 0
    scanned = 0
    for path in sorted((ROOT / "notes").rglob("*.md")):
        scanned += 1
        if normalize_file(path, dry_run=dry_run):
            fixed += 1
            print(f"  {'(dry)' if dry_run else 'fixed'}: {path.relative_to(ROOT)}")
    label = "would fix" if dry_run else "fixed"
    print(f"Scanned {scanned} notes, {label} {fixed} frontmatter block(s)")
