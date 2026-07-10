import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_source_drift  # noqa: E402,F401
from check_source_drift import _upstream_head  # noqa: E402


class _FakeCompleted:
    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def _fake_ls_remote(output_by_ref):
    """Return a subprocess.run stub keyed on the ref argument (argv[-1])."""

    def _run(cmd, *args, **kwargs):
        ref = cmd[-1]
        return _FakeCompleted(output_by_ref.get(ref, ""))

    return _run


def test_upstream_head_ignores_fork_branches_ending_in_main(monkeypatch):
    # `git ls-remote url refs/heads/main` on a repo with fork branches returns
    # every ref ending in `/main`; only the exact refs/heads/main must win.
    ls_remote_out = (
        "ed3a6bd26f38eaf271a71019cc2da9bd02807b05\trefs/heads/Dawn-Of-Justice/main\n"
        "3e2481dc24fc5d8123d99c874708fb50fff63b09\trefs/heads/YeonwooSung/main\n"
        "0dff5479aa51934c7d5833a7c38e2a5abba4e0c2\trefs/heads/main\n"
        "bee3ba36e60e6768581ab4a203dd3daac6282943\trefs/heads/praneeth999/main\n"
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_ls_remote({"refs/heads/main": ls_remote_out}),
    )
    head = _upstream_head("https://example.com/x/y", "main")
    assert head == "0dff5479aa51934c7d5833a7c38e2a5abba4e0c2"


def test_upstream_head_falls_back_to_head_when_branch_absent(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_ls_remote({"HEAD": "abc1230000000000000000000000000000000000\tHEAD\n"}),
    )
    head = _upstream_head("https://example.com/x/y", "main")
    assert head == "abc1230000000000000000000000000000000000"


def test_upstream_head_none_when_unreachable(monkeypatch):
    def _boom(cmd, *args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert _upstream_head("https://example.com/x/y", "main") is None
