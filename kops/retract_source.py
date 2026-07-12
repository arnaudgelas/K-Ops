"""Source retraction — revoke a bad source and map/flag its full blast radius.

K-Ops can already *block* claims that cite a revoked source (claim registry) and
*flag* them in lint/scorecard, but there is no single operation that unwinds a
source you have discovered is wrong. Doing it by hand means editing the source
status, re-running the registries, and hoping you caught every dependent note.

``retract`` makes it one deterministic, auditable step:

1. Mark the source ``revoked`` (or another blocked status) with a reason + date.
2. Compute the **blast radius** by impact-propagation over the vault graph —
   every claim, concept, and answer that transitively depends on the source.
3. Flag every dependent concept and answer ``revalidation_required`` so it surfaces
   in ``stale-impact`` and re-review, and re-derive the claim registry so dependent
   claims flip to ``blocked`` and appear in ``review-queue``.
4. Report the whole blast radius.

Deliberate boundary (matches K-Ops's "fail loudly, preserve Git review" principle):
this flags and reports; it never silently rewrites or deletes claim text. A human
plus Git decides what actually changes.

Impact propagation (source flows to its dependents):

    source --(claim supported_by)-->  claim
    source --(concept cites_source)--> concept
    claim  --(derived_from)-->         concept
    concept/source --(answer updates/mentions)--> answer
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict, deque
from pathlib import Path

from kops.utils import (
    CONFIG,
    ROOT,
    dump_frontmatter,
    find_source_note,
    parse_frontmatter,
    write_text,
)

# Statuses the claim registry treats as blocking (see claim_registry._BLOCKED_SOURCE_STATUSES).
_BLOCKED_STATUSES = ("revoked", "permission-revoked", "deleted-from-origin", "do-not-use")
_DEFAULT_STATUS = "revoked"


# ---------------------------------------------------------------------------
# Blast radius (pure, graph-only)
# ---------------------------------------------------------------------------


def build_impact_adjacency(graph: dict) -> dict[str, set[str]]:
    """Impact graph: ``adj[u]`` = nodes that become impacted when ``u`` is impacted."""
    adj: dict[str, set[str]] = defaultdict(set)
    for edge in graph.get("edges", []):
        rel, s, t = edge.get("relation"), edge.get("source"), edge.get("target")
        if not s or not t:
            continue
        if rel == "supported_by":  # claim(s) supported_by source(t)
            adj[t].add(s)
        elif rel == "cites_source":  # concept(s) cites_source source(t)
            adj[t].add(s)
        elif rel == "derived_from":  # claim(s) derived_from concept(t)
            adj[s].add(t)
        elif rel in ("updates", "mentions"):  # answer(s) -> concept/source(t)
            adj[t].add(s)
    return adj


def compute_blast_radius(graph: dict, source_id: str) -> dict:
    """Return the claims, concepts, and answers transitively depending on ``source_id``."""
    source_node = f"source:{source_id}"
    adj = build_impact_adjacency(graph)
    title_of = {n["id"]: n.get("title") or n["id"] for n in graph.get("nodes", [])}

    seen: set[str] = set()
    queue: deque[str] = deque([source_node])
    while queue:
        node = queue.popleft()
        for dependent in sorted(adj.get(node, ())):
            if dependent not in seen:
                seen.add(dependent)
                queue.append(dependent)

    def _of_kind(prefix: str) -> list[dict]:
        return sorted(
            (
                {"id": nid, "title": title_of.get(nid, nid)}
                for nid in seen
                if nid.startswith(prefix)
            ),
            key=lambda d: d["id"],
        )

    return {
        "source_id": source_id,
        "source_in_graph": source_node in {n["id"] for n in graph.get("nodes", [])},
        "claims": _of_kind("claim:"),
        "concepts": _of_kind("concept:"),
        "answers": _of_kind("answer:"),
    }


# ---------------------------------------------------------------------------
# Frontmatter mutation (pure string -> string)
# ---------------------------------------------------------------------------


def mark_source_retracted(text: str, reason: str, status: str, date: str) -> str:
    """Set a source note's status to a blocked value and record the retraction."""
    frontmatter, body = parse_frontmatter(text)
    frontmatter["source_status"] = status
    frontmatter["retracted_at"] = date
    frontmatter["retraction_reason"] = reason
    return dump_frontmatter(frontmatter) + body


def flag_note_for_revalidation(text: str, reason: str) -> tuple[str, bool]:
    """Set ``revalidation_required: true`` on a note. Returns (new_text, changed)."""
    frontmatter, body = parse_frontmatter(text)
    if frontmatter.get("revalidation_required") is True:
        return text, False
    frontmatter["revalidation_required"] = True
    frontmatter["revalidation_reason"] = reason
    return dump_frontmatter(frontmatter) + body, True


# ---------------------------------------------------------------------------
# Vault-mutating orchestration
# ---------------------------------------------------------------------------


def _note_path_for(node_id: str) -> Path | None:
    kind, _, stem = node_id.partition(":")
    if kind == "concept":
        return CONFIG.concepts_dir / f"{stem}.md"
    if kind == "answer":
        return CONFIG.answers_dir / f"{stem}.md"
    return None


def _scan_affected_outputs(source_id: str) -> list[str]:
    """Best-effort: rendered outputs are not graph nodes; grep them for the source id."""
    outputs_dir = getattr(CONFIG, "outputs_dir", None)
    hits: list[str] = []
    if not outputs_dir or not outputs_dir.exists():
        return hits
    for path in sorted(outputs_dir.rglob("*.md")):
        try:
            if source_id in path.read_text(encoding="utf-8"):
                hits.append(path.relative_to(ROOT).as_posix())
        except OSError:
            continue
    return hits


def retract(
    source_id: str,
    reason: str,
    status: str = _DEFAULT_STATUS,
    dry_run: bool = False,
    recompute: bool = True,
) -> dict:
    """Retract ``source_id``: revoke it, flag its blast radius, re-derive claims."""
    if status not in _BLOCKED_STATUSES:
        raise ValueError(f"status must be one of {_BLOCKED_STATUSES}, got {status!r}")

    from kops.vault_graph import load_graph

    source_note = find_source_note(source_id)
    radius = compute_blast_radius(load_graph(), source_id)
    date = dt.date.today().isoformat()

    flagged: list[str] = []
    if not dry_run:
        if source_note and source_note.exists():
            new_text = mark_source_retracted(
                source_note.read_text(encoding="utf-8"), reason, status, date
            )
            write_text(source_note, new_text)

        reval_reason = f"source {source_id} retracted ({reason})"
        for node in radius["concepts"] + radius["answers"]:
            path = _note_path_for(node["id"])
            if path and path.exists():
                updated, changed = flag_note_for_revalidation(
                    path.read_text(encoding="utf-8"), reval_reason
                )
                if changed:
                    write_text(path, updated)
                    flagged.append(path.relative_to(ROOT).as_posix())

        if recompute:
            from kops.claim_registry import run as run_claim_registry

            run_claim_registry()

    return {
        "source_id": source_id,
        "status": status,
        "reason": reason,
        "retracted_at": date,
        "source_note": source_note.relative_to(ROOT).as_posix() if source_note else None,
        "dry_run": dry_run,
        "blast_radius": {
            "claims": radius["claims"],
            "concepts": radius["concepts"],
            "answers": radius["answers"],
        },
        "flagged_notes": flagged,
        "affected_outputs": _scan_affected_outputs(source_id),
    }


def run(
    source_id: str,
    reason: str,
    status: str = _DEFAULT_STATUS,
    dry_run: bool = False,
    fmt: str = "text",
    recompute: bool = True,
) -> dict:
    report = retract(source_id, reason, status=status, dry_run=dry_run, recompute=recompute)

    if fmt == "json":
        import json

        print(json.dumps(report, indent=2, ensure_ascii=False))
        return report

    br = report["blast_radius"]
    tag = "[DRY-RUN] would retract" if dry_run else "Retracted"
    print(f"{tag} source {source_id} → status={report['status']} ({report['reason']})")
    if report["source_note"] is None:
        print("  ! no source note found for this id — status not written")
    print(
        f"  blast radius: {len(br['claims'])} claim(s), "
        f"{len(br['concepts'])} concept(s), {len(br['answers'])} answer(s)"
    )
    for label, key in (("concepts", "concepts"), ("answers", "answers")):
        for item in br[key]:
            print(f"    - {label[:-1]}: {item['title']}")
    if report["affected_outputs"]:
        print(f"  affected outputs ({len(report['affected_outputs'])}):")
        for out in report["affected_outputs"]:
            print(f"    - {out}")
    if not dry_run:
        print(f"  flagged {len(report['flagged_notes'])} note(s) for revalidation")
        print("  → dependent claims are now blocked; review with 'review-queue' and 'stale-impact'")
    return report


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Retract a source and map/flag its blast radius.")
    parser.add_argument("source_id", help="Source id to retract, e.g. src-1f2a3b4c5d")
    parser.add_argument("--reason", required=True, help="Why the source is being retracted.")
    parser.add_argument("--status", choices=_BLOCKED_STATUSES, default=_DEFAULT_STATUS)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument(
        "--dry-run", action="store_true", help="Report the blast radius, change nothing."
    )
    parser.add_argument(
        "--no-recompute", action="store_true", help="Skip re-deriving the claim registry."
    )
    args = parser.parse_args()
    run(
        args.source_id,
        args.reason,
        status=args.status,
        dry_run=args.dry_run,
        fmt=args.format,
        recompute=not args.no_recompute,
    )


if __name__ == "__main__":
    main()
