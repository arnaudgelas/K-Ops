"""Review queue — one list of everything in the vault that needs human judgment.

K-Ops already *computes* every "needs-a-human" signal, but scatters them across the
scorecard, the lint report, and four registries. This command gathers them into a
single, prioritised worklist so a reviewer has one place to look:

- failed / unverifiable quote spans   (data/span_verification.json)
- blocked / quarantined / unsupported claims   (data/claims.json)
- undocumented contradictions   (data/contradictions.json)
- sources needing verification/fetch or flagged adversarial   (notes/Sources/*.md)
- unreviewed probes   (research/evals/dev-probes.jsonl)
- knowledge gaps & fragile clusters   (data/graph/community_audit.json, if present)

The queue is derived and read-only. It never mutates the vault.
"""

from __future__ import annotations

import json
from pathlib import Path

from kops.utils import CONFIG, ROOT, parse_frontmatter

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}

_SOURCE_VERIFICATION_STATES = {"needs_primary_sources", "needs_fetch"}


def _load(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def assemble(
    spans: dict | None,
    claims: dict | None,
    contradictions: dict | None,
    sources: list[dict] | None,
    probes: list[dict] | None,
    community: dict | None,
) -> list[dict]:
    """Build the prioritised review list from already-loaded registry data.

    Pure function (no I/O) so it is directly testable.
    """
    items: list[dict] = []

    def add(category: str, severity: str, ref: str, detail: str, action: str) -> None:
        items.append(
            {
                "category": category,
                "severity": severity,
                "ref": ref,
                "detail": detail,
                "action": action,
            }
        )

    # ── quote spans ──────────────────────────────────────────────────────
    for result in (spans or {}).get("results", []):
        verdict = result.get("span_verification")
        cid = result.get("claim_id", "?")
        concept = result.get("concept", "?")
        if verdict == "failed":
            add(
                "failed-quote-span",
                "error",
                cid,
                f"{concept}: cited quote is not in the source",
                "Fix the quote anchor or remove the unsupported claim",
            )
        elif verdict == "unverifiable":
            add(
                "unverifiable-quote-span",
                "warning",
                cid,
                f"{concept}: source text could not be resolved to verify the quote",
                "Restore the source content or correct the source_id",
            )

    # ── claims ───────────────────────────────────────────────────────────
    for claim in (claims or {}).get("claims", []):
        cid = claim.get("claim_id") or claim.get("id", "?")
        concept = claim.get("concept", "?")
        status = claim.get("admission_status")
        reasons = ", ".join(claim.get("admission_reasons", [])) or status
        if status == "blocked":
            add(
                "blocked-claim",
                "error",
                cid,
                f"{concept}: depends on a revoked/do-not-use/adversarial source ({reasons})",
                "Remove or re-source the claim before it can be trusted",
            )
        elif status == "quarantine":
            add(
                "quarantined-claim",
                "warning",
                cid,
                f"{concept}: depends on weak/synthetic/unverified source ({reasons})",
                "Verify against a primary source, then re-run extract-claims",
            )
        elif claim.get("evidence_status") == "unsupported":
            add(
                "unsupported-claim",
                "warning",
                cid,
                f"{concept}: no direct or page-level source evidence",
                "Add an inline source citation or move to Open Questions",
            )

    # ── contradictions ───────────────────────────────────────────────────
    for rec in (contradictions or {}).get("contradictions", []):
        if not rec.get("documented", False):
            add(
                "undocumented-contradiction",
                "warning",
                str(rec.get("id", "?")),
                f"{rec.get('concept', '?')}: conflicting claims with no Open Questions bullet",
                "Adjudicate and document in an ## Open Questions section",
            )

    # ── sources needing verification ─────────────────────────────────────
    for fm in sources or []:
        sid = str(fm.get("source_id", "?"))
        if fm.get("adversarial_content") is True:
            add(
                "adversarial-source",
                "error",
                sid,
                "source flagged as containing adversarial/injection content",
                "Review raw content before any compile uses it",
            )
        elif str(fm.get("verification_state") or "") in _SOURCE_VERIFICATION_STATES:
            add(
                "source-needs-verification",
                "warning",
                sid,
                f"verification_state: {fm.get('verification_state')}",
                "Fetch primary sources or verify the lead before promotion",
            )

    # ── probes ───────────────────────────────────────────────────────────
    for probe in probes or []:
        if str(probe.get("review_status") or "unreviewed") == "unreviewed":
            add(
                "unreviewed-probe",
                "info",
                str(probe.get("id") or probe.get("question", "?"))[:60],
                f"{probe.get('concept', '?')}: probe awaiting review",
                "Run the Probe Review checklist",
            )

    # ── knowledge gaps & fragile clusters (optional) ─────────────────────
    for gap in (community or {}).get("gaps", []):
        a = gap.get("concept_a", {}).get("title", "?")
        b = gap.get("concept_b", {}).get("title", "?")
        add(
            "knowledge-gap",
            "info",
            f"{gap.get('concept_a', {}).get('id')}|{gap.get('concept_b', {}).get('id')}",
            f"'{a}' and '{b}' share {gap.get('shared_source_count')} source(s) but are unlinked and in different clusters",
            "Add a Related Concepts link, or file a research question if the relationship is unclear",
        )
    for frag in (community or {}).get("fragile_communities", []):
        conn = frag.get("sole_connector", {})
        add(
            "fragile-cluster",
            "info",
            f"community-{frag.get('community_id')}",
            f"cluster of {frag.get('size')} concepts hangs off a single connector '{conn.get('title')}'",
            "Add cross-links so the cluster is not a single point of failure",
        )

    items.sort(key=lambda it: (_SEVERITY_ORDER.get(it["severity"], 3), it["category"], it["ref"]))
    return items


# ---------------------------------------------------------------------------
# Vault-backed loaders
# ---------------------------------------------------------------------------


def _load_source_frontmatter() -> list[dict]:
    out: list[dict] = []
    summaries_dir = getattr(CONFIG, "summaries_dir", None)
    if not summaries_dir or not summaries_dir.exists():
        return out
    for path in sorted(summaries_dir.rglob("src-*.md")):
        try:
            fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        out.append(fm)
    return out


def _load_probes() -> list[dict]:
    path = ROOT / "research" / "evals" / "dev-probes.jsonl"
    if not path.exists():
        return []
    probes: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            probes.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return probes


def build_queue() -> list[dict]:
    return assemble(
        spans=_load(ROOT / "data" / "span_verification.json"),
        claims=_load(ROOT / "data" / "claims.json"),
        contradictions=_load(ROOT / "data" / "contradictions.json"),
        sources=_load_source_frontmatter(),
        probes=_load_probes(),
        community=_load(ROOT / "data" / "graph" / "community_audit.json"),
    )


def run(fmt: str = "text", severity: str = "all") -> list[dict]:
    items = build_queue()
    if severity != "all":
        allowed = {s for s in _SEVERITY_ORDER if _SEVERITY_ORDER[s] <= _SEVERITY_ORDER[severity]}
        items = [it for it in items if it["severity"] in allowed]

    if fmt == "json":
        print(json.dumps({"count": len(items), "items": items}, indent=2, ensure_ascii=False))
        return items

    if not items:
        print("Review queue is empty — nothing awaiting human judgment.")
        return items

    from collections import Counter

    counts = Counter(it["severity"] for it in items)
    header = ", ".join(f"{counts[s]} {s}" for s in ("error", "warning", "info") if counts[s])
    print(f"Review queue: {len(items)} item(s) — {header}\n")
    last_category = None
    for it in items:
        if it["category"] != last_category:
            print(f"[{it['severity'].upper()}] {it['category']}")
            last_category = it["category"]
        print(f"  • {it['ref']}: {it['detail']}")
        print(f"    → {it['action']}")
    return items


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="List everything in the vault needing human review."
    )
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument(
        "--severity",
        choices=["error", "warning", "info", "all"],
        default="all",
        help="Show items at this severity or higher.",
    )
    args = parser.parse_args()
    run(fmt=args.format, severity=args.severity)


if __name__ == "__main__":
    main()
