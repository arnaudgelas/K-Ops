"""
compile_large_source.py — Bottom-up summarization orchestrator for large sources.

Usage:
    uv run python scripts/compile_large_source.py <source_id> [--dry-run] [--resume] [--force]

Compiles a large source bottom-up using its v2 manifest nodes:
  1. Build a tree from the manifest nodes (parent/child relationships or inferred grouping)
  2. Leaf nodes are compiled first (extract localized claims)
  3. Parent nodes receive child summaries + minimal context
  4. Deduplication: leaf claims are canonical; parents may not restate as new atomic claims
  5. Output: research/scratch/large-source/<source_id>/

No LLM calls are made here. This script produces:
  - research/scratch/large-source/<source_id>/<node_id>.md  (one per node, placeholder in dry-run)
  - research/scratch/large-source/<source_id>/compile_log.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
SCRATCH_DIR = ROOT / "research" / "scratch" / "large-source"

# Token budget guard: warn above this, refuse without --force above 2x
TOKEN_BUDGET_WARNING = 500_000
TOKEN_BUDGET_HARD = 1_000_000

# Grouping: if no explicit parent_id hierarchy, group this many consecutive
# leaf nodes per virtual parent group.
DEFAULT_GROUP_SIZE = 29

# Approximate chars per token (GPT-family heuristic)
CHARS_PER_TOKEN = 4
PROMPT_OVERHEAD_TOKENS = 1_000


# ---------------------------------------------------------------------------
# Claim normalisation (mirrors claim_registry.py logic)
# ---------------------------------------------------------------------------
_SOURCE_CITATION_RE = re.compile(
    r"\s*\(?(?:\[\[Sources/(?:[^/\]#|]+/)?src-[0-9a-f]{10}"
    r"(?:#[^\]|)]+)?(?:\|[^\]]*)?\]\]|src-[0-9a-f]{10}"
    r"(?:#[\w./=&:%+-]+)?)\)?"
)
_PUNCT_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_claim_text(text: str) -> str:
    """Strip source citations, lowercase, strip punctuation, collapse whitespace."""
    text = _SOURCE_CITATION_RE.sub("", text).strip()
    text = text.lower()
    text = _PUNCT_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def claim_stable_id(source_id: str, claim_text: str) -> str:
    norm = normalize_claim_text(claim_text)
    key = f"{source_id}:{norm}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
    return f"clm-{digest}"


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------
def load_manifest(source_id: str) -> dict[str, Any]:
    manifest_path = RAW_DIR / source_id / "large_source_manifest.json"
    if not manifest_path.exists():
        sys.exit(f"ERROR: manifest not found: {manifest_path}")
    data: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    if data.get("large_source_manifest_version") != 2:
        sys.exit(
            f"ERROR: expected large_source_manifest_version=2, "
            f"got {data.get('large_source_manifest_version')}"
        )
    return data


# ---------------------------------------------------------------------------
# Tree construction
# ---------------------------------------------------------------------------
def build_tree(
    nodes: list[dict[str, Any]], source_id: str, group_size: int = DEFAULT_GROUP_SIZE
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """
    Build a processing tree from manifest nodes.

    Strategy:
      1. If any node has a non-null parent_id, use explicit parent links.
      2. Otherwise, group consecutive leaf nodes (level==1) into virtual
         parent groups of `group_size` nodes.

    Returns:
      - augmented_nodes: all nodes (original + any virtual group nodes)
      - children: mapping parent_id -> [child_node_id, ...]
    """
    has_explicit_parents = any(n.get("parent_id") is not None for n in nodes)

    if has_explicit_parents:
        return _build_explicit_tree(nodes)
    else:
        return _build_inferred_tree(nodes, source_id, group_size)


def _build_explicit_tree(
    nodes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Use parent_id links directly. Nodes with parent_id=None are root children."""
    children: dict[str, list[str]] = defaultdict(list)

    # Create a virtual root to collect all top-level nodes
    all_ids = {n["node_id"] for n in nodes}
    for node in nodes:
        pid = node.get("parent_id")
        if pid and pid in all_ids:
            children[pid].append(node["node_id"])

    return list(nodes), dict(children)


def _build_inferred_tree(
    nodes: list[dict[str, Any]], source_id: str, group_size: int
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """
    Infer a two-level tree by grouping consecutive nodes into virtual parents.
    All original nodes become leaves; virtual group nodes are synthesised.
    """
    # Sort by 'order' field
    sorted_nodes = sorted(nodes, key=lambda n: n.get("order", 0))

    virtual_groups: list[dict[str, Any]] = []
    children: dict[str, list[str]] = defaultdict(list)

    for g_idx in range(0, len(sorted_nodes), group_size):
        chunk = sorted_nodes[g_idx : g_idx + group_size]
        g_num = g_idx // group_size
        group_id = f"{source_id}-group-{g_num:03d}"

        # Derive title from first and last node in group
        first_title = chunk[0].get("title", f"Node {g_idx}")
        last_title = chunk[-1].get("title", f"Node {g_idx + len(chunk) - 1}")
        group_title = f"Group {g_num}: {first_title} — {last_title}"

        virtual_node: dict[str, Any] = {
            "node_id": group_id,
            "parent_id": None,  # root-level
            "order": g_num,
            "level": 2,
            "type": "virtual-group",
            "title": group_title,
            "anchor": f"group-{g_num:03d}",
            "start_char": chunk[0].get("start_char"),
            "end_char": chunk[-1].get("end_char"),
            "content_hash": None,
            "extraction_method": "inferred-grouping",
            "confidence": "inferred",
            "warnings": ["no-explicit-hierarchy"],
            "is_virtual": True,
        }
        virtual_groups.append(virtual_node)

        for leaf in chunk:
            children[group_id].append(leaf["node_id"])

    augmented = list(sorted_nodes) + virtual_groups
    return augmented, dict(children)


# ---------------------------------------------------------------------------
# Processing order: bottom-up BFS (leaves first, then parents)
# ---------------------------------------------------------------------------
def topological_order(nodes: list[dict[str, Any]], children: dict[str, list[str]]) -> list[str]:
    """
    Return node_ids in processing order: leaves before their parents.
    Uses Kahn's algorithm on the parent→child graph (reversed).
    """
    node_ids = {n["node_id"] for n in nodes}
    # Build parent map: child_id -> parent_id
    parent_of: dict[str, str] = {}
    for parent_id, child_ids in children.items():
        for cid in child_ids:
            parent_of[cid] = parent_id

    # Nodes with no children are leaves (in-degree 0 in parent-child dag)
    # We want leaves first, so process in reverse dependency order.
    # child_count tracks how many unprocessed children each node has.
    child_count: dict[str, int] = {n["node_id"]: 0 for n in nodes}
    for parent_id, child_ids in children.items():
        if parent_id in child_count:
            child_count[parent_id] = len(child_ids)

    # Queue starts with all nodes that have no children (leaves)
    queue: deque[str] = deque(nid for nid, count in child_count.items() if count == 0)
    order: list[str] = []

    while queue:
        nid = queue.popleft()
        order.append(nid)
        pid = parent_of.get(nid)
        if pid and pid in child_count:
            child_count[pid] -= 1
            if child_count[pid] == 0:
                queue.append(pid)

    # Any nodes not reached (cycles or disconnected) go at end
    remaining = [nid for nid in node_ids if nid not in set(order)]
    order.extend(sorted(remaining))

    return order


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------
def extract_node_text(source_id: str, node: dict[str, Any]) -> str:
    """Extract the text slice for a leaf node using start_char/end_char."""
    normalized_path = RAW_DIR / source_id / "normalized.md"
    if not normalized_path.exists():
        return ""

    start = node.get("start_char") or 0
    end = node.get("end_char")

    text = normalized_path.read_text(encoding="utf-8")
    if end:
        return text[start:end]
    return text[start:]


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------
def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


# ---------------------------------------------------------------------------
# Claim extraction from dry-run / real summaries
# ---------------------------------------------------------------------------
_CLAIM_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+\S)\s*$", re.MULTILINE)


def extract_claims_from_summary(text: str) -> list[str]:
    """Extract bullet-point claim texts from a summary markdown file."""
    # Look for a "Key claims" section first
    section_match = re.search(r"##\s+Key [Cc]laims?\s*\n(.*?)(?:\n##|\Z)", text, re.DOTALL)
    if section_match:
        body = section_match.group(1)
    else:
        body = text

    claims = []
    for m in _CLAIM_BULLET_RE.finditer(body):
        claims.append(m.group(1).strip())
    return claims


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------
def compute_dedup_stats(source_id: str, summaries: dict[str, str]) -> dict[str, Any]:
    """
    Compute duplicate claim rate across all leaf summaries.

    Returns dict with: total_emitted, unique_ids, dedup_ratio, duplicate_claim_ids
    """
    claim_id_counts: dict[str, int] = {}
    claim_id_first_node: dict[str, str] = {}
    total_emitted = 0

    for node_id, text in summaries.items():
        claims = extract_claims_from_summary(text)
        for claim_text in claims:
            total_emitted += 1
            cid = claim_stable_id(source_id, claim_text)
            claim_id_counts[cid] = claim_id_counts.get(cid, 0) + 1
            if cid not in claim_id_first_node:
                claim_id_first_node[cid] = node_id

    unique_ids = len(claim_id_counts)
    duplicates = [(cid, cnt) for cid, cnt in claim_id_counts.items() if cnt > 1]
    dedup_ratio = (total_emitted - unique_ids) / total_emitted if total_emitted > 0 else 0.0

    return {
        "total_emitted": total_emitted,
        "unique_ids": unique_ids,
        "dedup_ratio": round(dedup_ratio, 4),
        "duplicate_claim_ids": [cid for cid, _ in duplicates[:20]],  # cap at 20 for log
    }


# ---------------------------------------------------------------------------
# Dry-run placeholder generation
# ---------------------------------------------------------------------------
def make_dry_run_placeholder(node: dict[str, Any], section_text: str, token_estimate: int) -> str:
    node_id = node["node_id"]
    title = node.get("title", node_id)
    level = node.get("level", 1)
    node_type = node.get("type", "unknown")
    is_virtual = node.get("is_virtual", False)
    excerpt = section_text[:200].replace("\n", " ").strip() if section_text else "(no text)"

    lines = [
        f"# [DRY-RUN] {title}",
        "",
        f"**node_id**: {node_id}",
        f"**level**: {level}",
        f"**type**: {node_type}",
        f"**is_virtual**: {is_virtual}",
        f"**token_estimate**: {token_estimate}",
        "",
        "## Summary",
        "",
        f"[placeholder — would summarise {token_estimate} tokens of content]",
        "",
        "## Key claims",
        "",
        f"- [claim-A] Placeholder claim from {node_id}",
        f"- [claim-B] Another placeholder claim from {node_id}",
        "",
        "## Section digest",
        "",
        f"> {excerpt}...",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------
def run(source_id: str, dry_run: bool = False, resume: bool = False, force: bool = False) -> None:
    # 1. Load manifest
    manifest = load_manifest(source_id)
    nodes_raw: list[dict[str, Any]] = manifest.get("nodes", [])
    if not nodes_raw:
        sys.exit(f"ERROR: manifest for {source_id} has no nodes")

    print(f"Loaded manifest: {source_id} ({len(nodes_raw)} nodes)")

    # 2. Build tree
    all_nodes, children = build_tree(nodes_raw, source_id)
    node_map = {n["node_id"]: n for n in all_nodes}
    leaf_ids = {nid for nid in node_map if nid not in children}
    non_leaf_ids = set(children.keys())

    print(
        f"Tree: {len(all_nodes)} total nodes, "
        f"{len(leaf_ids)} leaves, {len(non_leaf_ids)} non-leaves "
        f"({'explicit' if any(n.get('parent_id') for n in nodes_raw) else 'inferred grouping'})"
    )

    # 3. Processing order (bottom-up)
    order = topological_order(all_nodes, children)
    print(f"Processing order: {len(order)} nodes (leaves first)")

    # 4. Token estimation
    token_estimates: dict[str, int] = {}
    for node in all_nodes:
        nid = node["node_id"]
        if nid in leaf_ids:
            text = extract_node_text(source_id, node)
            token_estimates[nid] = estimate_tokens(text)
        else:
            # Parent: cost is sum of child summary lengths (estimated) + overhead
            child_ids = children.get(nid, [])
            # Rough: assume each child summary ~500 tokens compressed
            token_estimates[nid] = len(child_ids) * 500 + PROMPT_OVERHEAD_TOKENS

    total_estimated = sum(token_estimates.values())
    warnings: list[str] = []

    if total_estimated > TOKEN_BUDGET_HARD and not force:
        msg = (
            f"Estimated {total_estimated:,} tokens exceeds hard limit {TOKEN_BUDGET_HARD:,}. "
            f"Pass --force to proceed."
        )
        sys.exit(f"ERROR: {msg}")
    elif total_estimated > TOKEN_BUDGET_WARNING:
        warnings.append(
            f"Estimated token usage {total_estimated:,} exceeds warning threshold "
            f"{TOKEN_BUDGET_WARNING:,}."
        )
        print(f"WARNING: {warnings[-1]}")

    # 5. Set up scratch directory
    scratch_dir = SCRATCH_DIR / source_id
    scratch_dir.mkdir(parents=True, exist_ok=True)
    log_path = scratch_dir / "compile_log.json"

    # Load existing log for resumability
    existing_log: dict[str, Any] = {}
    if resume and log_path.exists():
        try:
            existing_log = json.loads(log_path.read_text(encoding="utf-8"))
            print(f"Resuming from existing log: {log_path}")
        except Exception as e:
            print(f"WARNING: could not load existing log ({e}); starting fresh")

    completed_nodes: list[str] = list(existing_log.get("completed_nodes", []))
    skipped_nodes: list[str] = list(existing_log.get("skipped_nodes", []))
    failures: list[dict[str, str]] = list(existing_log.get("failures", []))
    completed_set = set(completed_nodes)

    # 6. Process nodes in order
    leaf_summaries: dict[str, str] = {}  # node_id -> summary text (for dedup)

    for nid in order:
        node = node_map.get(nid)
        if node is None:
            warnings.append(f"node_id {nid} not found in node_map; skipped")
            continue

        out_path = scratch_dir / f"{nid}.md"

        # Resumability: skip if output exists and node was previously completed
        if out_path.exists() and nid in completed_set:
            skipped_nodes.append(nid)
            # Load for dedup if it's a leaf
            if nid in leaf_ids:
                leaf_summaries[nid] = out_path.read_text(encoding="utf-8")
            continue
        # Also skip if file exists even without log entry (conservative resume)
        if out_path.exists() and resume:
            skipped_nodes.append(nid)
            completed_set.add(nid)
            if nid in leaf_ids:
                leaf_summaries[nid] = out_path.read_text(encoding="utf-8")
            continue

        is_leaf = nid in leaf_ids
        tok_est = token_estimates.get(nid, 0)

        if is_leaf:
            section_text = extract_node_text(source_id, node)
        else:
            # For parent nodes, build a digest from child summaries
            child_ids = children.get(nid, [])
            child_texts = []
            for cid in child_ids:
                child_path = scratch_dir / f"{cid}.md"
                if child_path.exists():
                    child_texts.append(
                        f"### Child: {cid}\n\n{child_path.read_text(encoding='utf-8')}"
                    )
            section_text = "\n\n".join(child_texts)

        if dry_run:
            content = make_dry_run_placeholder(node, section_text, tok_est)
        else:
            # Real LLM call would happen here via kb_runtime.py
            # This harness only prepares the context and writes placeholders
            content = make_dry_run_placeholder(node, section_text, tok_est)
            warnings.append(
                f"node {nid}: LLM call not implemented in orchestrator — "
                "integrate with kb_runtime.agent_run()"
            )

        try:
            out_path.write_text(content, encoding="utf-8")
            completed_nodes.append(nid)
            completed_set.add(nid)
            if is_leaf:
                leaf_summaries[nid] = content
        except Exception as e:
            failures.append({"node_id": nid, "error": str(e)})
            warnings.append(f"Failed to write {out_path}: {e}")

    # 7. Deduplication across leaf summaries
    dedup_stats = compute_dedup_stats(source_id, leaf_summaries)
    if dedup_stats["dedup_ratio"] >= 0.05:
        warnings.append(
            f"Dedup ratio {dedup_stats['dedup_ratio']:.1%} exceeds 5% threshold — "
            "review leaf prompts for over-broad claim extraction."
        )

    # 8. Write compile log
    status = "dry-run" if dry_run else ("complete" if not failures else "partial")
    log: dict[str, Any] = {
        "source_id": source_id,
        "manifest_version": manifest.get("large_source_manifest_version", 2),
        "generated_at": dt.datetime.now().replace(microsecond=0).isoformat(),
        "dry_run": dry_run,
        "status": status,
        "total_nodes": len(all_nodes),
        "original_nodes": len(nodes_raw),
        "virtual_nodes": len(all_nodes) - len(nodes_raw),
        "leaf_nodes": len(leaf_ids),
        "non_leaf_nodes": len(non_leaf_ids),
        "processing_order": order,
        "completed_nodes": completed_nodes,
        "skipped_nodes": skipped_nodes,
        "failures": failures,
        "warnings": warnings,
        "token_estimates": token_estimates,
        "estimated_total_tokens": total_estimated,
        "dedup_stats": dedup_stats,
        "group_size_used": DEFAULT_GROUP_SIZE,
        "tree_strategy": (
            "explicit-parent-ids"
            if any(n.get("parent_id") for n in nodes_raw)
            else "inferred-grouping"
        ),
    }
    log_path.write_text(json.dumps(log, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 9. Print summary
    print(f"\nCompile log: {log_path.relative_to(ROOT)}")
    print(f"Status: {status}")
    print(f"Completed: {len(completed_nodes)} nodes")
    print(f"Skipped (resumed): {len(skipped_nodes)} nodes")
    if failures:
        print(f"Failures: {len(failures)}")
        for f in failures[:5]:
            print(f"  {f['node_id']}: {f['error']}")
    print(f"Estimated tokens: {total_estimated:,}")
    print(
        f"Dedup ratio: {dedup_stats['dedup_ratio']:.1%} ({dedup_stats['unique_ids']} unique / {dedup_stats['total_emitted']} emitted)"
    )
    if warnings:
        print(f"Warnings: {len(warnings)}")
        for w in warnings[:5]:
            print(f"  {w}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bottom-up summarization orchestrator for large sources."
    )
    parser.add_argument("source_id", help="Source ID (e.g. src-e481bf41d0)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write placeholder summaries without LLM calls.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip nodes whose output files already exist.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Proceed even if token budget exceeds hard limit.",
    )
    args = parser.parse_args()
    run(args.source_id, dry_run=args.dry_run, resume=args.resume, force=args.force)


if __name__ == "__main__":
    main()
