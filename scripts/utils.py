from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "kb_config.yaml"


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


def load_config() -> KBPaths:
    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
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
    )


CONFIG = load_config()


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
