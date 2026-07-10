#!/usr/bin/env python3
"""Detect upstream git drift for GitHub-repo-snapshot sources and flag derived pages.

For every source note captured from a GitHub repository, this compares the commit
recorded in the note's frontmatter (`git_commit`) against the current upstream head
(`git ls-remote`, no clone). When upstream has moved, the source note and every
curated page that cites the source are flagged for revalidation.

What this can and cannot do:
- CAN (deterministic): detect drift, refresh the recorded upstream head, and mark
  the source note + derived concept pages so nothing silently goes stale.
- CANNOT (needs an agent/human): rewrite curated prose. Drift only *flags*; the raw
  snapshot is refreshed by re-running `kb.py ingest-github`, and the prose is then
  re-curated. See notes/Runbooks/Source_Drift_Tracking.md.

Usage:
    python scripts/check_source_drift.py                       # scan ALL github sources (network-heavy)
    python scripts/check_source_drift.py --source src-abc123   # check only named source(s)
    python scripts/check_source_drift.py --flag                # write drift flags
    python scripts/check_source_drift.py --json                # machine-readable report

Exit codes: 0 = all in sync, 2 = drift detected, 1 = error (e.g. unreachable).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from utils import ROOT, dump_frontmatter, now_stamp, parse_frontmatter

SOURCES_DIR = ROOT / "notes" / "Sources"
# Directories whose pages may be grounded in a source and should be flagged on drift.
DERIVED_DIRS = [ROOT / "notes" / "Concepts", ROOT / "notes" / "Maintenance"]
GITHUB_KIND = "github-repo-snapshot"
LS_REMOTE_TIMEOUT = 20


def _iter_source_notes(only: set[str] | None):
    for path in sorted(SOURCES_DIR.rglob("*.md")):
        try:
            fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if fm.get("source_kind") != GITHUB_KIND:
            continue
        if not fm.get("git_commit") or not fm.get("source_url"):
            continue
        if only and str(fm.get("source_id", path.stem)) not in only:
            continue
        yield path, fm, body


def _build_derived_index() -> list[tuple[Path, str]]:
    """Read every candidate derived page once so per-source matching is in-memory."""
    index: list[tuple[Path, str]] = []
    for base in DERIVED_DIRS:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.md")):
            try:
                index.append((path, path.read_text(encoding="utf-8")))
            except Exception:
                continue
    return index


def _upstream_head(url: str, branch: str) -> str | None:
    """Return the upstream commit for branch, or None if unreachable/absent.

    Query fully-qualified refs and match the ref name exactly. A bare
    `git ls-remote url main` glob-matches every ref ending in `/main`
    (e.g. fork branches like `refs/heads/someuser/main`), so relying on the
    first returned line can pick an unrelated fork head. See the fork-branch
    false-positive that this guards against.
    """
    # (query ref, expected exact ref name in output)
    candidates = [(f"refs/heads/{branch}", f"refs/heads/{branch}"), ("HEAD", "HEAD")]
    for query_ref, exact_ref in candidates:
        try:
            out = subprocess.run(
                ["git", "ls-remote", url, query_ref],
                capture_output=True,
                text=True,
                timeout=LS_REMOTE_TIMEOUT,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if out.returncode != 0:
            continue
        for line in out.stdout.strip().splitlines():
            sha, _, ref = line.partition("\t")
            if ref.strip() == exact_ref:
                return sha.strip()
    return None


def _derived_pages(source_id: str, index: list[tuple[Path, str]]) -> list[Path]:
    return [path for path, text in index if source_id in text]


def _flag_source_note(path: Path, fm: dict, body: str, upstream: str) -> None:
    fm["drift_status"] = "drifted"
    fm["upstream_commit"] = upstream
    fm["upstream_checked_at"] = now_stamp()
    fm["revalidation_required"] = True
    path.write_text(dump_frontmatter(fm) + body, encoding="utf-8")


def _flag_derived_page(path: Path, source_id: str, recorded: str, upstream: str) -> None:
    fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    fm["revalidation_required"] = True
    marker = "## Upstream Drift"
    bullet = (
        f"- `{source_id}` moved upstream `{recorded[:7]}` -> `{upstream[:7]}` "
        f"(detected {now_stamp()}). Re-ingest the snapshot and re-ground claims cited from this source."
    )
    lines = body.splitlines()
    # Drop any prior bullet for this same source (idempotent re-flagging).
    prefix = f"- `{source_id}` moved upstream"
    lines = [ln for ln in lines if not ln.startswith(prefix)]
    if marker in lines:
        # Insert the bullet immediately after the marker heading; preserve all other sections.
        idx = lines.index(marker)
        insert_at = idx + 1
        if insert_at < len(lines) and lines[insert_at].strip() == "":
            insert_at += 1
        lines.insert(insert_at, bullet)
        new_body = "\n".join(lines).rstrip() + "\n"
    else:
        new_body = body.rstrip() + f"\n\n{marker}\n\n{bullet}\n"
    path.write_text(dump_frontmatter(fm) + new_body, encoding="utf-8")


def check(flag: bool, only: set[str] | None) -> tuple[list[dict], int]:
    results: list[dict] = []
    exit_code = 0
    index = _build_derived_index()
    for path, fm, body in _iter_source_notes(only):
        source_id = fm.get("source_id", path.stem)
        recorded = str(fm["git_commit"]).strip()
        branch = str(fm.get("branch") or "main").strip()
        url = str(fm["source_url"]).strip()
        upstream = _upstream_head(url, branch)
        derived = _derived_pages(source_id, index)

        if upstream is None:
            status = "unreachable"
            exit_code = max(exit_code, 1)
        elif upstream == recorded:
            status = "in-sync"
        else:
            status = "drifted"
            exit_code = max(exit_code, 2)
            if flag:
                _flag_source_note(path, fm, body, upstream)
                for page in derived:
                    _flag_derived_page(page, source_id, recorded, upstream)

        results.append(
            {
                "source_id": source_id,
                "repo": url,
                "branch": branch,
                "recorded": recorded,
                "upstream": upstream,
                "status": status,
                "derived_pages": [str(p.relative_to(ROOT)) for p in derived],
            }
        )
    return results, exit_code


def _print_report(results: list[dict], flagged: bool) -> None:
    if not results:
        print("No github-repo-snapshot sources with a recorded git_commit found.")
        return
    width = max(len(r["source_id"]) for r in results)
    for r in results:
        badge = {"in-sync": "OK  ", "drifted": "DRIFT", "unreachable": "ERR "}[r["status"]]
        rec = (r["recorded"] or "")[:7]
        up = (r["upstream"] or "?")[:7]
        detail = f"{rec}->{up}" if r["status"] == "drifted" else rec
        print(f"[{badge}] {r['source_id']:<{width}}  {detail:<16} {r['repo']}")
        if r["status"] == "drifted":
            for p in r["derived_pages"]:
                print(f"          {'flagged' if flagged else 'derives'}: {p}")
    drift = sum(1 for r in results if r["status"] == "drifted")
    err = sum(1 for r in results if r["status"] == "unreachable")
    print(f"\n{len(results)} source(s): {drift} drifted, {err} unreachable.")
    if drift and not flagged:
        print("Run with --flag to mark the source notes and derived pages for revalidation.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--flag", action="store_true", help="Write drift flags to notes.")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    ap.add_argument(
        "--source",
        nargs="+",
        metavar="SRC_ID",
        help="Limit the check to these source ids (avoids a full network scan).",
    )
    args = ap.parse_args()

    results, exit_code = check(flag=args.flag, only=set(args.source) if args.source else None)
    if args.json:
        print(json.dumps({"results": results, "flagged": args.flag}, indent=2))
    else:
        _print_report(results, flagged=args.flag)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
