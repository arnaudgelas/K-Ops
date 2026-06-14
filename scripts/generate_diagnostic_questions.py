#!/usr/bin/env python3
"""
Generate diagnostic questions (probes) from source summaries for supported concepts.
Implements P2.1 of the evaluation plan.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

# Add scripts directory to path to allow importing utils
sys.path.append(str(Path(__file__).resolve().parent))
from utils import ROOT, load_config, parse_frontmatter, detect_agent_command

PROBES_FILE = ROOT / "research" / "evals" / "knowledge-probes.jsonl"


def generate_stable_id(question: str) -> str:
    # Normalize question: lowercase, keep only alphanumeric characters
    norm = re.sub(r"[^a-z0-9]", "", question.lower())
    h = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:12]
    return f"probe-{h}"


def load_existing_probes() -> list[dict]:
    probes = []
    if PROBES_FILE.exists():
        with open(PROBES_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        probes.append(json.loads(line))
                    except Exception as e:
                        print(f"Warning: failed to parse existing probe: {e}")
    return probes


def save_probes(probes: list[dict]) -> None:
    PROBES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROBES_FILE, "w", encoding="utf-8") as f:
        for probe in probes:
            f.write(json.dumps(probe, ensure_ascii=False) + "\n")


def load_sources(sources_dir: Path) -> dict[str, dict]:
    sources = {}
    for path in sources_dir.rglob("*.md"):
        if not path.name.startswith("src-"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
            frontmatter, content = parse_frontmatter(text)
            source_id = frontmatter.get("source_id") or path.stem
            sources[source_id] = {
                "path": path,
                "frontmatter": frontmatter,
                "content": content,
                "text": text,
                "evidence_strength": frontmatter.get("evidence_strength", ""),
            }
        except Exception as e:
            print(f"Warning: failed to load source {path}: {e}")
    return sources


def load_supported_concepts(concepts_dir: Path) -> list[dict]:
    concepts = []
    for path in concepts_dir.glob("*.md"):
        try:
            text = path.read_text(encoding="utf-8")
            frontmatter, content = parse_frontmatter(text)
            if frontmatter.get("claim_quality") == "supported":
                concepts.append(
                    {
                        "path": path,
                        "name": path.stem,
                        "frontmatter": frontmatter,
                        "content": content,
                        "text": text,
                    }
                )
        except Exception as e:
            print(f"Warning: failed to load concept {path}: {e}")
    return concepts


def extract_json(text: str) -> list[dict]:
    text_stripped = text.strip()
    # Remove markdown code blocks if any
    if text_stripped.startswith("```"):
        lines = text_stripped.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text_stripped = "\n".join(lines).strip()

    # Try finding first '[' and last ']'
    start = text_stripped.find("[")
    end = text_stripped.rfind("]")
    if start != -1 and end != -1:
        json_str = text_stripped[start : end + 1]
        try:
            val = json.loads(json_str)
            if isinstance(val, list):
                return val
        except Exception:
            pass

    # Try finding first '{' and last '}'
    start_obj = text_stripped.find("{")
    end_obj = text_stripped.rfind("}")
    if start_obj != -1 and end_obj != -1:
        json_str = text_stripped[start_obj : end_obj + 1]
        try:
            val = json.loads(json_str)
            if isinstance(val, dict):
                return [val]
        except Exception:
            pass

    # Fallback to direct parse
    try:
        val = json.loads(text_stripped)
        if isinstance(val, list):
            return val
        elif isinstance(val, dict):
            return [val]
    except Exception:
        pass

    raise ValueError(f"Failed to parse JSON from output: {text}")


def generate_probes_for_concept(
    concept_name: str, source_id: str, source_content: str, num_needed: int, has_temporal: bool
) -> list[dict]:
    # Construct the prompt
    type_instruction = (
        "- 'factual': factual recall questions testing critical details or claims.\n"
        "- 'comparison': questions that compare different aspects, tools, or ideas.\n"
        "- 'contradiction': questions targeting potential contradictions, conflicts, or trade-offs.\n"
        "- 'edge-case': questions testing edge cases, limitations, or failure modes."
    )
    if has_temporal:
        type_instruction += "\n- 'temporal': 'what changed?' questions based on updated or refreshed source metadata."
        types_pool = "factual, comparison, contradiction, edge-case, temporal"
    else:
        types_pool = "factual, comparison, contradiction, edge-case"

    prompt = f"""You are a precise evaluation helper. Your task is to generate {num_needed} diagnostic questions (probes) for the concept "{concept_name}" derived from the provided source note.

Concept Name: {concept_name}
Source ID: {source_id}

Source Note Content:
{source_content}

Generate {num_needed} diagnostic probe(s). Each probe must be a JSON object with:
- "concept": "{concept_name}" (must match exactly)
- "source_id": "{source_id}" (must match exactly)
- "type": one of the probe types (chosen from: {types_pool})
- "question": a diagnostic question text targeting this concept and source
- "expected_answer": list of required facts/ground truth citations that must be mentioned to answer this question.

Probe Type definitions:
{type_instruction}

Output ONLY a JSON list of objects (enclosed in []). Do not output markdown code blocks (like ```json), do not output explanations or conversational text.
"""
    base_cmd = detect_agent_command("gemini")
    cmd = base_cmd + ["-p", prompt]

    # Run the subprocess
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), check=True)

    stdout = result.stdout
    probes = extract_json(stdout)

    # Validate and clean up fields
    validated_probes = []
    for p in probes:
        if not isinstance(p, dict):
            continue
        q = p.get("question")
        if not q:
            continue

        # Ensure concept and source_id are correct
        p["concept"] = concept_name
        p["source_id"] = source_id

        # Generate stable ID
        p["id"] = generate_stable_id(q)

        # Set default review fields
        p["review_status"] = "unreviewed"
        p["reviewer"] = None
        p["reject_reason"] = None

        # Ensure type is valid
        ptype = p.get("type", "factual")
        if ptype not in ["factual", "comparison", "contradiction", "edge-case", "temporal"]:
            ptype = "factual"
        p["type"] = ptype

        # Ensure expected_answer is a list of strings
        ans = p.get("expected_answer")
        if isinstance(ans, str):
            p["expected_answer"] = [ans]
        elif isinstance(ans, list):
            p["expected_answer"] = [str(x) for x in ans if x]
        else:
            p["expected_answer"] = []

        validated_probes.append(p)

    return validated_probes


def main():
    parser = argparse.ArgumentParser(
        description="Generate diagnostic questions from sources for supported concepts."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force regeneration of probes even if they already exist.",
    )
    args = parser.parse_args()

    config = load_config()
    print(f"Project: {config.project_name}")

    # 1. Load existing probes
    existing_probes = [] if args.force else load_existing_probes()
    print(f"Loaded {len(existing_probes)} existing probe(s) from {PROBES_FILE}")

    # Group by concept
    probes_by_concept = {}
    for p in existing_probes:
        concept = p.get("concept")
        if concept:
            probes_by_concept.setdefault(concept, []).append(p)

    # 2. Load all sources
    print("Loading source summaries...")
    sources = load_sources(config.summaries_dir)
    print(f"Loaded {len(sources)} source summary/summaries.")

    # 3. Load supported concepts
    print("Loading supported concepts...")
    concepts = load_supported_concepts(config.concepts_dir)
    print(f"Loaded {len(concepts)} supported concept(s).")

    # 4. Generate probes
    all_probes = list(existing_probes)
    new_probes_generated = 0

    for concept in concepts:
        concept_name = concept["name"]
        existing = probes_by_concept.get(concept_name, [])
        num_existing = len(existing)

        if num_existing >= 3:
            print(f"Concept '{concept_name}' already has {num_existing} probe(s). Skipping.")
            continue

        num_needed = 3 - num_existing
        print(
            f"Concept '{concept_name}' has {num_existing} probe(s). Generating {num_needed} probe(s)..."
        )

        # Find referenced sources
        ref_source_ids = sorted(set(re.findall(r"src-[0-9a-f]{10}", concept["text"])))

        # Filter high-value sources
        high_value_refs = []
        other_refs = []
        for sid in ref_source_ids:
            if sid in sources:
                src_info = sources[sid]
                strength = src_info["evidence_strength"]
                if strength in ["strong", "primary-doc"]:
                    high_value_refs.append(sid)
                else:
                    other_refs.append(sid)
            else:
                # Stub or unknown source
                pass

        # Select best source to use
        selected_source_id = None
        if high_value_refs:
            # Prefer first high-value source
            selected_source_id = high_value_refs[0]
            print(f"  Using high-value source reference: {selected_source_id}")
        elif other_refs:
            selected_source_id = other_refs[0]
            print(
                f"  Warning: no high-value source references found for '{concept_name}'. Using: {selected_source_id}"
            )
        else:
            # Let's find any high-value source in the vault as a desperate fallback
            high_value_all = [
                sid
                for sid, s in sources.items()
                if s["evidence_strength"] in ["strong", "primary-doc"]
            ]
            if high_value_all:
                selected_source_id = high_value_all[0]
                print(
                    f"  Warning: no source references found for '{concept_name}'. Using global high-value fallback: {selected_source_id}"
                )
            else:
                # No sources at all? Use first available source
                if sources:
                    selected_source_id = list(sources.keys())[0]
                    print(
                        f"  Warning: no sources found at all. Using global fallback: {selected_source_id}"
                    )
                else:
                    print(
                        "  Error: no source summaries available in the vault to generate probes from!"
                    )
                    continue

        src_data = sources[selected_source_id]
        source_content = src_data["text"]

        # Check if source is refreshed or has temporal metadata
        has_temporal = (
            "refreshed" in source_content.lower()
            or "earlier capture" in source_content.lower()
            or "ingested_at" in src_data["frontmatter"]
        )

        # Generate probes using LLM
        retries = 3
        generated = []
        for attempt in range(retries):
            try:
                generated = generate_probes_for_concept(
                    concept_name=concept_name,
                    source_id=selected_source_id,
                    source_content=source_content,
                    num_needed=num_needed,
                    has_temporal=has_temporal,
                )
                if len(generated) >= num_needed:
                    break
                print(
                    f"  Attempt {attempt + 1}: Generated {len(generated)}/{num_needed} probes. Retrying..."
                )
            except Exception as e:
                print(f"  Attempt {attempt + 1} failed: {e}")

        if not generated:
            print(
                f"  Failed to generate probes for concept '{concept_name}' after {retries} attempts."
            )
            continue

        print(f"  Successfully generated {len(generated)} probe(s) for '{concept_name}'.")
        for gp in generated:
            all_probes.append(gp)
            new_probes_generated += 1

        # Save after each concept to prevent data loss if interrupted
        save_probes(all_probes)

    print(f"Done! Generated {new_probes_generated} new probe(s). Total probes: {len(all_probes)}")


if __name__ == "__main__":
    main()
