"""Research quality tiers — a config-free constant.

Kept in its own tiny module (no CONFIG access, no heavy imports) so the CLI
argument parser can reference it without importing the command layer, which
would eagerly load the vault config. This is what lets ``kops --help`` work
outside a vault.
"""

from __future__ import annotations

RESEARCH_TIERS = {"fast", "standard", "deep"}
