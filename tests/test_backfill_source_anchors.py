import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kops.backfill_source_anchors import _find_verbatim_span, _serialize_anchor_fields  # noqa: E402


def test_find_verbatim_span_round_trips_exact_claim_text():
    source = "Intro.\n\nThe harness stores execution traces in files for later review.\n"
    claim = "The harness stores execution traces in files for later review."

    span = _find_verbatim_span(claim, source)

    assert span is not None
    assert span["quote"] == claim
    assert source[span["char_start"] : span["char_end"]] == span["quote"]
    assert span["extraction_confidence"] == "exact-claim"


def test_find_verbatim_span_selects_source_quote_for_paraphrase():
    source = (
        "Harnesses should keep durable state in files. "
        "Logs and rollout trajectories can outgrow the model context window.\n\n"
        "Unrelated paragraph about model pricing."
    )
    claim = "Harnesses preserve durable state in files, logs, and rollout trajectories."

    span = _find_verbatim_span(claim, source)

    assert span is not None
    assert "durable state in files" in span["quote"]
    assert "rollout trajectories" in span["quote"]
    assert source[span["char_start"] : span["char_end"]] == span["quote"]


def test_serialize_anchor_includes_character_offsets():
    anchor = {
        "char_start": 12,
        "char_end": 34,
        "source_text_path": "data/raw/src-abc/normalized.md",
    }

    assert (
        _serialize_anchor_fields(anchor)
        == "char_start=12&char_end=34&source_text_path=data/raw/src-abc/normalized.md"
    )
