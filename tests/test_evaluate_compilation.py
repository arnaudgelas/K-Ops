from pathlib import Path
import sys

# Add scripts directory to path to allow importing utils
sys.path.append(str(Path(__file__).resolve().parent.parent / "scripts"))
from kops.utils import parse_frontmatter
from kops.feedback_loop import update_concept_file, parse_sections, parse_gaps_section


def test_parse_sections():
    content = """# Title
## What It Is
Intro content.

## Related Concepts
- Concept A
"""
    sections = parse_sections(content)
    assert len(sections) == 3
    assert sections[0][0] == ""
    assert sections[1][0] == "## What It Is"
    assert sections[2][0] == "## Related Concepts"


def test_parse_gaps_section():
    lines = [
        "- **[Unresolved]** [probe-1] Question: Test?",
        "  - Expected facts:",
        "    - Fact A",
        "- **[Unresolved]** [probe-2] Question: Test 2?",
        "  - Expected facts:",
        "    - Fact B",
    ]
    gaps = parse_gaps_section(lines)
    assert len(gaps) == 2
    assert "probe-1" in gaps
    assert "probe-2" in gaps
    assert "Fact A" in "".join(gaps["probe-1"])


def test_update_concept_file_with_gaps(tmp_path, monkeypatch):
    # Setup temporary concept page
    concept_dir = tmp_path / "notes" / "Concepts"
    concept_dir.mkdir(parents=True)
    concept_file = concept_dir / "TestConcept.md"

    initial_content = """---
title: TestConcept
claim_quality: supported
---
# TestConcept

## What It Is
Definition here.

## Related Concepts
- Related A
"""
    concept_file.write_text(initial_content, encoding="utf-8")

    # Mock ROOT in feedback_loop
    monkeypatch.setattr("kops.feedback_loop.ROOT", tmp_path)

    failed_probes = [
        {
            "id": "probe-fail1",
            "concept": "TestConcept",
            "question": "What is the overhead?",
            "expected_answer": ["7-9% overhead"],
        }
    ]
    passed_ids = {"probe-pass1"}

    # Run feedback loop update
    update_concept_file("TestConcept", failed_probes, passed_ids)

    # Verify file content
    updated_text = concept_file.read_text(encoding="utf-8")
    frontmatter, content = parse_frontmatter(updated_text)

    assert frontmatter.get("revalidation_required") is True
    assert "## Coverage Gaps" in content
    assert "probe-fail1" in content
    assert "7-9% overhead" in content


def test_update_concept_file_cleared(tmp_path, monkeypatch):
    concept_dir = tmp_path / "notes" / "Concepts"
    concept_dir.mkdir(parents=True)
    concept_file = concept_dir / "TestConcept.md"

    initial_content = """---
title: TestConcept
claim_quality: supported
revalidation_required: true
---
# TestConcept

## What It Is
Definition here.

## Coverage Gaps

- **[Unresolved]** [probe-fail1] Question: What is the overhead?
  - Expected facts:
    - 7-9% overhead

## Related Concepts
- Related A
"""
    concept_file.write_text(initial_content, encoding="utf-8")

    monkeypatch.setattr("kops.feedback_loop.ROOT", tmp_path)

    # Send no failed probes, and failed probe ID in passed list to clear it
    failed_probes = []
    passed_ids = {"probe-fail1"}

    update_concept_file("TestConcept", failed_probes, passed_ids)

    updated_text = concept_file.read_text(encoding="utf-8")
    frontmatter, content = parse_frontmatter(updated_text)

    assert "revalidation_required" not in frontmatter
    assert "## Coverage Gaps" not in content
    assert "probe-fail1" not in content
