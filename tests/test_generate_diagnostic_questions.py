import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "scripts"))
from utils import ROOT, parse_frontmatter

VALID_TYPES = {"factual", "comparison", "contradiction", "edge-case", "temporal"}
REQUIRED_FIELDS = {"concept", "source_id", "type", "question", "expected_answer", "id"}
REVIEW_FIELDS = {"review_status", "reviewer", "reject_reason"}
VALID_REVIEW_STATUSES = {"unreviewed", "approved", "rejected"}


def _concept_quality_map() -> dict[str, str]:
    result: dict[str, str] = {}
    for path in (ROOT / "notes" / "Concepts").glob("*.md"):
        fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        q = fm.get("claim_quality")
        if q:
            result[path.stem] = q
    return result


def test_knowledge_probes_validity():
    # T6 renamed knowledge-probes.jsonl → dev-probes.jsonl
    probes_file = ROOT / "research" / "evals" / "dev-probes.jsonl"
    assert probes_file.exists(), (
        "dev-probes.jsonl does not exist (was knowledge-probes.jsonl renamed by T6?)"
    )

    quality_map = _concept_quality_map()
    all_concepts = set(quality_map)
    supported_concepts = {c for c, q in quality_map.items() if q == "supported"}

    assert len(supported_concepts) >= 1, "Expected at least 1 supported concept"

    probe_counts: dict[str, int] = {}
    with open(probes_file, encoding="utf-8") as f:
        for idx, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue

            try:
                probe = json.loads(raw)
            except Exception as e:
                assert False, f"Line {idx} in dev-probes.jsonl is not valid JSON: {e}"

            # Required structural fields
            missing = REQUIRED_FIELDS - probe.keys()
            assert not missing, f"Probe at line {idx} missing fields: {missing}"

            # Review workflow fields (added by T7)
            missing_review = REVIEW_FIELDS - probe.keys()
            assert not missing_review, (
                f"Probe at line {idx} missing T7 review fields: {missing_review}"
            )

            assert probe["review_status"] in VALID_REVIEW_STATUSES, (
                f"Probe at line {idx} has invalid review_status '{probe['review_status']}'"
            )

            # Concept must exist in the vault
            concept = probe["concept"]
            assert concept in all_concepts, (
                f"Probe at line {idx} targets concept '{concept}' which does not exist in the vault"
            )

            # expected_answer must be a non-empty list of non-empty strings
            ans = probe["expected_answer"]
            assert isinstance(ans, list) and ans, (
                f"expected_answer at line {idx} must be a non-empty list"
            )
            for fact in ans:
                assert isinstance(fact, str) and fact, (
                    f"expected_answer facts must be non-empty strings (line {idx})"
                )

            # Type must be valid
            assert probe["type"] in VALID_TYPES, (
                f"Invalid probe type '{probe['type']}' at line {idx}"
            )

            # Stable ID check
            q_text = probe["question"]
            norm = re.sub(r"[^a-z0-9]", "", q_text.lower())
            expected_id = f"probe-{hashlib.sha256(norm.encode()).hexdigest()[:12]}"
            assert probe["id"] == expected_id, (
                f"ID mismatch at line {idx}: expected '{expected_id}', got '{probe['id']}'"
            )

            probe_counts[concept] = probe_counts.get(concept, 0) + 1

    # Every supported concept must have at least 1 probe (approved probes
    # are a subset; the ≥3 gate is enforced by the scorecard once approved)
    for concept in supported_concepts:
        count = probe_counts.get(concept, 0)
        assert count >= 1, f"Supported concept '{concept}' has no probes in dev-probes.jsonl"
