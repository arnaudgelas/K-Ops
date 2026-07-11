"""Vault-root resolution — side-effect free.

Decouples *code root* (where the tooling lives) from *vault root* (where a
project's ``data/``, ``notes/`` and ``research/`` live). This lets one shared
copy of the tooling operate on any vault, which is the prerequisite for keeping
the tooling in one repository while a separate, private repository holds only a
vault.

``kb_home()`` resolves the vault root in priority order:

1. ``KB_HOME`` environment variable (explicit override).
2. The parent of ``config/`` implied by ``KB_CONFIG_PATH`` (if set).
3. The nearest ancestor of the current working directory that contains
   ``config/kb_config.yaml`` (lets you run from inside a vault).
4. Back-compat fallback: the code repository root (colocated code + vault).

This module deliberately imports nothing from the rest of the toolkit and has
no import-time side effects, so any script can depend on it cheaply.
"""

from __future__ import annotations

import os
from pathlib import Path

# Where the tooling itself lives (the code repo root). Use this for *code*
# assets that ship with the tooling: templates/, skills/, config/schema.yaml.
CODE_ROOT = Path(__file__).resolve().parents[1]

_CONFIG_MARKER = Path("config") / "kb_config.yaml"


def kb_home() -> Path:
    """Resolve the vault root. See module docstring for precedence."""
    env = os.environ.get("KB_HOME")
    if env:
        return Path(env).expanduser().resolve()

    cfg = os.environ.get("KB_CONFIG_PATH")
    if cfg:
        # KB_CONFIG_PATH points at <home>/config/kb_config.yaml
        return Path(cfg).expanduser().resolve().parent.parent

    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / _CONFIG_MARKER).exists():
            return candidate

    return CODE_ROOT


# Resolved once at import. Entry points that accept a --vault flag must set
# os.environ["KB_HOME"] *before* importing modules that read ROOT.
ROOT = kb_home()
