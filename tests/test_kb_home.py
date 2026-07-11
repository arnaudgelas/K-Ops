"""Tests for vault-root resolution (kb_paths) and the public-safety tripwire."""

import json

import check_public_safe
import kb_paths


# --- kb_home() precedence ---------------------------------------------------


def test_kb_home_env_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("KB_HOME", str(tmp_path))
    assert kb_paths.kb_home() == tmp_path.resolve()


def test_kb_home_from_config_path(monkeypatch, tmp_path):
    monkeypatch.delenv("KB_HOME", raising=False)
    cfg = tmp_path / "config" / "kb_config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("project_name: demo\n")
    monkeypatch.setenv("KB_CONFIG_PATH", str(cfg))
    assert kb_paths.kb_home() == tmp_path.resolve()


def test_kb_home_walks_up_from_cwd(monkeypatch, tmp_path):
    monkeypatch.delenv("KB_HOME", raising=False)
    monkeypatch.delenv("KB_CONFIG_PATH", raising=False)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "kb_config.yaml").write_text("project_name: demo\n")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    assert kb_paths.kb_home() == tmp_path.resolve()


def test_kb_home_falls_back_to_code_root(monkeypatch, tmp_path):
    monkeypatch.delenv("KB_HOME", raising=False)
    monkeypatch.delenv("KB_CONFIG_PATH", raising=False)
    isolated = tmp_path / "no-vault-here"
    isolated.mkdir()
    monkeypatch.chdir(isolated)
    assert kb_paths.kb_home() == kb_paths.CODE_ROOT


# --- public-safety tripwire -------------------------------------------------


def test_public_safe_passes_when_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(check_public_safe, "ROOT", tmp_path)
    assert check_public_safe.main() == 0


def test_public_safe_fails_on_large_registry(monkeypatch, tmp_path):
    monkeypatch.setattr(check_public_safe, "ROOT", tmp_path)
    monkeypatch.setattr(check_public_safe, "MAX_SOURCES", 2)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "registry.json").write_text(
        json.dumps([{"id": i} for i in range(5)]), encoding="utf-8"
    )
    assert check_public_safe.main() == 1


def test_public_safe_counts_id_keyed_registry(monkeypatch, tmp_path):
    monkeypatch.setattr(check_public_safe, "ROOT", tmp_path)
    monkeypatch.setattr(check_public_safe, "MAX_SOURCES", 2)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "registry.json").write_text(
        json.dumps({f"src-{i}": {"id": i} for i in range(5)}), encoding="utf-8"
    )
    assert check_public_safe.main() == 1
