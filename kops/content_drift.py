#!/usr/bin/env python3
"""Detect raw-content drift for any source and flag derived pages.

The companion `check_source_drift.py` detects drift for GitHub-repo-snapshot sources
by comparing the recorded `git_commit` against the upstream head. This does the same
job for **every other source kind** (web, PDF, local file) using the **content hash**:
it compares the `content_hash` recorded on a source note (the hash the summary was
built from) against the current raw content hash under `data/raw/<id>/metadata.json`.
When they differ, the raw evidence has changed since the summary was curated, so the
source note and every curated page that cites it are flagged for revalidation.

This closes the design.md P0: "content hashes are stored, but a complete automatic
invalidation cascade from changed raw content to stale concept claims is not
implemented yet."

Deterministic and offline: it compares two stored hashes; it does not re-fetch.
(Refreshing the raw content — and thus its hash — is `kb.py refresh`.)

Lifecycle:
- `backfill-content-hash` seeds the baseline `content_hash` onto source notes from the
  current raw metadata (run once; `--force` re-baselines all notes to the current hash).
- `refresh` updates the raw hash when content changes.
- `check-content-drift --flag` detects divergence and flags the source note + derived
  pages `revalidation_required`.
- Resolution: re-curate the summary/claims, then re-baseline
  (`backfill-content-hash --force`) and `clear-stale-flags`.

Like `check-drift`, this only *flags*; it never rewrites curated prose (human-gated).

Exit codes: 0 = all in sync, 2 = drift detected, 1 = error (e.g. missing raw).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kops.check_source_drift import _build_derived_index, _derived_pages
from kops.utils import CONFIG, ROOT, dump_frontmatter, now_stamp, parse_frontmatter

SOURCES_DIR = ROOT / "notes" / "Sources"


def current_raw_hash(source_id: str) -> str | None:
    """The current raw content hash for a source, or None if no raw is present."""
    meta = CONFIG.raw_dir / source_id / "metadata.json"
    if meta.exists():
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        h = data.get("content_hash")
        if h:
            return str(h)
    # Fall back to the source registry entry.
    try:
        registry = json.loads(CONFIG.registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        registry = []
    for entry in registry if isinstance(registry, list) else []:
        if entry.get("id") == source_id and entry.get("content_hash"):
            return str(entry["content_hash"])
    return None


def _iter_source_notes(only: set[str] | None):
    for path in sorted(SOURCES_DIR.rglob("*.md")):
        try:
            fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        source_id = str(fm.get("source_id", path.stem))
        if only and source_id not in only:
            continue
        yield path, fm, body


def detect(only: set[str] | None = None) -> list[dict]:
    """Compare each source note's baseline hash against the current raw hash."""
    results: list[dict] = []
    for path, fm, _ in _iter_source_notes(only):
        source_id = str(fm.get("source_id", path.stem))
        recorded = fm.get("content_hash")
        current = current_raw_hash(source_id)
        if not recorded:
            status = "no-baseline"  # never backfilled; cannot judge drift
        elif current is None:
            status = "no-raw"  # nothing to compare against (e.g. local-file source)
        elif str(recorded) == str(current):
            status = "in-sync"
        else:
            status = "drifted"
        results.append(
            {
                "source_id": source_id,
                "recorded": str(recorded) if recorded else None,
                "current": current,
                "status": status,
            }
        )
    return results


def _flag_source_note(path: Path, fm: dict, body: str, current: str) -> None:
    fm["content_drift_status"] = "drifted"
    fm["drifted_content_hash"] = current
    fm["content_checked_at"] = now_stamp()
    fm["revalidation_required"] = True
    path.write_text(dump_frontmatter(fm) + body, encoding="utf-8")


def _flag_derived_page(path: Path, source_id: str, recorded: str, current: str) -> None:
    fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    fm["revalidation_required"] = True
    marker = "## Content Drift"
    bullet = (
        f"- `{source_id}` raw content changed `{recorded[:7]}` -> `{current[:7]}` "
        f"(detected {now_stamp()}). Re-ground claims cited from this source."
    )
    lines = body.splitlines()
    prefix = f"- `{source_id}` raw content changed"
    lines = [ln for ln in lines if not ln.startswith(prefix)]  # idempotent re-flagging
    if marker in lines:
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
    results = detect(only)
    index = _build_derived_index()
    exit_code = 0
    note_by_id = {
        str(fm.get("source_id", p.stem)): (p, fm, body) for p, fm, body in _iter_source_notes(only)
    }
    for r in results:
        if r["status"] != "drifted":
            continue
        exit_code = max(exit_code, 2)
        r["derived_pages"] = [
            str(p.relative_to(ROOT)) for p in _derived_pages(r["source_id"], index)
        ]
        if flag:
            path, fm, body = note_by_id[r["source_id"]]
            _flag_source_note(path, fm, body, r["current"])
            for page in _derived_pages(r["source_id"], index):
                _flag_derived_page(page, r["source_id"], r["recorded"], r["current"])
    return results, exit_code


def backfill_content_hash(dry_run: bool = False, force: bool = False) -> int:
    """Seed (or, with force, re-baseline) `content_hash` on source notes.

    Sets each note's baseline to the current raw hash. Without --force, only notes
    missing a baseline are touched; --force re-baselines all notes to the current hash
    (use after re-curating a drifted source).
    """
    changed = 0
    for path, fm, body in _iter_source_notes(None):
        source_id = str(fm.get("source_id", path.stem))
        current = current_raw_hash(source_id)
        if current is None:
            continue
        if fm.get("content_hash") and not force:
            continue
        if str(fm.get("content_hash")) == str(current):
            continue
        changed += 1
        if dry_run:
            print(f"[DRY-RUN] would set content_hash={current} on {source_id}")
            continue
        fm["content_hash"] = current
        # Re-baselining resolves drift bookkeeping on the note.
        if fm.get("content_drift_status") == "drifted":
            fm["content_drift_status"] = "resolved"
        path.write_text(dump_frontmatter(fm) + body, encoding="utf-8")
    verb = "would update" if dry_run else "updated"
    print(f"content_hash baseline {verb} on {changed} source note(s).")
    return changed


def _print_report(results: list[dict], flagged: bool) -> None:
    if not results:
        print("No source notes found.")
        return
    width = max(len(r["source_id"]) for r in results)
    badges = {
        "in-sync": "OK  ",
        "drifted": "DRIFT",
        "no-raw": "----",
        "no-baseline": "SEED",
    }
    for r in results:
        rec = (r["recorded"] or "")[:7]
        cur = (r["current"] or "?")[:7]
        detail = f"{rec}->{cur}" if r["status"] == "drifted" else rec
        print(f"[{badges[r['status']]}] {r['source_id']:<{width}}  {detail}")
        if r["status"] == "drifted":
            for p in r.get("derived_pages", []):
                print(f"          {'flagged' if flagged else 'derives'}: {p}")
    drift = sum(1 for r in results if r["status"] == "drifted")
    seed = sum(1 for r in results if r["status"] == "no-baseline")
    print(f"\n{len(results)} source(s): {drift} drifted, {seed} without a baseline.")
    if seed:
        print("Run 'backfill-content-hash' to seed baselines before drift can be detected.")
    if drift and not flagged:
        print("Run with --flag to mark the source notes and derived pages for revalidation.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--flag", action="store_true", help="Write drift flags to notes.")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    ap.add_argument("--source", nargs="+", metavar="SRC_ID", help="Limit to these source ids.")
    args = ap.parse_args()
    results, exit_code = check(flag=args.flag, only=set(args.source) if args.source else None)
    if args.json:
        print(json.dumps({"results": results, "flagged": args.flag}, indent=2))
    else:
        _print_report(results, flagged=args.flag)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
