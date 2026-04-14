from __future__ import annotations

import datetime as dt
import functools
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "kb_config.yaml"

_REQUIRED_KEYS = (
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

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n?---\n(.*)$", re.DOTALL)


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
    summaries_dir: Path
    answers_dir: Path
    attachments_dir: Path
    outputs_dir: Path
    # Behavioral flags (exposed so scripts can read them without re-parsing YAML)
    allow_web_fetch_during_qa: bool
    file_answer_back_into_vault: bool
    use_obsidian_wikilinks: bool


@functools.lru_cache(maxsize=1)
def load_config() -> KBPaths:
    """Load and validate config/kb_config.yaml.

    Override the config path by setting the KB_CONFIG_PATH environment variable.
    The result is cached; call ``load_config.cache_clear()`` in tests to reload.
    """
    config_path = Path(os.environ.get("KB_CONFIG_PATH", str(CONFIG_PATH)))
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(
            f"[kb] Config file not found: {config_path}\n"
            f"  Set KB_CONFIG_PATH to override the config location."
        )
    if not isinstance(data, dict):
        raise SystemExit(f"[kb] Config file is not a YAML mapping: {config_path}")
    missing = [k for k in _REQUIRED_KEYS if k not in data]
    if missing:
        raise SystemExit(
            f"[kb] Missing required config key(s): {', '.join(missing)}\n"
            f"  Fix: add them to {config_path}"
        )
    return KBPaths(
        project_name=data["project_name"],
        raw_dir=ROOT / data["raw_dir"],
        registry_path=ROOT / data["registry_path"],
        vault_dir=ROOT / data["vault_dir"],
        research_dir=ROOT / data["research_dir"],
        home_note=ROOT / data["home_note"],
        todo_note=ROOT / data["todo_note"],
        concepts_dir=ROOT / data["concepts_dir"],
        summaries_dir=ROOT / data["summaries_dir"],
        answers_dir=ROOT / data["answers_dir"],
        attachments_dir=ROOT / data["attachments_dir"],
        outputs_dir=ROOT / data["outputs_dir"],
        allow_web_fetch_during_qa=bool(data.get("allow_web_fetch_during_qa", False)),
        file_answer_back_into_vault=bool(data.get("file_answer_back_into_vault", True)),
        use_obsidian_wikilinks=bool(data.get("use_obsidian_wikilinks", True)),
    )


CONFIG = load_config()


# ---------------------------------------------------------------------------
# Frontmatter helpers (canonical implementations — import these, don't
# re-implement parse_frontmatter or dump_frontmatter in other scripts)
# ---------------------------------------------------------------------------

def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from a Markdown string.

    Returns ``(data_dict, body)`` where *body* is the text after the closing
    ``---`` delimiter.  Returns ``({}, text)`` when no valid frontmatter is
    found.
    """
    if not text.startswith("---\n"):
        return {}, text
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    data = yaml.safe_load(match.group(1)) or {}
    if not isinstance(data, dict):
        data = {}
    return data, match.group(2)


def dump_frontmatter(data: dict) -> str:
    """Serialize *data* as a YAML frontmatter block (``---\\n...\\n---\\n``)."""
    return "---\n" + yaml.safe_dump(data, sort_keys=False, allow_unicode=True).rstrip() + "\n---\n"


# ---------------------------------------------------------------------------
# General utilities
# ---------------------------------------------------------------------------

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
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Agent runner helpers (shared by kb.py and research_workflow.py)
# ---------------------------------------------------------------------------

TEMPLATES = ROOT / "templates"


def build_prompt(template_name: str, **kwargs: str) -> Path:
    template = (TEMPLATES / template_name).read_text(encoding="utf-8")
    rendered = template.format(**kwargs)
    prompt_path = ROOT / ".tmp" / f"{template_name}.{now_stamp()}.md"
    ensure_dir(prompt_path.parent)
    write_text(prompt_path, rendered)
    return prompt_path


def build_runtime_prompt(name: str, text: str) -> Path:
    prompt_path = ROOT / ".tmp" / f"{name}.{now_stamp()}.md"
    ensure_dir(prompt_path.parent)
    write_text(prompt_path, text)
    return prompt_path


def agent_run(agent: str, prompt_path: Path) -> None:
    base_cmd = detect_agent_command(agent)
    prompt_text = prompt_path.read_text(encoding="utf-8")
    if agent == "codex":
        cmd = base_cmd + ["exec", "--skip-git-repo-check", "--full-auto", prompt_text]
    elif agent == "claude":
        cmd = base_cmd + ["-p", str(prompt_path)]
    elif agent == "gemini":
        cmd = base_cmd + ["-p", prompt_text]
    else:
        raise ValueError(agent)
    print(f"\nRunning: {shell_join(cmd)}\n")
    subprocess.run(cmd, check=True, cwd=ROOT)
