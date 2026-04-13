from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from utils import CONFIG, ROOT, ensure_dir, load_json, now_stamp, save_json, short_hash

REGISTRY_PATH = CONFIG.registry_path
RAW_DIR = CONFIG.raw_dir

ROOT_DOC_NAMES = [
    "README.md",
    "README.rst",
    "README.txt",
    "CONTRIBUTING.md",
    "ARCHITECTURE.md",
    "DESIGN.md",
    "CHANGELOG.md",
    "docs/README.md",
]
DOC_SUFFIXES = {".md", ".rst", ".txt"}
MANIFEST_NAMES = {
    "pyproject.toml": "Python",
    "requirements.txt": "Python",
    "package.json": "Node.js",
    "Cargo.toml": "Rust",
    "go.mod": "Go",
    "pom.xml": "Java",
    "build.gradle": "Java/Gradle",
    "Gemfile": "Ruby",
    "composer.json": "PHP",
    "Dockerfile": "Docker",
    "docker-compose.yml": "Docker Compose",
    "docker-compose.yaml": "Docker Compose",
}
EXTENSION_LABELS = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cpp": "C++",
    ".c": "C",
    ".swift": "Swift",
}
MAX_DOCS = 10
MAX_HEADINGS = 5
MAX_PARAGRAPH_CHARS = 400
MAX_RELEVANT_DIRS = 8


def parse_github_repo(repo: str) -> tuple[str, str]:
    normalized = repo.strip()
    ssh_match = re.match(r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$", normalized)
    if ssh_match:
        return ssh_match.group(1), ssh_match.group(2)

    parsed = urlsplit(normalized)
    if parsed.scheme in {"http", "https"} and parsed.netloc == "github.com":
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2:
            owner = parts[0]
            repo_name = re.sub(r"\.git$", "", parts[1])
            if owner and repo_name:
                return owner, repo_name

    raise ValueError(f"Unsupported GitHub repository URL: {repo}")


def github_clone_url(repo: str) -> str:
    owner, repo_name = parse_github_repo(repo)
    return f"https://github.com/{owner}/{repo_name}.git"


def github_home_url(repo: str) -> str:
    owner, repo_name = parse_github_repo(repo)
    return f"https://github.com/{owner}/{repo_name}"


def run_git(args: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        check=False,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        details = stderr or stdout or f"`git {' '.join(args)}` exited with status {result.returncode}"
        raise RuntimeError(details)
    return result.stdout.strip()


def clone_repo(repo_url: str, branch: str | None) -> Path:
    tmp_root = Path(tempfile.mkdtemp(prefix="living-kb-github-", dir="/tmp"))
    clone_dir = tmp_root / "repo"
    cmd = ["clone", "--depth", "1"]
    if branch:
        cmd.extend(["--branch", branch])
    cmd.extend([github_clone_url(repo_url), str(clone_dir)])
    run_git(cmd)
    return clone_dir


def detect_branch(repo_dir: Path) -> str:
    return run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir)


def detect_commit(repo_dir: Path) -> str:
    return run_git(["rev-parse", "HEAD"], cwd=repo_dir)


def list_tracked_files(repo_dir: Path) -> list[Path]:
    output = run_git(["ls-files"], cwd=repo_dir)
    if not output:
        return []
    return [repo_dir / line for line in output.splitlines() if line.strip()]


def github_blob_url(owner: str, name: str, branch: str, path: Path) -> str:
    rel_path = path.as_posix().strip("/")
    return f"https://github.com/{owner}/{name}/blob/{branch}/{rel_path}"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def first_heading(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return None


def extract_first_paragraph(text: str) -> str | None:
    lines = text.splitlines()
    chunks: list[str] = []
    in_code_block = False
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if not stripped:
            if chunks:
                break
            continue
        if stripped.startswith("#") or stripped.startswith("![") or stripped.startswith(">"):
            if chunks:
                break
            continue
        chunks.append(stripped)
    if not chunks:
        return None
    paragraph = " ".join(chunks)
    return paragraph[:MAX_PARAGRAPH_CHARS].strip()


def extract_headings(text: str) -> list[str]:
    headings: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                headings.append(heading)
        if len(headings) >= MAX_HEADINGS:
            break
    return headings


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def collect_candidate_docs(repo_dir: Path, tracked_files: list[Path]) -> list[Path]:
    repo_relative = [path.relative_to(repo_dir) for path in tracked_files]
    chosen: list[Path] = []
    seen: set[Path] = set()

    for doc_name in ROOT_DOC_NAMES:
        rel = Path(doc_name)
        candidate = repo_dir / rel
        if candidate in tracked_files and candidate not in seen:
            chosen.append(candidate)
            seen.add(candidate)

    docs_dir_files = [
        repo_dir / rel
        for rel in repo_relative
        if len(rel.parts) >= 2 and rel.parts[0] == "docs" and rel.suffix.lower() in DOC_SUFFIXES
    ]
    docs_dir_files.sort(key=lambda path: (len(path.relative_to(repo_dir).parts), str(path.relative_to(repo_dir))))
    for candidate in docs_dir_files:
        if candidate not in seen:
            chosen.append(candidate)
            seen.add(candidate)
        if len(chosen) >= MAX_DOCS:
            break

    if len(chosen) < MAX_DOCS:
        root_doc_files = [
            repo_dir / rel
            for rel in repo_relative
            if len(rel.parts) == 1 and rel.suffix.lower() in DOC_SUFFIXES and rel.name not in ROOT_DOC_NAMES
        ]
        root_doc_files.sort(key=lambda path: str(path.relative_to(repo_dir)))
        for candidate in root_doc_files:
            if candidate not in seen:
                chosen.append(candidate)
                seen.add(candidate)
            if len(chosen) >= MAX_DOCS:
                break

    return chosen[:MAX_DOCS]


def detect_project_signals(tracked_files: list[Path], repo_dir: Path) -> dict[str, list[str] | int]:
    repo_relative = [path.relative_to(repo_dir) for path in tracked_files]

    manifests: list[str] = []
    for rel in repo_relative:
        if rel.name in MANIFEST_NAMES:
            manifests.append(f"{rel.as_posix()} ({MANIFEST_NAMES[rel.name]})")

    ext_counter: Counter[str] = Counter()
    for rel in repo_relative:
        suffix = rel.suffix.lower()
        if suffix in EXTENSION_LABELS:
            ext_counter[EXTENSION_LABELS[suffix]] += 1

    top_level_counter: Counter[str] = Counter()
    for rel in repo_relative:
        if len(rel.parts) >= 2:
            top_level_counter[rel.parts[0]] += 1

    top_dirs = [name for name, _ in top_level_counter.most_common(MAX_RELEVANT_DIRS)]
    languages = [name for name, _ in ext_counter.most_common(5)]

    return {
        "manifests": manifests,
        "languages": languages,
        "top_dirs": top_dirs,
        "file_count": len(repo_relative),
    }


def summarize_docs(owner: str, repo_name: str, branch: str, repo_dir: Path, docs: list[Path]) -> list[dict[str, str | list[str]]]:
    summaries: list[dict[str, str | list[str]]] = []
    for path in docs:
        rel = path.relative_to(repo_dir)
        text = read_text_file(path)
        title = first_heading(text) or rel.name
        paragraph = extract_first_paragraph(text) or "No concise prose summary was detected near the top of this document."
        headings = extract_headings(text)
        summaries.append(
            {
                "title": title,
                "path": rel.as_posix(),
                "url": github_blob_url(owner, repo_name, branch, rel),
                "paragraph": paragraph,
                "headings": headings,
            }
        )
    return summaries


def build_overview(owner: str, repo_name: str, signals: dict[str, list[str] | int], doc_summaries: list[dict[str, str | list[str]]]) -> str:
    file_count = signals["file_count"]
    manifests = signals["manifests"]
    languages = signals["languages"]
    top_dirs = signals["top_dirs"]
    readme_summary = doc_summaries[0]["paragraph"] if doc_summaries else None

    parts = [f"`{owner}/{repo_name}` is a GitHub repository snapshot with about `{file_count}` tracked files"]
    if languages:
        parts.append(f"and the visible code mix is led by {', '.join(f'`{language}`' for language in languages)}")
    if manifests:
        manifest_names = ", ".join(f"`{item.split(' ')[0]}`" for item in manifests[:4])
        parts.append(f"The repo includes manifest or build files such as {manifest_names}")
    if top_dirs:
        parts.append(f"High-signal top-level areas include {', '.join(f'`{name}`' for name in top_dirs[:5])}")
    overview = ". ".join(parts) + "."
    if readme_summary:
        overview += f" The leading project description says: {readme_summary}"
    return overview


def build_claims(signals: dict[str, list[str] | int], doc_summaries: list[dict[str, str | list[str]]]) -> list[str]:
    claims: list[str] = []
    if doc_summaries:
        claims.append(
            "The repository exposes enough local documentation to ground a repo-level summary directly from checked-in files rather than relying only on the landing page."
        )
    if signals["manifests"]:
        claims.append(
            "Build or package manifests are present, which makes the repo easier to classify by language or runtime from a shallow clone."
        )
    if signals["top_dirs"]:
        claims.append(
            "The top-level tree suggests distinct functional areas that can be used as navigation anchors during later vault compilation."
        )
    if any(summary["path"] != "README.md" for summary in doc_summaries):
        claims.append(
            "There are non-README documents worth linking directly from the vault so later agents can jump to architecture, setup, or contribution material without re-discovering paths."
        )
    claims.append(
        "This snapshot is derived from a shallow clone and document heuristics, so it is strongest as navigational and workflow evidence rather than as a full implementation audit."
    )
    return claims


def render_snapshot_markdown(
    repo_url: str,
    owner: str,
    repo_name: str,
    branch: str,
    commit: str,
    source_id: str,
    signals: dict[str, list[str] | int],
    doc_summaries: list[dict[str, str | list[str]]],
) -> str:
    repo_home = f"https://github.com/{owner}/{repo_name}"
    lines = [
        f"# GitHub Repository Snapshot: {owner}/{repo_name}",
        "",
        f"- Source ID: `{source_id}`",
        f"- Repository URL: {repo_url}",
        f"- GitHub Home: {repo_home}",
        f"- Branch: `{branch}`",
        f"- Commit: `{commit}`",
        f"- Analyzed At: `{now_stamp()}`",
        "",
        "## Summary",
        "",
        build_overview(owner, repo_name, signals, doc_summaries),
        "",
        "## Repository Signals",
        "",
        f"- Tracked file count: `{signals['file_count']}`",
    ]

    manifests = signals["manifests"]
    languages = signals["languages"]
    top_dirs = signals["top_dirs"]
    if manifests:
        lines.append(f"- Manifest or build files: {', '.join(f'`{item}`' for item in manifests)}")
    if languages:
        lines.append(f"- Dominant visible languages: {', '.join(f'`{item}`' for item in languages)}")
    if top_dirs:
        lines.append(f"- Top-level directories: {', '.join(f'`{item}`' for item in top_dirs)}")

    lines.extend(["", "## Key Documents", ""])
    if not doc_summaries:
        lines.append("- No high-signal README or docs files were detected from the shallow clone.")
    else:
        for summary in doc_summaries:
            lines.append(f"### {summary['title']}")
            lines.append("")
            lines.append(f"- Path: `{summary['path']}`")
            lines.append(f"- GitHub URL: {summary['url']}")
            lines.append(f"- Summary: {summary['paragraph']}")
            headings = summary["headings"]
            if headings:
                lines.append(f"- Visible headings: {', '.join(f'`{item}`' for item in headings)}")
            lines.append("")

    lines.extend(["## Candidate Claims", ""])
    for claim in build_claims(signals, doc_summaries):
        lines.append(f"- {claim}")

    lines.extend(
        [
            "",
            "## Evidence Notes",
            "",
            "- This snapshot was generated from a shallow clone in `/tmp`, not from a full repository history or issue tracker crawl.",
            "- GitHub links are included so later vault compilation can preserve provenance back to README and other high-signal docs.",
            "- Generated summaries are heuristic and document-led; they should be treated as a starting point for vault updates, not as a substitute for reading implementation-critical files.",
            "",
        ]
    )
    return "\n".join(lines)


def upsert_registry_entry(entry: dict) -> None:
    registry = load_json(REGISTRY_PATH, default=[])
    existing = {item["id"]: index for index, item in enumerate(registry)}
    index = existing.get(entry["id"])
    if index is None:
        registry.append(entry)
    else:
        registry[index] = entry
    save_json(REGISTRY_PATH, registry)


def ingest_repo_snapshot(repo_url: str, note_text: str, owner: str, repo_name: str) -> dict:
    canonical_repo_url = github_home_url(repo_url)
    source_id = f"src-{short_hash(canonical_repo_url)}"
    source_dir = RAW_DIR / source_id
    ensure_dir(source_dir)

    original_path = source_dir / "original.md"
    normalized_path = source_dir / "normalized.md"
    metadata_path = source_dir / "metadata.json"

    original_path.write_text(note_text, encoding="utf-8")
    normalized_path.write_text(note_text, encoding="utf-8")

    metadata = {
        "id": source_id,
        "source": canonical_repo_url,
        "ingested_at": now_stamp(),
        "kind": "github_repo_snapshot",
        "content_type": "text/markdown",
        "original_path": str(original_path.relative_to(ROOT)),
        "normalized_path": str(normalized_path.relative_to(ROOT)),
        "title_guess": f"GitHub Repo {owner} {repo_name}",
        "content_hash": content_hash(note_text),
        "last_checked_at": now_stamp(),
    }
    save_json(metadata_path, metadata)
    return metadata


def ingest_repo(repo_url: str, branch: str | None = None) -> dict:
    owner, repo_name = parse_github_repo(repo_url)
    clone_dir = clone_repo(repo_url, branch)
    clone_root = clone_dir.parent

    try:
        detected_branch = detect_branch(clone_dir)
        commit = detect_commit(clone_dir)
        tracked_files = list_tracked_files(clone_dir)
        doc_paths = collect_candidate_docs(clone_dir, tracked_files)
        signals = detect_project_signals(tracked_files, clone_dir)
        source_id = f"src-{short_hash(github_home_url(repo_url))}"
        doc_summaries = summarize_docs(owner, repo_name, detected_branch, clone_dir, doc_paths)
        note_text = render_snapshot_markdown(
            repo_url=repo_url,
            owner=owner,
            repo_name=repo_name,
            branch=detected_branch,
            commit=commit,
            source_id=source_id,
            signals=signals,
            doc_summaries=doc_summaries,
        )
        metadata = ingest_repo_snapshot(repo_url, note_text, owner, repo_name)
    finally:
        shutil.rmtree(clone_root, ignore_errors=True)

    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Clone a GitHub repository, synthesize a markdown snapshot, and ingest it.")
    parser.add_argument("--repo", required=True, help="GitHub repository URL")
    parser.add_argument("--branch", help="Branch to clone. Defaults to the repository default branch.")
    parser.add_argument("--keep-clone", action="store_true", help="Keep the temporary clone under /tmp for inspection.")
    args = parser.parse_args()

    if args.keep_clone:
        owner, repo_name = parse_github_repo(args.repo)
        clone_dir = clone_repo(args.repo, args.branch)
        clone_root = clone_dir.parent
        try:
            branch = detect_branch(clone_dir)
            commit = detect_commit(clone_dir)
            tracked_files = list_tracked_files(clone_dir)
            doc_paths = collect_candidate_docs(clone_dir, tracked_files)
            signals = detect_project_signals(tracked_files, clone_dir)
            source_id = f"src-{short_hash(github_home_url(args.repo))}"
            doc_summaries = summarize_docs(owner, repo_name, branch, clone_dir, doc_paths)
            note_text = render_snapshot_markdown(
                repo_url=args.repo,
                owner=owner,
                repo_name=repo_name,
                branch=branch,
                commit=commit,
                source_id=source_id,
                signals=signals,
                doc_summaries=doc_summaries,
            )
            metadata = ingest_repo_snapshot(args.repo, note_text, owner, repo_name)
        finally:
            print(f"Kept clone at {clone_root}")
    else:
        metadata = ingest_repo(args.repo, args.branch)

    upsert_registry_entry(metadata)

    print(f"Ingested {args.repo} -> {metadata['id']}")
    print(metadata["normalized_path"])


if __name__ == "__main__":
    main()
