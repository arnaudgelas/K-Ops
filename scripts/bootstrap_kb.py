from __future__ import annotations

import argparse
import re
import shutil
import textwrap
from pathlib import Path

from utils import ensure_dir, slugify


ROOT = Path(__file__).resolve().parent.parent
MACHINERY_DIRS = ("scripts", "templates", "skills")
GITIGNORE_SOURCE = ROOT / ".gitignore"


def pretty_name(project_name: str) -> str:
    parts = [part for part in re.split(r"[^a-zA-Z0-9]+", project_name) if part]
    return " ".join(part.capitalize() for part in parts) or "Knowledge Base"


def render_readme(project_name: str) -> str:
    title = pretty_name(project_name)
    return textwrap.dedent(
        f"""\
        # {title}

        `{project_name}` is a blank, agent-first Markdown knowledge base starter.

        It includes the workflow machinery needed to ingest sources, compile notes, answer questions, and render outputs, but it starts without any imported source corpus.

        ## What Is Included

        - `scripts/` for ingestion, compilation, healing, linting, and rendering
        - `templates/` for agent prompts
        - `skills/` for reusable skill definitions
        - `notes/` for the Obsidian vault structure
        - `config/kb_config.yaml` for repo-local path settings

        ## First Steps

        1. Install `uv`.
        2. Run `uv sync`.
        3. Add your first URLs or files to an input list.
        4. Run `uv run python scripts/kb.py ingest --input <file>`.
        5. Run `uv run python scripts/kb.py compile --agent codex`.
        6. Use `uv run python scripts/kb.py lint` after structural edits.

        ## Starter Notes

        - `notes/Home.md` is the Obsidian entry point.
        - `notes/TODO.md` tracks follow-up work.
        - `notes/Runbooks/Agent_Workflow_Quick_Reference.md` summarizes the repo commands.
        - `notes/_Templates/` contains note templates for source summaries and concept pages.
        """
    ).strip() + "\n"


def render_agents() -> str:
    return textwrap.dedent(
        """\
        # AGENTS.md

        This repo is designed for agentic CLI workflows.

        ## Roles

        ### Source Ingestor
        Goal: transform new raw sources into normalized source summaries.

        ### Wiki Compiler
        Goal: merge source summaries into durable concept pages and indexes.

        ### Lint + Heal
        Goal: detect contradictions, weak structure, missing backlinks, and unsupported claims.

        ### Q&A Agent
        Goal: answer using the vault, then file durable insights back into the vault.

        ### Render Agent
        Goal: convert the current vault into memos, briefings, slide outlines, diagrams, and plot specs.

        ## Repo Contract
        - `data/raw/` holds source evidence
        - `notes/Sources/` holds per-source summaries
        - `notes/Concepts/` holds durable knowledge pages
        - `notes/Answers/` holds generated answer memos
        - `notes/Home.md` is the Obsidian entry point
        - `notes/TODO.md` tracks gaps and healing tasks
        - `notes/Runbooks/Agent_Workflow_Quick_Reference.md` is the compact operator map for cross-CLI workflows

        ## Behavioral Guardrails
        - Prefer modifying a small number of files with high signal.
        - Prefer precise edits over broad rewrites.
        - Preserve provenance from source summaries into concept pages.
        - When uncertain, mark uncertainty explicitly.
        """
    ).strip() + "\n"


def render_claude(project_name: str) -> str:
    title = pretty_name(project_name)
    return textwrap.dedent(
        f"""\
        # CLAUDE.md

        This repository is a starter Obsidian-aligned living research vault. The same operating contract should work whether the active CLI is Claude Code, Codex CLI, or Gemini CLI.

        ## Mission
        Turn raw sources into a durable Markdown knowledge base. Every answer should either:
        1. reference existing vault notes, or
        2. improve the vault if durable new knowledge was produced.

        ## Operating Rules
        - Treat `data/raw/` as immutable source evidence.
        - Treat `notes/` as the curated Obsidian vault.
        - Prefer updating existing concept pages instead of creating duplicates.
        - Keep always-on instructions short; move command detail into runbooks, skills, or templates.
        - Every concept page should link to related pages and relevant source summaries.
        - Record contradictions, uncertainties, and missing evidence explicitly.
        - Do not silently invent citations.
        - If a question cannot be answered from the vault, say so and propose the minimum fetch needed.

        ## Default Workflow
        1. Read relevant source summaries in `notes/Sources/`.
        2. Read the linked concept pages in `notes/Concepts/`.
        3. Use `notes/Runbooks/Agent_Workflow_Quick_Reference.md` when you need command syntax or command order.
        4. Answer from the vault.
        5. If the answer yields durable knowledge, file it back into the vault.
        6. Run `lint` after structural edits.
        7. Update `notes/Home.md` and `notes/TODO.md` when the vault's structure or gaps change.

        ## Page Conventions
        Each concept page should usually contain:
        - What it is
        - Why it matters
        - Key claims
        - Evidence / source basis
        - Related concepts
        - Open questions
        - Backlinks

        ## Reference Notes
        - `notes/Runbooks/Agent_Workflow_Quick_Reference.md`

        ## Obsidian Conventions
        - Use Obsidian-style wikilinks for internal note links when editing curated notes.
        - Keep note filenames stable and human-readable.
        - Prefer frontmatter on durable notes so properties remain queryable in Obsidian.
        """
    ).strip() + "\n"


def render_home(project_name: str) -> str:
    title = pretty_name(project_name)
    return textwrap.dedent(
        f"""\
        ---
        title: "Home"
        type: home
        tags:
          - kb/home
        ---
        # Home

        ## Scope

        `{title}` starts empty. Add sources, compile summaries, and let the vault grow from there.

        ## Start Here

        - Read `notes/Runbooks/Agent_Workflow_Quick_Reference.md`
        - Add your first source list
        - Run `uv run python scripts/kb.py ingest --input <file>`
        - Compile with `uv run python scripts/kb.py compile --agent codex`

        ## Maintenance

        - [[TODO|TODO]]
        """
    ).strip() + "\n"


def render_todo() -> str:
    return textwrap.dedent(
        """\
        ---
        title: "TODO"
        type: note
        tags:
          - kb/todo
        ---
        # TODO

        ## Starter Tasks

        - Add your first sources under `data/raw/`.
        - Ingest them into `notes/Sources/`.
        - Compile the first concept pages.
        - Replace these placeholder tasks with project-specific follow-ups.
        """
    ).strip() + "\n"


def render_runbook() -> str:
    return textwrap.dedent(
        """\
        ---
        title: "Agent Workflow Quick Reference"
        type: maintenance
        tags:
          - kb/maintenance
          - kb/runbook
        ---
        # Agent Workflow Quick Reference

        Compact command map for the starter vault.

        ## Commands

        | Command | Use When | Notes |
        |---|---|---|
        | `ingest` | You have a newline-delimited list of URLs or file paths | Writes raw evidence into `data/raw/` and updates `data/registry.json` |
        | `ingest-github` | You want a single GitHub repository snapshot | Captures repo docs and writes a raw snapshot |
        | `compile` | You want source summaries and concept pages | Uses the active agent CLI |
        | `ask` | You want a durable answer memo | Writes to `notes/Answers/` and may file insights back into the vault |
        | `heal` | You need structural cleanup | Runs lint-and-repair behavior |
        | `lint` | You want consistency checks | Verifies registry, backlinks, and note structure |
        | `refresh` | You want to re-check known sources | Re-fetches registered sources before compiling |
        | `backfill-source-notes` | You need missing source summaries created | Uses registry and raw artifacts |
        | `bootstrap` | You want a fresh blank starter vault | Creates another copy of this file structure |

        ## Safe Order

        1. `ingest`
        2. `compile`
        3. `ask`
        4. `heal`
        5. `lint`

        ## Rules

        - Keep `data/raw/` empty until you actually ingest something.
        - Keep `notes/Home.md` as the main navigation entry point.
        - Use `notes/_Templates/` for note templates, not for source evidence.
        """
    ).strip() + "\n"


def render_source_template() -> str:
    return textwrap.dedent(
        """\
        ---
        title: "{{title}}"
        type: source-summary
        source_id: "{{source_id}}"
        evidence_strength: "{{evidence_strength}}"
        tags:
          - kb/source
        ---

        # {{title}}

        ## Summary

        ## Key Claims

        ## Evidence Notes

        ## Related Concepts

        ## Backlinks
        """
    ).strip() + "\n"


def render_concept_template() -> str:
    return textwrap.dedent(
        """\
        ---
        title: "{{title}}"
        type: concept
        tags:
          - kb/concept
        claim_quality: "{{claim_quality}}"
        ---

        # {{title}}

        ## What It Is

        ## Why It Matters

        ## Key Claims

        ## Evidence / Source Basis

        ## Related Concepts

        ## Open Questions

        ## Backlinks
        """
    ).strip() + "\n"


def render_readme_example() -> str:
    return textwrap.dedent(
        """\
        # Sample Note

        This is a local note that can be ingested like any other source.

        - A living wiki is more inspectable than an opaque retrieval index.
        - Durable answers should be filed back into the knowledge base.
        """
    ).strip() + "\n"


def copy_dir(source: Path, target: Path) -> None:
    if not source.exists():
        return
    shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def create_obsidian_files(target_root: Path) -> None:
    obsidian_dir = target_root / ".obsidian"
    ensure_dir(obsidian_dir)
    (obsidian_dir / "app.json").write_text(
        textwrap.dedent(
            """\
            {
              "alwaysUpdateLinks": true,
              "attachmentFolderPath": "notes/Attachments",
              "newFileLocation": "folder",
              "newFileFolderPath": "notes",
              "showInlineTitle": true,
              "useMarkdownLinks": false
            }
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (obsidian_dir / "appearance.json").write_text("{}\n", encoding="utf-8")
    (obsidian_dir / "core-plugins.json").write_text(
        textwrap.dedent(
            """\
            {
              "file-explorer": true,
              "global-search": true,
              "switcher": false,
              "graph": true,
              "backlink": true,
              "outgoing-link": true,
              "tag-pane": true,
              "page-preview": true,
              "daily-notes": false,
              "templates": true,
              "note-composer": false,
              "command-palette": false,
              "slash-command": false,
              "editor-status": false,
              "markdown-importer": false,
              "zk-prefixer": false,
              "random-note": false,
              "outline": true,
              "word-count": false,
              "slides": false,
              "audio-recorder": false,
              "workspaces": false,
              "file-recovery": false,
              "publish": false,
              "sync": false,
              "canvas": true,
              "footnotes": false,
              "properties": true,
              "bookmarks": true,
              "bases": true,
              "webviewer": false
            }
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (obsidian_dir / "templates.json").write_text('{ "folder": "notes/_Templates" }\n', encoding="utf-8")
    (obsidian_dir / "workspace.json").write_text("{}\n", encoding="utf-8")


def create_gitignore(target_root: Path) -> None:
    if GITIGNORE_SOURCE.exists():
        shutil.copy2(GITIGNORE_SOURCE, target_root / ".gitignore")


def create_pyproject(target_root: Path, project_name: str) -> None:
    pyproject = textwrap.dedent(
        f"""\
        [project]
        name = "{project_name}"
        version = "0.1.0"
        description = "Starter agent-first Markdown knowledge base."
        readme = "README.md"
        requires-python = ">=3.11"
        dependencies = [
          "beautifulsoup4>=4.12.0",
          "pypdf>=5.0.0",
          "pyyaml>=6.0.0",
          "requests>=2.32.0",
          "trafilatura>=1.9.0",
        ]

        [build-system]
        requires = ["hatchling"]
        build-backend = "hatchling.build"

        [tool.uv]
        package = false
        """
    ).strip() + "\n"
    (target_root / "pyproject.toml").write_text(pyproject, encoding="utf-8")


def create_config(target_root: Path, project_name: str) -> None:
    config_dir = target_root / "config"
    ensure_dir(config_dir)
    config_text = textwrap.dedent(
        f"""\
        project_name: {project_name}
        raw_dir: data/raw
        registry_path: data/registry.json
        vault_dir: notes
        home_note: notes/Home.md
        todo_note: notes/TODO.md
        concepts_dir: notes/Concepts
        summaries_dir: notes/Sources
        answers_dir: notes/Answers
        attachments_dir: notes/Attachments
        outputs_dir: outputs
        allow_web_fetch_during_qa: false
        file_answer_back_into_vault: true
        use_obsidian_wikilinks: true
        """
    ).strip() + "\n"
    (config_dir / "kb_config.yaml").write_text(config_text, encoding="utf-8")


def create_data_layout(target_root: Path) -> None:
    data_dir = target_root / "data"
    raw_dir = data_dir / "raw"
    ensure_dir(raw_dir)
    (data_dir / "registry.json").write_text("[]\n", encoding="utf-8")
    (raw_dir / ".gitkeep").write_text("", encoding="utf-8")


def create_notes_layout(target_root: Path, project_name: str) -> None:
    notes_dir = target_root / "notes"
    ensure_dir(notes_dir)
    for subdir in ("Concepts", "Sources", "Answers", "Attachments", "Runbooks", "_Archive", "_Templates"):
        ensure_dir(notes_dir / subdir)

    (notes_dir / "Home.md").write_text(render_home(project_name), encoding="utf-8")
    (notes_dir / "TODO.md").write_text(render_todo(), encoding="utf-8")
    (notes_dir / "Runbooks" / "Agent_Workflow_Quick_Reference.md").write_text(render_runbook(), encoding="utf-8")
    (notes_dir / "_Templates" / "Source_Summary.md").write_text(render_source_template(), encoding="utf-8")
    (notes_dir / "_Templates" / "Concept_Note.md").write_text(render_concept_template(), encoding="utf-8")

    for path in (
        notes_dir / "Concepts" / ".gitkeep",
        notes_dir / "Sources" / ".gitkeep",
        notes_dir / "Answers" / ".gitkeep",
        notes_dir / "Attachments" / ".gitkeep",
        notes_dir / "Runbooks" / ".gitkeep",
        notes_dir / "_Archive" / ".gitkeep",
    ):
        path.write_text("", encoding="utf-8")


def create_examples(target_root: Path) -> None:
    examples_dir = target_root / "examples"
    ensure_dir(examples_dir)
    (examples_dir / "links.txt").write_text(
        textwrap.dedent(
            """\
            # URLs or local paths, one per line
            # https://example.com/article
            # ./notes/Home.md
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def bootstrap(target: Path, project_name: str | None = None, with_examples: bool = False, force: bool = False) -> None:
    if target.exists() and any(target.iterdir()) and not force:
        raise SystemExit(f"Target directory already exists and is not empty: {target}")
    ensure_dir(target)

    project = project_name or slugify(target.name)

    for directory in MACHINERY_DIRS:
        copy_dir(ROOT / directory, target / directory)

    create_gitignore(target)
    create_pyproject(target, project)
    create_config(target, project)
    create_obsidian_files(target)
    create_data_layout(target)
    create_notes_layout(target, project)
    (target / "README.md").write_text(render_readme(project), encoding="utf-8")
    (target / "AGENTS.md").write_text(render_agents(), encoding="utf-8")
    (target / "CLAUDE.md").write_text(render_claude(project), encoding="utf-8")

    if with_examples:
        create_examples(target)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a blank starter knowledge-base repository.")
    parser.add_argument("--target", required=True, help="Directory to create for the new starter vault.")
    parser.add_argument("--project-name", help="Optional project name to write into config and metadata.")
    parser.add_argument("--with-examples", action="store_true", help="Add a small examples/ folder with starter input files.")
    parser.add_argument("--force", "--froce", action="store_true", help="Overwrite the starter scaffold even if the target directory already exists.")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    bootstrap(target, project_name=args.project_name, with_examples=args.with_examples, force=args.force)
    print(f"Created starter knowledge base at {target}")


if __name__ == "__main__":
    main()
