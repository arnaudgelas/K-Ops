from __future__ import annotations

import argparse

import kb as _kb
import research_workflow as _rw
import render_manifest as _rm
from utils import ROOT


def main() -> None:
    parser = argparse.ArgumentParser(description="Living research vault workflow")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest")
    p_ingest.add_argument("--input", required=True)
    p_ingest.add_argument("--branch", help="Optional branch override for GitHub repository URLs in the input list.")
    p_ingest.add_argument("--fail-fast", action="store_true")

    p_ingest_github = sub.add_parser("ingest-github")
    p_ingest_github.add_argument("--repo", required=True)
    p_ingest_github.add_argument("--branch")
    p_ingest_github.add_argument("--compile-agent", choices=["codex", "claude", "gemini"])

    p_compile = sub.add_parser("compile")
    p_compile.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_compile.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the prompt that would be sent without invoking the agent.",
    )

    p_refresh = sub.add_parser("refresh")
    p_refresh.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_refresh.add_argument("--branch", help="Optional branch override for GitHub repository URLs during refresh.")
    p_refresh.add_argument("--fail-fast", action="store_true")
    p_refresh.add_argument(
        "--force-compile",
        action="store_true",
        help="Run compile even if no source content changed.",
    )

    p_heal = sub.add_parser("heal")
    p_heal.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_heal.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the prompt that would be sent without invoking the agent.",
    )

    p_ask = sub.add_parser("ask")
    p_ask.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_ask.add_argument("--question", required=True)

    p_render = sub.add_parser("render")
    p_render.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_render.add_argument("--format", required=True, choices=["memo", "slides", "outline", "report"])
    p_render.add_argument("--prompt", required=True)

    p_install_assets = sub.add_parser("install-agent-assets")
    p_install_assets.add_argument("--agent", choices=["all", "claude", "gemini", "codex"], default="all")
    p_install_assets.add_argument("--scope", choices=["project", "home", "both"], default="both")
    p_install_assets.add_argument("--dry-run", action="store_true")
    p_install_assets.add_argument("--force", action="store_true")

    p_research_start = sub.add_parser("research-start")
    p_research_start.add_argument("--topic", required=True)
    p_research_start.add_argument("--tier", choices=sorted(_rw.RESEARCH_TIERS), default="standard")

    p_research_status = sub.add_parser("research-status")
    p_research_status.add_argument("topic", nargs="?", default=None)
    p_research_status.add_argument("--topic", dest="topic_opt")

    p_research_collect = sub.add_parser("research-collect")
    p_research_collect.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_research_collect.add_argument("--topic", required=True)
    p_research_collect.add_argument("--tier", choices=sorted(_rw.RESEARCH_TIERS), default="standard")

    p_research_review = sub.add_parser("research-review")
    p_research_review.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_research_review.add_argument("--topic", required=True)
    p_research_review.add_argument("--tier", choices=sorted(_rw.RESEARCH_TIERS), default="standard")

    p_research_report = sub.add_parser("research-report")
    p_research_report.add_argument("--agent", choices=["codex", "claude", "gemini"], required=True)
    p_research_report.add_argument("--topic", required=True)
    p_research_report.add_argument("--tier", choices=sorted(_rw.RESEARCH_TIERS), default="standard")
    p_research_report.add_argument("--allow-missing-review", action="store_true")

    p_research_import = sub.add_parser("research-import")
    p_research_import.add_argument("--topic", required=True)
    p_research_import.add_argument("--path", required=True)
    p_research_import.add_argument(
        "--provider",
        choices=["gemini", "openai", "claude", "perplexity", "other"],
        default="other",
    )
    p_research_import.add_argument("--origin")
    p_research_import.add_argument("--tier", choices=sorted(_rw.RESEARCH_TIERS), default="standard")

    p_research_archive = sub.add_parser("research-archive")
    p_research_archive.add_argument("--topic", required=True)

    p_export = sub.add_parser("export-vault")
    p_export.add_argument("--output")

    p_export_index = sub.add_parser("export-index")
    p_export_index.add_argument("--output")
    p_export_index.add_argument("--format", choices=["json", "csv"], default="json")

    p_build_graph = sub.add_parser("build-graph")
    p_build_graph.add_argument("--output")
    p_build_graph.add_argument("--report-output")
    p_build_graph.add_argument("--csv-output")

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

    p_normalize_github = sub.add_parser("normalize-github-sources")
    p_normalize_github.add_argument("--dry-run", action="store_true")

    sub.add_parser("validate", help="Print the loaded config and verify all required paths.")

    p_bootstrap = sub.add_parser("bootstrap")
    p_bootstrap.add_argument("--target", required=True, help="Directory for the new blank starter vault.")
    p_bootstrap.add_argument("--project-name", help="Optional project name to write into the generated config.")
    p_bootstrap.add_argument("--with-examples", action="store_true", help="Add a tiny examples folder with starter input files.")
    p_bootstrap.add_argument("--force", action="store_true", help="Overwrite the starter scaffold even if the target already exists.")

    p_backfill_metadata = sub.add_parser("backfill-source-metadata")
    p_backfill_metadata.add_argument("--dry-run", action="store_true")

    p_backfill_concept_quality = sub.add_parser("backfill-concept-quality")
    p_backfill_concept_quality.add_argument("--dry-run", action="store_true")

    p_backfill_answer_quality = sub.add_parser("backfill-answer-quality")
    p_backfill_answer_quality.add_argument("--dry-run", action="store_true")

    p_backfill_notes = sub.add_parser("backfill-source-notes")
    p_backfill_notes.add_argument("--dry-run", action="store_true")

    p_maintain = sub.add_parser("maintenance")
    p_maintain.add_argument(
        "--agent",
        choices=["codex", "claude", "gemini"],
        help="Optional agent to refresh and compile before the mechanical maintenance pass.",
    )

    sub.add_parser("extract-claims", help="Extract atomic claims from concept pages and write data/claims.json.")

    p_claim_search = sub.add_parser("claim-search", help="Search the claims registry by keyword.")
    p_claim_search.add_argument("--query", required=True)
    p_claim_search.add_argument("--limit", type=int, default=20)
    p_claim_search.add_argument("--format", choices=["text", "json"], default="text")

    p_stale_impact = sub.add_parser("stale-impact", help="Report concept pages flagged for revalidation after source changes.")
    p_stale_impact.add_argument("--format", choices=["text", "json"], default="text")

    p_clear_stale = sub.add_parser("clear-stale-flags", help="Remove revalidation_required flags from all concept pages and answers.")
    p_clear_stale.add_argument("--dry-run", action="store_true")

    p_scorecard = sub.add_parser("scorecard", help="Compute vault health scorecard and write data/scorecard.json.")
    p_scorecard.add_argument("--output", help="Override output path.")
    p_scorecard.add_argument("--format", choices=["text", "json"], default="text")

    sub.add_parser("eval-setup", help="Create the golden Q&A evaluation scaffold at tests/qa_golden.yaml.")
    sub.add_parser("eval-check", help="Validate the golden Q&A file at tests/qa_golden.yaml.")
    sub.add_parser("extract-contradictions", help="Extract contradiction records from conflicting concepts and write data/contradictions.json.")

    p_contradiction_search = sub.add_parser("contradiction-search", help="Search the contradiction registry by keyword.")
    p_contradiction_search.add_argument("--query", required=True)
    p_contradiction_search.add_argument("--limit", type=int, default=20)
    p_contradiction_search.add_argument("--format", choices=["text", "json"], default="text")

    p_lint = sub.add_parser("lint")
    p_lint.add_argument("--strict", action="store_true")
    p_lint.add_argument("--fix-backlinks", action="store_true")

    sub.add_parser("render-manifest", help="Print a JSON manifest of the registry and vault files.")

    args = parser.parse_args()

    if args.command == "ingest":
        _kb.run_fetch(args.input, branch=args.branch, fail_fast=args.fail_fast)
    elif args.command == "ingest-github":
        _kb.run_ingest_github(args.repo, args.branch)
        if args.compile_agent:
            _kb._kr.cmd_compile(args.compile_agent)
    elif args.command == "compile":
        _kb._kr.cmd_compile(args.agent, dry_run=args.dry_run)
    elif args.command == "refresh":
        _refresh_list, changed = _kb.run_refresh_sources(branch=args.branch, fail_fast=args.fail_fast)
        if changed or args.force_compile:
            if changed:
                print(f"{len(changed)} source(s) changed content — running compile.")
                affected = _kb.propagate_stale_flags(changed)
                if affected:
                    print(f"Flagged {len(affected)} concept(s) for revalidation (run 'stale-impact' to review):")
                    for p in affected:
                        print(f"  - {p.relative_to(ROOT)}")
            else:
                print("--force-compile set — running compile despite no content changes.")
            _kb._kr.cmd_compile(args.agent)
        else:
            print("All sources unchanged — skipping compile.")
    elif args.command == "heal":
        _kb._kr.cmd_heal(args.agent, dry_run=args.dry_run)
    elif args.command == "ask":
        _kb._kr.cmd_ask(args.agent, args.question)
    elif args.command == "render":
        _kb._kr.cmd_render(args.agent, args.format, args.prompt)
    elif args.command == "install-agent-assets":
        _kb.run_install_agent_assets(agent=args.agent, scope=args.scope, dry_run=args.dry_run, force=args.force)
    elif args.command == "research-start":
        _rw.cmd_research_start(args.topic, tier=args.tier)
    elif args.command == "research-status":
        _rw.cmd_research_status(args.topic_opt or args.topic or "all")
    elif args.command == "research-collect":
        _rw.cmd_research_collect(args.agent, args.topic, tier=args.tier)
    elif args.command == "research-review":
        _rw.cmd_research_review(args.agent, args.topic, tier=args.tier)
    elif args.command == "research-report":
        _rw.cmd_research_report(args.agent, args.topic, tier=args.tier, require_review=not args.allow_missing_review)
    elif args.command == "research-import":
        _rw.cmd_research_import(args.topic, args.path, args.provider, canonical_origin=args.origin, tier=args.tier)
    elif args.command == "research-archive":
        _rw.cmd_research_archive(args.topic)
    elif args.command == "export-vault":
        _kb.run_export_vault(args.output)
    elif args.command == "export-index":
        _kb.run_export_index(output=args.output, fmt=args.format)
    elif args.command == "build-graph":
        _kb.run_build_graph(output=args.output, report_output=args.report_output, csv_output=args.csv_output)
    elif args.command == "search":
        _kb.run_search_graph(args.query, limit=args.limit, scope=args.scope, fmt=args.format)
    elif args.command == "graph-traverse":
        _kb.run_traverse_graph(args.start, depth=args.depth, relations=args.relation, scope=args.scope, fmt=args.format)
    elif args.command == "retention-report":
        _kb.run_retention_report(output=args.output, limit=args.limit)
    elif args.command == "normalize-github-sources":
        _kb.run_normalize_github_sources(dry_run=args.dry_run)
    elif args.command == "bootstrap":
        _kb.run_bootstrap(
            target=args.target,
            project_name=args.project_name,
            with_examples=args.with_examples,
            force=args.force,
        )
    elif args.command == "backfill-source-notes":
        _kb.run_backfill_source_notes(dry_run=args.dry_run)
    elif args.command == "backfill-source-metadata":
        _kb.run_backfill_source_metadata(dry_run=args.dry_run)
    elif args.command == "backfill-concept-quality":
        _kb.run_backfill_concept_quality(dry_run=args.dry_run)
    elif args.command == "backfill-answer-quality":
        _kb.run_backfill_answer_quality(dry_run=args.dry_run)
    elif args.command == "maintenance":
        _kb.run_maintenance(agent=args.agent)
    elif args.command == "extract-claims":
        _kb.run_extract_claims()
    elif args.command == "claim-search":
        _kb.run_claim_search(args.query, limit=args.limit, fmt=args.format)
    elif args.command == "stale-impact":
        _kb.run_stale_impact(fmt=args.format)
    elif args.command == "clear-stale-flags":
        _kb.run_clear_stale_flags(dry_run=args.dry_run)
    elif args.command == "scorecard":
        _kb.run_scorecard(output=args.output, fmt=args.format)
    elif args.command == "eval-setup":
        _kb.run_eval_setup()
    elif args.command == "eval-check":
        _kb.run_eval_check()
    elif args.command == "extract-contradictions":
        _kb.run_extract_contradictions()
    elif args.command == "contradiction-search":
        _kb.run_contradiction_search(args.query, limit=args.limit, fmt=args.format)
    elif args.command == "lint":
        _kb.run_lint(strict=args.strict, fix_backlinks=args.fix_backlinks)
    elif args.command == "render-manifest":
        _rm.main()
    elif args.command == "validate":
        _kb.run_validate_config()
