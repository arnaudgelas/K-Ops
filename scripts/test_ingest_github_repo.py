from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def main() -> None:
    sys.path.append(str(ROOT / "scripts"))
    from ingest_github_repo import collect_candidate_files, detect_project_signals, render_snapshot_markdown, summarize_files  # noqa: WPS433

    with tempfile.TemporaryDirectory(prefix="living-kb-git-test-") as tmp:
        repo_dir = Path(tmp) / "repo"
        repo_dir.mkdir()

        run_git(["init"], repo_dir)
        run_git(["config", "user.name", "Test User"], repo_dir)
        run_git(["config", "user.email", "test@example.com"], repo_dir)

        files = {
            "README.md": "# Project\n\nLanding page only.\n",
            "docs/guide.md": "# Guide\n\nDeep docs live here.\n",
            "src/app.py": "def main():\n    return 1\n",
            "tests/test_app.py": "def test_main():\n    assert True\n",
            ".github/workflows/ci.yml": "name: ci\n",
            "package.json": "{\n  \"name\": \"example\"\n}\n",
            "notes/architecture/design.md": "# Design\n\nNested documentation.\n",
        }

        for rel_path, content in files.items():
            path = repo_dir / rel_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        run_git(["add", "."], repo_dir)
        run_git(["commit", "-m", "Initial commit"], repo_dir)

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

        missing = sorted(required.difference(selected_paths))
        if missing:
            raise AssertionError(f"Expected repository-wide file selection, missing: {missing}\nSelected: {selected_paths}")

        if selected_paths[0] != "notes/architecture/design.md":
            raise AssertionError(f"Architecture evidence should lead the selection, got: {selected_paths[0]!r}")

        if selected_paths.index("README.md") > selected_paths.index("src/app.py"):
            raise AssertionError(f"README.md should still outrank implementation files.\nSelected: {selected_paths}")

        if len(selected_paths) > 20:
            raise AssertionError(f"Selection exceeded the configured cap: {len(selected_paths)}")

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
            if section not in snapshot:
                raise AssertionError(f"Missing expected snapshot section: {section!r}\nSnapshot:\n{snapshot}")

        print("ingest_github_repo regression passed")


if __name__ == "__main__":
    main()
