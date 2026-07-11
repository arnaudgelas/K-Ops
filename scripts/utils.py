from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shlex
import shutil
import tempfile
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from kb_paths import CODE_ROOT, ROOT, kb_home  # noqa: F401  (re-exported for callers)

# Monkey-patch Path.glob and Path.rglob to ignore OKF reserved index.md and log.md files
_original_glob = Path.glob
_original_rglob = Path.rglob


def _filtered_glob(self, pattern, *args, **kwargs):
    gen = _original_glob(self, pattern, *args, **kwargs)
    if isinstance(pattern, str) and pattern.endswith("*.md"):
        for p in gen:
            if p.name not in ("index.md", "log.md"):
                yield p
    else:
        yield from gen


def _filtered_rglob(self, pattern, *args, **kwargs):
    gen = _original_rglob(self, pattern, *args, **kwargs)
    if isinstance(pattern, str) and pattern.endswith("*.md"):
        for p in gen:
            if p.name not in ("index.md", "log.md"):
                yield p
    else:
        yield from gen


Path.glob = _filtered_glob
Path.rglob = _filtered_rglob

CONFIG_PATH = Path(os.environ.get("KB_CONFIG_PATH", str(ROOT / "config" / "kb_config.yaml")))


@dataclass(frozen=True)
class KBPaths:
    project_name: str
    raw_dir: Path
    registry_path: Path
    vault_dir: Path
    research_dir: Path
    home_note: Path
    todo_note: Path
    concepts_dir: Path
    indexes_dir: Path
    summaries_dir: Path
    answers_dir: Path
    attachments_dir: Path
    outputs_dir: Path
    allow_web_fetch_during_qa: bool
    file_answer_back_into_vault: bool
    use_obsidian_wikilinks: bool


_REQUIRED_CONFIG_KEYS = (
    "project_name",
    "raw_dir",
    "registry_path",
    "vault_dir",
    "research_dir",
    "home_note",
    "todo_note",
    "concepts_dir",
    "summaries_dir",
    "answers_dir",
    "attachments_dir",
    "outputs_dir",
)


@lru_cache(maxsize=1)
def load_config() -> KBPaths:
    import sys as _sys

    env_path = os.environ.get("KB_CONFIG_PATH")
    config_path = Path(env_path) if env_path else CONFIG_PATH
    if not config_path.exists():
        _sys.exit(f"KB config not found: {config_path}")
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        _sys.exit(f"KB config YAML parse error: {exc}")
    if not isinstance(data, dict):
        _sys.exit(f"KB config is not a YAML mapping: {config_path}")
    for key in _REQUIRED_CONFIG_KEYS:
        if key not in data:
            _sys.exit(f"KB config missing required key: {key}")
    return KBPaths(
        project_name=data["project_name"],
        raw_dir=ROOT / data["raw_dir"],
        registry_path=ROOT / data["registry_path"],
        vault_dir=ROOT / data["vault_dir"],
        research_dir=ROOT / data["research_dir"],
        home_note=ROOT / data["home_note"],
        todo_note=ROOT / data["todo_note"],
        concepts_dir=ROOT / data["concepts_dir"],
        indexes_dir=ROOT / data.get("indexes_dir", "notes/Indexes"),
        summaries_dir=ROOT / data["summaries_dir"],
        answers_dir=ROOT / data["answers_dir"],
        attachments_dir=ROOT / data["attachments_dir"],
        outputs_dir=ROOT / data["outputs_dir"],
        allow_web_fetch_during_qa=bool(data.get("allow_web_fetch_during_qa", False)),
        file_answer_back_into_vault=bool(data.get("file_answer_back_into_vault", True)),
        use_obsidian_wikilinks=bool(data.get("use_obsidian_wikilinks", True)),
    )


get_config = load_config  # backward-compatible alias; both are LRU-cached


class _ConfigProxy:
    def __getattr__(self, name: str) -> Any:
        return getattr(get_config(), name)

    def __dir__(self) -> list[str]:
        return sorted(set(dir(type(self)) + list(get_config().__dict__.keys())))


CONFIG = _ConfigProxy()


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        return {}, text
    data = yaml.safe_load(parts[0][4:]) or {}
    if not isinstance(data, dict):
        data = {}
    return data, parts[1]


def dump_frontmatter(data: dict) -> str:
    return "---\n" + yaml.safe_dump(data, sort_keys=False, allow_unicode=True).rstrip() + "\n---\n"


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def slugify(text: str, max_len: int = 80) -> str:
    text = text.strip().lower()
    text = re.sub(r"https?://", "", text)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:max_len] or "item"


def short_hash(text: str, length: int = 10) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)


def shell_join(cmd: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)


def detect_first_available_command(candidates: list[str]) -> list[str]:
    for candidate in candidates:
        parts = shlex.split(candidate)
        if not parts:
            continue
        if shutil.which(parts[0]):
            return parts
    raise ValueError(f"No supported command found among: {', '.join(candidates)}")


def detect_agent_command(agent: str) -> list[str]:
    if agent == "codex":
        raw = os.environ.get("KB_CODEX_CMD")
        if raw:
            return shlex.split(raw)
        return detect_first_available_command(["codex", "codex-cli"])
    elif agent == "claude":
        raw = os.environ.get("KB_CLAUDE_CMD")
        if raw:
            return shlex.split(raw)
        return detect_first_available_command(["claude", "claude-code"])
    elif agent == "gemini":
        raw = os.environ.get("KB_GEMINI_CMD")
        if raw:
            return shlex.split(raw)
        return detect_first_available_command(["gemini", "gemini-cli"])
    else:
        raise ValueError(f"Unsupported agent: {agent}")


def write_text(path: Path, content: str) -> None:
    ensure_dir(path.parent)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)


def find_source_note(source_id: str) -> Path | None:
    """Locate an existing source note under summaries_dir (any subfolder).

    Returns the first matching path, or None if not found.
    """
    for candidate in get_config().summaries_dir.rglob(f"{source_id}.md"):
        return candidate
    return None


def resolve_content_path(metadata: dict) -> str:
    """Return the best available content path for a source.

    Prefers ``normalized_path`` when present (web/PDF sources where
    normalization actually transformed the content).  Falls back to
    ``original_path`` for sources where no separate normalized file exists
    (GitHub repo snapshots, local files whose normalized copy was identical).
    """
    norm = metadata.get("normalized_path")
    if norm:
        candidate = ROOT / norm
        if candidate.exists():
            return str(candidate)
    orig = metadata.get("original_path")
    if orig:
        return str(ROOT / orig)
    raise FileNotFoundError(f"No content file found for source {metadata.get('id')}")
