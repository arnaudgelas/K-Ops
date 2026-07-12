from __future__ import annotations

import argparse
import os as _os
import sys as _sys

# Resolve --vault BEFORE importing modules that read the vault root at import
# time (utils/kb_paths compute ROOT on import). Env var wins if already set.
if "KB_HOME" not in _os.environ:
    for _i, _arg in enumerate(_sys.argv[1:], start=1):
        if _arg == "--vault" and _i + 1 < len(_sys.argv):
            _os.environ["KB_HOME"] = _sys.argv[_i + 1]
            break
        if _arg.startswith("--vault="):
            _os.environ["KB_HOME"] = _arg.split("=", 1)[1]
            break

from kops.utils import ROOT

# Only config-free imports at module top: building the arg parser must not pull
# in the command layer (which eagerly loads the vault config), so `kops --help`
# works outside a vault. The command imports are deferred into main() and
# run_maintenance(), after argparse has had its chance to handle --help.
from kops.research_tiers import RESEARCH_TIERS


def _clean_tmp(max_age_days: int = 7) -> None:
    import time

    tmp_dir = ROOT / ".tmp"
    if not tmp_dir.exists():
        return
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    for path in tmp_dir.iterdir():
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink()
            removed += 1
    print(f"Cleaned {removed} file(s) from .tmp/ (older than {max_age_days} days)")


def run_maintenance(
    agent: str | None = None, clean_tmp: bool = False, check_drift: bool = False
) -> None:
    from kops.kb_commands import (
        run_refresh_sources,
        run_normalize_github_sources,
        run_backfill_source_notes,
        run_backfill_source_metadata,
        run_backfill_concept_quality,
        run_backfill_answer_quality,
        run_build_graph,
        run_extract_claims,
        run_extract_contradictions,
        run_verify_spans,
        run_scorecard,
        run_signal_log,
        run_lint,
    )
    from kops.kb_runtime import cmd_compile

    if clean_tmp:
        _clean_tmp()
    if agent:
        run_refresh_sources()
        # maintenance rebuilds the registries itself below, so skip the inner-loop rebuild.
        cmd_compile(agent, verify=False)
    run_normalize_github_sources()
    run_backfill_source_notes()
    run_backfill_source_metadata()
    run_backfill_concept_quality()
    run_backfill_answer_quality()
    run_build_graph()
    run_extract_claims()
    run_extract_contradictions()
    run_verify_spans()
    if check_drift:
        # Network-heavy (one git ls-remote per GitHub source); off by default.
        from kops.check_source_drift import check as _check_drift, _print_report as _drift_report

        results, _ = _check_drift(flag=True, only=None)
        _drift_report(results, flagged=True)
    run_scorecard()
    # Record one signal datapoint per maintenance run. Warn (do not hard-exit) on a
    # hard regression — the fail-closed gate is the standalone 'signal-log --check'.
    signal_result = run_signal_log(record=True)
    if signal_result and signal_result.get("regression", {}).get("hard"):
        reasons = signal_result["regression"].get("reasons", [])
        print("WARNING: hard signal regression detected — " + "; ".join(reasons))
        print("  Run 'kops signal-log --check' to gate on this.")
    run_lint(fix_backlinks=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Living research vault workflow")
    parser.add_argument(
        "--vault",
        metavar="DIR",
        help="Vault root directory (overrides KB_HOME; handled before subcommand dispatch).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest")
    p_ingest.add_argument("--input", required=True)
    p_ingest.add_argument(
        "--branch", help="Optional branch override for GitHub repository URLs in the input list."
    )
    p_ingest.add_argument("--fail-fast", action="store_true")

    p_add = sub.add_parser(
        "add",
        help="Ingest one URL, GitHub repo URL, or local file directly.",
        description="Ingest one URL, GitHub repo URL, or local file directly.",
    )
    p_add.add_argument("source")
    p_add.add_argument("--branch", help="Optional branch override for GitHub repository URLs.")
    p_add.add_argument("--fail-fast", action="store_true")

    p_ingest_github = sub.add_parser("ingest-github")
    p_ingest_github.add_argument("--repo", required=True)
    p_ingest_github.add_argument("--branch")
    p_ingest_github.add_argument("--compile-agent", choices=["codex", "claude", "gemini"])

    p_compile = sub.add_parser("compile")
    p_compile.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_compile.add_argument(
        "--show-prompt",
        action="store_true",
        help="Print rendered prompt and exit without running the agent.",
    )
    p_compile.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip the inner-loop verification after the agent write.",
    )

    p_compile_large = sub.add_parser(
        "compile-large",
        help="Bottom-up summarization orchestrator for large sources (>50 pages).",
    )
    p_compile_large.add_argument(
        "--source-id", required=True, help="Source ID (e.g. src-e481bf41d0)"
    )
    p_compile_large.add_argument(
        "--dry-run",
        action="store_true",
        help="Write placeholder summaries without LLM calls.",
    )
    p_compile_large.add_argument(
        "--resume",
        action="store_true",
        help="Skip nodes whose output files already exist.",
    )
    p_compile_large.add_argument(
        "--force",
        action="store_true",
        help="Proceed even if estimated token budget exceeds hard limit.",
    )

    p_refresh = sub.add_parser("refresh")
    p_refresh.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_refresh.add_argument(
        "--branch", help="Optional branch override for GitHub repository URLs during refresh."
    )
    p_refresh.add_argument("--fail-fast", action="store_true")

    p_heal = sub.add_parser("heal")
    p_heal.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_heal.add_argument(
        "--show-prompt",
        action="store_true",
        help="Print rendered prompt and exit without running the agent.",
    )
    p_heal.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip the inner-loop verification after the agent write.",
    )

    p_ask = sub.add_parser("ask")
    p_ask.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_ask.add_argument("--question", required=True)

    p_render = sub.add_parser("render")
    p_render.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_render.add_argument(
        "--format", required=True, choices=["memo", "slides", "outline", "report"]
    )
    p_render.add_argument("--prompt", required=True)

    p_claim_map = sub.add_parser(
        "claim-map", help="Generate a Mermaid argument map for a concept from claims.json."
    )
    p_claim_map.add_argument(
        "--concept", required=True, help="Concept stem (e.g. Multi_Agent_Orchestration)"
    )
    p_claim_map.add_argument("--output", choices=["stdout", "file"], default="stdout")

    p_install_assets = sub.add_parser("install-agent-assets")
    p_install_assets.add_argument(
        "--agent", choices=["all", "claude", "gemini", "codex"], default="all"
    )
    p_install_assets.add_argument("--scope", choices=["project", "home", "both"], default="both")
    p_install_assets.add_argument("--dry-run", action="store_true")
    p_install_assets.add_argument("--force", action="store_true")

    p_validate = sub.add_parser(
        "validate", help="Print the loaded config and verify the expected vault paths exist."
    )
    p_validate.add_argument(
        "--strict",
        action="store_true",
        help="Also run schema validation against config/schema.yaml and fail on missing mandatory fields.",
    )

    p_research_start = sub.add_parser("research-start")
    p_research_start.add_argument("--topic", required=True)
    p_research_start.add_argument("--tier", choices=sorted(RESEARCH_TIERS), default="standard")

    p_research_status = sub.add_parser("research-status")
    p_research_status.add_argument("topic", nargs="?", default=None)
    p_research_status.add_argument("--topic", dest="topic_opt")

    p_research_collect = sub.add_parser("research-collect")
    p_research_collect.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_research_collect.add_argument("--topic", required=True)
    p_research_collect.add_argument("--tier", choices=sorted(RESEARCH_TIERS), default="standard")

    p_research_review = sub.add_parser("research-review")
    p_research_review.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_research_review.add_argument("--topic", required=True)
    p_research_review.add_argument("--tier", choices=sorted(RESEARCH_TIERS), default="standard")

    p_research_report = sub.add_parser("research-report")
    p_research_report.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_research_report.add_argument("--topic", required=True)
    p_research_report.add_argument("--tier", choices=sorted(RESEARCH_TIERS), default="standard")
    p_research_report.add_argument("--allow-missing-review", action="store_true")

    p_research_import = sub.add_parser("research-import")
    p_research_import.add_argument("--topic", required=True)
    p_research_import.add_argument("--path", required=True)
    p_research_import.add_argument(
        "--provider", choices=["gemini", "openai", "claude", "perplexity", "other"], default="other"
    )
    p_research_import.add_argument("--origin")
    p_research_import.add_argument("--tier", choices=sorted(RESEARCH_TIERS), default="standard")

    p_research_archive = sub.add_parser("research-archive")
    p_research_archive.add_argument("--topic", required=True)

    p_export = sub.add_parser("export-vault")
    p_export.add_argument("--output")

    p_export_index = sub.add_parser("export-index")
    p_export_index.add_argument("--output")
    p_export_index.add_argument("--format", choices=["json", "csv"], default="json")

    p_suggest = sub.add_parser(
        "suggest-links",
        help="Suggest new wikilinks using nine graph- and text-analysis techniques.",
    )
    p_suggest.add_argument(
        "--approach",
        choices=[
            "all",
            "co-citation",
            "shared-sources",
            "embedding",
            "conceptual-gravity",
            "analogical-mapping",
            "triadic-closure",
            "eigenvector-centrality",
            "friction",
            "contradiction-mapping",
        ],
        default="all",
    )
    p_suggest.add_argument("--min-co-cite", type=int, default=2)
    p_suggest.add_argument("--min-shared", type=int, default=2)
    p_suggest.add_argument("--emb-threshold", type=float, default=0.75)
    p_suggest.add_argument("--min-gravity", type=float, default=0.5)
    p_suggest.add_argument("--min-jaccard", type=float, default=0.25)
    p_suggest.add_argument("--min-triadic", type=int, default=2)
    p_suggest.add_argument("--ev-top-frac", type=float, default=0.33)
    p_suggest.add_argument("--min-friction", type=float, default=0.15)
    p_suggest.add_argument("--limit", type=int, default=50)
    p_suggest.add_argument("--format", choices=["json", "text"], default="json")
    p_suggest.add_argument("--output", help="Write JSON output to this path.")

    p_graph_audit = sub.add_parser(
        "graph-audit",
        help="Detect structural antipatterns in the vault graph (hub outliers, "
        "single-source dependencies, vague contradictions).",
    )
    p_graph_audit.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )

    p_community_audit = sub.add_parser(
        "community-audit",
        help="Cluster the concept graph and report communities, bridge nodes, "
        "fragile clusters, and cross-cluster knowledge gaps.",
    )
    p_community_audit.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format (default: text)."
    )
    p_community_audit.add_argument(
        "--min-shared",
        type=int,
        default=1,
        help="Min shared sources for two unlinked concepts to count as a gap (default: 1).",
    )

    p_review_queue = sub.add_parser(
        "review-queue",
        help="One prioritised list of everything in the vault that needs human review.",
    )
    p_review_queue.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format (default: text)."
    )
    p_review_queue.add_argument(
        "--severity",
        choices=["error", "warning", "info", "all"],
        default="all",
        help="Show items at this severity or higher (default: all).",
    )

    p_retract = sub.add_parser(
        "retract",
        help="Retract a bad source: revoke it, map its blast radius, and flag dependents.",
    )
    p_retract.add_argument("source_id", help="Source id to retract, e.g. src-1f2a3b4c5d.")
    p_retract.add_argument("--reason", required=True, help="Why the source is being retracted.")
    p_retract.add_argument(
        "--status",
        choices=["revoked", "permission-revoked", "deleted-from-origin", "do-not-use"],
        default="revoked",
    )
    p_retract.add_argument("--format", choices=["text", "json"], default="text")
    p_retract.add_argument(
        "--dry-run", action="store_true", help="Report the blast radius, change nothing."
    )
    p_retract.add_argument(
        "--no-recompute", action="store_true", help="Skip re-deriving the claim registry."
    )

    p_build_graph = sub.add_parser("build-graph")
    p_build_graph.add_argument("--output")
    p_build_graph.add_argument("--report-output")
    p_build_graph.add_argument("--csv-output")
    p_build_graph.add_argument(
        "--check", action="store_true", help="Fail if files are out of sync."
    )
    p_build_graph.add_argument("--dry-run", action="store_true", help="Run without mutating files.")

    p_search = sub.add_parser("search")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--scope", choices=["all", "shared"], default="all")
    p_search.add_argument("--format", choices=["json", "text"], default="json")

    p_traverse = sub.add_parser("graph-traverse")
    p_traverse.add_argument("--start", required=True)
    p_traverse.add_argument("--depth", type=int, default=2)
    p_traverse.add_argument("--relation", action="append")
    p_traverse.add_argument("--scope", choices=["all", "shared"], default="all")
    p_traverse.add_argument("--format", choices=["json", "text"], default="json")

    p_retention = sub.add_parser("retention-report")
    p_retention.add_argument("--output")
    p_retention.add_argument("--limit", type=int, default=50)

    p_migrate_fields = sub.add_parser(
        "migrate-source-fields",
        help="Batch-derive source_kind/ingested_at/source_url for source notes from registry.json.",
    )
    p_migrate_fields.add_argument("--dry-run", action="store_true")

    p_normalize_fm = sub.add_parser(
        "normalize-frontmatter",
        help="Normalize frontmatter: kb/ tag namespace, bare enum values, updated timestamps.",
    )
    p_normalize_fm.add_argument("--dry-run", action="store_true")

    p_normalize_github = sub.add_parser("normalize-github-sources")
    p_normalize_github.add_argument("--dry-run", action="store_true")

    p_bootstrap = sub.add_parser("bootstrap")
    p_bootstrap.add_argument(
        "--target", required=True, help="Directory for the new blank starter vault."
    )
    p_bootstrap.add_argument(
        "--project-name", help="Optional project name to write into the generated config."
    )
    p_bootstrap.add_argument(
        "--with-examples",
        action="store_true",
        help="Add a tiny examples folder with starter input files.",
    )
    p_bootstrap.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the starter scaffold even if the target already exists.",
    )

    p_fetch_queue = sub.add_parser(
        "fetch-queue", help="List blocked URLs in data/fetch_queue.json."
    )
    p_fetch_queue.add_argument("--format", choices=["text", "json"], default="text")

    p_source_registry = sub.add_parser(
        "generate-source-registry",
        help="Generate notes/Indexes/Source_Registry.md from registry.json.",
    )
    p_source_registry.add_argument("--output", help="Override output path.")

    p_render_manifest = sub.add_parser("render-manifest")
    p_render_manifest.add_argument("--output")

    p_backfill_metadata = sub.add_parser("backfill-source-metadata")
    p_backfill_metadata.add_argument("--dry-run", action="store_true")

    p_backfill_concept_quality = sub.add_parser("backfill-concept-quality")
    p_backfill_concept_quality.add_argument("--dry-run", action="store_true")

    p_backfill_answer_quality = sub.add_parser("backfill-answer-quality")
    p_backfill_answer_quality.add_argument("--dry-run", action="store_true")

    p_backfill_notes = sub.add_parser("backfill-source-notes")
    p_backfill_notes.add_argument("--dry-run", action="store_true")

    p_extract_claims = sub.add_parser(
        "extract-claims",
        help="Extract atomic claims from concept pages and write data/claims.json.",
    )
    p_extract_claims.add_argument(
        "--check", action="store_true", help="Fail if data/claims.json is out of sync."
    )
    p_extract_claims.add_argument(
        "--dry-run", action="store_true", help="Run without mutating files."
    )

    p_claim_search = sub.add_parser("claim-search", help="Search the claims registry by keyword.")
    p_claim_search.add_argument("--query", required=True)
    p_claim_search.add_argument("--limit", type=int, default=20)
    p_claim_search.add_argument("--format", choices=["text", "json"], default="text")

    p_extract_contradictions = sub.add_parser(
        "extract-contradictions",
        help="Extract contradiction records from conflicting concepts and write data/contradictions.json.",
    )
    p_extract_contradictions.add_argument(
        "--check", action="store_true", help="Fail if data/contradictions.json is out of sync."
    )
    p_extract_contradictions.add_argument(
        "--dry-run", action="store_true", help="Run without mutating files."
    )

    p_verify_spans = sub.add_parser(
        "verify-spans",
        help="Verify each claim's cited quote exists in its source; write data/span_verification.json.",
    )
    p_verify_spans.add_argument(
        "--check",
        action="store_true",
        help="Fail if any claim cites a quote absent from its source.",
    )
    p_verify_spans.add_argument(
        "--dry-run", action="store_true", help="Run without mutating files."
    )

    p_signal_log = sub.add_parser(
        "signal-log",
        help="Record/report the deterministic vault signal vector over time; gate on regressions.",
    )
    p_signal_log.add_argument(
        "--record", action="store_true", help="Append this run's datapoint to the history."
    )
    p_signal_log.add_argument(
        "--check",
        action="store_true",
        help="Fail if an error-class signal strictly increased vs the last record.",
    )
    p_signal_log.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format (default: text)."
    )

    p_next_action = sub.add_parser(
        "next-action",
        help="Recommend the single highest-leverage next loop action and a convergence verdict.",
    )
    p_next_action.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format (default: text)."
    )
    p_next_action.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the vault is in a BLOCKING state (the stateless CI gate).",
    )

    p_contradiction_search = sub.add_parser(
        "contradiction-search", help="Search the contradiction registry by keyword."
    )
    p_contradiction_search.add_argument("--query", required=True)
    p_contradiction_search.add_argument("--limit", type=int, default=20)
    p_contradiction_search.add_argument("--format", choices=["text", "json"], default="text")

    p_scorecard = sub.add_parser(
        "scorecard", help="Compute vault health scorecard and write data/scorecard.json."
    )
    p_scorecard.add_argument("--output", help="Override output path.")
    p_scorecard.add_argument("--format", choices=["text", "json"], default="text")
    p_scorecard.add_argument(
        "--check", action="store_true", help="Fail if scorecard is out of sync."
    )
    p_scorecard.add_argument("--dry-run", action="store_true", help="Run without mutating files.")

    p_audit_kb = sub.add_parser(
        "audit-kb",
        help="Run the epistemic audit scorecard and write data/scorecard.json.",
    )
    p_audit_kb.add_argument("--output", help="Override output path.")
    p_audit_kb.add_argument("--format", choices=["text", "json"], default="text")
    p_audit_kb.add_argument(
        "--check", action="store_true", help="Fail if scorecard is out of sync."
    )
    p_audit_kb.add_argument("--dry-run", action="store_true", help="Run without mutating files.")

    p_stale_impact = sub.add_parser(
        "stale-impact", help="Report concept pages and answers flagged for revalidation."
    )
    p_stale_impact.add_argument("--format", choices=["text", "json"], default="text")

    p_clear_stale = sub.add_parser(
        "clear-stale-flags",
        help="Remove revalidation_required flags from concept pages and answers.",
    )
    p_clear_stale.add_argument("--dry-run", action="store_true")

    p_maintain = sub.add_parser("maintenance")
    p_maintain.add_argument(
        "--agent",
        choices=["codex", "claude", "gemini"],
        help="Optional agent to refresh and compile before the mechanical maintenance pass.",
    )
    p_maintain.add_argument(
        "--clean-tmp",
        action="store_true",
        help="Delete rendered prompt snapshots in .tmp/ older than 7 days.",
    )
    p_maintain.add_argument(
        "--check-drift",
        action="store_true",
        help="Also flag GitHub sources whose upstream has drifted (network-heavy).",
    )

    sub.add_parser(
        "generate-probes", help="Generate diagnostic questions (probes) from source summaries."
    )

    p_eval = sub.add_parser(
        "evaluate", help="Evaluate compiled concept pages against raw sources and summaries."
    )
    p_eval.add_argument("--limit", type=int, help="Limit the number of probes to run.")
    p_eval.add_argument("--probe-id", type=str, help="Evaluate only a specific probe ID.")
    p_eval.add_argument("--workers", type=int, default=5, help="Number of parallel workers.")
    p_eval.add_argument("--verbose", action="store_true", help="Print verbose details.")

    p_lint = sub.add_parser("lint")
    p_lint.add_argument("--strict", action="store_true")
    p_lint.add_argument("--fix-backlinks", action="store_true")
    p_lint.add_argument(
        "--check",
        action="store_true",
        help="Runs index generation in memory and fails if files differ.",
    )

    p_drift = sub.add_parser(
        "check-drift", help="Detect upstream git drift for GitHub-repo-snapshot sources."
    )
    p_drift.add_argument("--flag", action="store_true", help="Write drift flags to notes.")
    p_drift.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    p_drift.add_argument(
        "--source", nargs="+", metavar="SRC_ID", help="Limit the check to these source ids."
    )

    args = parser.parse_args()

    # Deferred until after argparse: importing the command layer eagerly loads the
    # vault config, so keeping these out of module scope lets `kops --help` and
    # argparse errors work without a vault present.
    from kops.kb_commands import (
        run_add_source,
        run_claim_search,
        run_backfill_answer_quality,
        run_backfill_concept_quality,
        run_backfill_source_metadata,
        run_backfill_source_notes,
        run_bootstrap,
        run_build_graph,
        run_graph_audit,
        run_community_audit,
        run_review_queue,
        run_next_action,
        run_retract,
        run_clear_stale_flags,
        run_contradiction_search,
        run_export_index,
        run_export_vault,
        run_extract_claims,
        run_extract_contradictions,
        run_verify_spans,
        run_signal_log,
        run_fetch,
        run_ingest_github,
        run_lint,
        run_install_agent_assets,
        run_normalize_github_sources,
        run_refresh_sources,
        run_fetch_queue,
        run_generate_source_registry,
        run_migrate_source_fields,
        run_normalize_frontmatter_cmd,
        run_render_manifest,
        run_retention_report,
        run_search_graph,
        run_traverse_graph,
        run_scorecard,
        run_stale_impact,
        run_suggest_links,
        run_validate_config,
        cmd_claim_map,
        run_generate_probes,
        run_evaluate,
        run_compile_large_source,
    )
    from kops.kb_runtime import cmd_ask, cmd_compile, cmd_heal, cmd_render
    from kops.research_workflow import (
        cmd_research_archive,
        cmd_research_collect,
        cmd_research_import,
        cmd_research_report,
        cmd_research_review,
        cmd_research_start,
        cmd_research_status,
    )

    if args.command == "ingest":
        run_fetch(args.input, branch=args.branch, fail_fast=args.fail_fast)
    elif args.command == "add":
        run_add_source(args.source, branch=args.branch, fail_fast=args.fail_fast)
    elif args.command == "ingest-github":
        run_ingest_github(args.repo, args.branch)
        if args.compile_agent:
            cmd_compile(args.compile_agent)
    elif args.command == "compile":
        cmd_compile(args.agent, show_prompt=args.show_prompt, verify=not args.no_verify)
    elif args.command == "compile-large":
        run_compile_large_source(
            args.source_id,
            dry_run=args.dry_run,
            resume=args.resume,
            force=args.force,
        )
    elif args.command == "refresh":
        run_refresh_sources(branch=args.branch, fail_fast=args.fail_fast)
        cmd_compile(args.agent)
    elif args.command == "heal":
        cmd_heal(args.agent, show_prompt=args.show_prompt, verify=not args.no_verify)
    elif args.command == "ask":
        cmd_ask(args.agent, args.question)
    elif args.command == "claim-map":
        cmd_claim_map(args.concept, output=args.output)
    elif args.command == "render":
        cmd_render(args.agent, args.format, args.prompt)
    elif args.command == "validate":
        run_validate_config(strict=args.strict)
    elif args.command == "install-agent-assets":
        run_install_agent_assets(
            agent=args.agent, scope=args.scope, dry_run=args.dry_run, force=args.force
        )
    elif args.command == "research-start":
        cmd_research_start(args.topic, tier=args.tier)
    elif args.command == "research-status":
        cmd_research_status(args.topic_opt or args.topic or "all")
    elif args.command == "research-collect":
        cmd_research_collect(args.agent, args.topic, tier=args.tier)
    elif args.command == "research-review":
        cmd_research_review(args.agent, args.topic, tier=args.tier)
    elif args.command == "research-report":
        cmd_research_report(
            args.agent, args.topic, tier=args.tier, require_review=not args.allow_missing_review
        )
    elif args.command == "research-import":
        cmd_research_import(
            args.topic, args.path, args.provider, canonical_origin=args.origin, tier=args.tier
        )
    elif args.command == "research-archive":
        cmd_research_archive(args.topic)
    elif args.command == "export-vault":
        run_export_vault(args.output)
    elif args.command == "export-index":
        run_export_index(output=args.output, fmt=args.format)
    elif args.command == "fetch-queue":
        run_fetch_queue(fmt=args.format)
    elif args.command == "generate-source-registry":
        run_generate_source_registry(output=args.output)
    elif args.command == "render-manifest":
        run_render_manifest(output=args.output)
    elif args.command == "suggest-links":
        run_suggest_links(
            approach=args.approach,
            min_co_cite=args.min_co_cite,
            min_shared=args.min_shared,
            emb_threshold=args.emb_threshold,
            min_gravity=args.min_gravity,
            min_jaccard=args.min_jaccard,
            min_triadic=args.min_triadic,
            ev_top_frac=args.ev_top_frac,
            min_friction=args.min_friction,
            limit=args.limit,
            fmt=args.format,
            output=args.output,
        )
    elif args.command == "graph-audit":
        run_graph_audit(fmt=args.format)
    elif args.command == "community-audit":
        run_community_audit(fmt=args.format, min_shared=args.min_shared)
    elif args.command == "review-queue":
        run_review_queue(fmt=args.format, severity=args.severity)
    elif args.command == "retract":
        run_retract(
            args.source_id,
            args.reason,
            status=args.status,
            dry_run=args.dry_run,
            fmt=args.format,
            recompute=not args.no_recompute,
        )
    elif args.command == "build-graph":
        run_build_graph(
            output=args.output,
            report_output=args.report_output,
            csv_output=args.csv_output,
            check=args.check,
            dry_run=args.dry_run,
        )
    elif args.command == "search":
        run_search_graph(args.query, limit=args.limit, scope=args.scope, fmt=args.format)
    elif args.command == "graph-traverse":
        run_traverse_graph(
            args.start, depth=args.depth, relations=args.relation, scope=args.scope, fmt=args.format
        )
    elif args.command == "retention-report":
        run_retention_report(output=args.output, limit=args.limit)
    elif args.command == "migrate-source-fields":
        run_migrate_source_fields(dry_run=args.dry_run)
    elif args.command == "normalize-frontmatter":
        run_normalize_frontmatter_cmd(dry_run=args.dry_run)
    elif args.command == "normalize-github-sources":
        run_normalize_github_sources(dry_run=args.dry_run)
    elif args.command == "bootstrap":
        run_bootstrap(
            target=args.target,
            project_name=args.project_name,
            with_examples=args.with_examples,
            force=args.force,
        )
    elif args.command == "backfill-source-notes":
        run_backfill_source_notes(dry_run=args.dry_run)
    elif args.command == "backfill-source-metadata":
        run_backfill_source_metadata(dry_run=args.dry_run)
    elif args.command == "backfill-concept-quality":
        run_backfill_concept_quality(dry_run=args.dry_run)
    elif args.command == "backfill-answer-quality":
        run_backfill_answer_quality(dry_run=args.dry_run)
    elif args.command == "extract-claims":
        run_extract_claims(check=args.check, dry_run=args.dry_run)
    elif args.command == "claim-search":
        run_claim_search(args.query, limit=args.limit, fmt=args.format)
    elif args.command == "extract-contradictions":
        run_extract_contradictions(check=args.check, dry_run=args.dry_run)
    elif args.command == "verify-spans":
        run_verify_spans(check=args.check, dry_run=args.dry_run)
    elif args.command == "signal-log":
        run_signal_log(record=args.record, check=args.check, fmt=args.format)
    elif args.command == "next-action":
        run_next_action(fmt=args.format, check=args.check)
    elif args.command == "contradiction-search":
        run_contradiction_search(args.query, limit=args.limit, fmt=args.format)
    elif args.command in {"scorecard", "audit-kb"}:
        run_scorecard(output=args.output, fmt=args.format, check=args.check, dry_run=args.dry_run)
    elif args.command == "stale-impact":
        run_stale_impact(fmt=args.format)
    elif args.command == "clear-stale-flags":
        run_clear_stale_flags(dry_run=args.dry_run)
    elif args.command == "maintenance":
        run_maintenance(agent=args.agent, clean_tmp=args.clean_tmp, check_drift=args.check_drift)
    elif args.command == "generate-probes":
        run_generate_probes()
    elif args.command == "evaluate":
        run_evaluate(
            limit=args.limit,
            probe_id=args.probe_id,
            workers=args.workers,
            verbose=args.verbose,
        )
    elif args.command == "lint":
        run_lint(strict=args.strict, fix_backlinks=args.fix_backlinks, check=args.check)
    elif args.command == "check-drift":
        import sys as _sys
        from kops.check_source_drift import check as _check, _print_report as _report

        results, code = _check(flag=args.flag, only=set(args.source) if args.source else None)
        if args.json:
            import json as _json

            print(_json.dumps({"results": results, "flagged": args.flag}, indent=2))
        else:
            _report(results, flagged=args.flag)
        _sys.exit(code)


if __name__ == "__main__":
    main()
