"""Tests for repository snapshot ingestion helpers."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kops.ingest_github_repo import (  # noqa: E402
    collect_candidate_files,
    detect_project_signals,
    render_snapshot_markdown,
    summarize_files,
)
from kops.kb_schema import Validator  # noqa: E402


def _run_git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_repository_snapshot_selection_and_metadata_validation(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    _run_git(["init"], repo_dir)
    _run_git(["config", "user.name", "Test User"], repo_dir)
    _run_git(["config", "user.email", "test@example.com"], repo_dir)

    files = {
        "README.md": "# Project\n\nLanding page only.\n",
        "docs/guide.md": "# Guide\n\nDeep docs live here.\n",
        "src/app.py": "def main():\n    return 1\n",
        "tests/test_app.py": "def test_main():\n    assert True\n",
        ".github/workflows/ci.yml": "name: ci\n",
        "package.json": '{\n  "name": "example"\n}\n',
        "notes/architecture/design.md": "# Design\n\nNested documentation.\n",
    }

    for rel_path, content in files.items():
        path = repo_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    _run_git(["add", "."], repo_dir)
    _run_git(["commit", "-m", "Initial commit"], repo_dir)

    tracked_files = [repo_dir / rel_path for rel_path in sorted(files)]
    selected = collect_candidate_files(repo_dir, tracked_files)
    selected_paths = [path.relative_to(repo_dir).as_posix() for path in selected]

    required = {
        "README.md",
        "docs/guide.md",
        "src/app.py",
        "tests/test_app.py",
        ".github/workflows/ci.yml",
        "package.json",
        "notes/architecture/design.md",
    }
    assert required <= set(selected_paths)
    assert selected_paths[0] == "notes/architecture/design.md"
    assert selected_paths.index("README.md") < selected_paths.index("src/app.py")
    assert len(selected_paths) <= 20

    signals = detect_project_signals(tracked_files, repo_dir)
    summaries = summarize_files("example", "repo", "main", repo_dir, selected)
    snapshot = render_snapshot_markdown(
        repo_url="https://github.com/example/repo",
        owner="example",
        repo_name="repo",
        branch="main",
        commit="deadbeef",
        source_id="src-test",
        signals=signals,
        file_summaries=summaries,
    )

    for section in ("## Key Concepts", "## Architectural Decisions", "## Key Files"):
        assert section in snapshot

    validator = Validator()
    metadata = {
        "id": "src-test",
        "source": "https://github.com/example/repo",
        "ingested_at": "2026-06-12T00:00:00Z",
        "kind": "github_repo_snapshot",
        "content_type": "text/markdown",
        "git_commit": "deadbeef",
        "git_branch": "main",
        "tracked_file_count": len(tracked_files),
        "sampled_file_count": len(selected),
        "sampled_paths": selected_paths,
        "omitted_paths_manifest": [],
        "coverage_policy": {
            "max_evidence_files": 20,
        },
    }

    issues = validator.validate_metadata_json(metadata, Path("metadata.json"))
    assert not [issue for issue in issues if issue.severity == "error"]

    missing_metadata = metadata.copy()
    del missing_metadata["git_commit"]
    issues = validator.validate_metadata_json(missing_metadata, Path("metadata.json"))
    assert [
        issue for issue in issues if issue.severity == "warning" and issue.field == "git_commit"
    ]

    bad_type_metadata = metadata.copy()
    bad_type_metadata["tracked_file_count"] = "not-an-integer"
    issues = validator.validate_metadata_json(bad_type_metadata, Path("metadata.json"))
    assert [
        issue
        for issue in issues
        if issue.severity == "error" and issue.field == "tracked_file_count"
    ]
