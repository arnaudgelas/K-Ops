"""
Generate held-out benchmark questions deterministically from vault data.
Produces 20 questions per class (lookup, synthesis, freshness, code, trap) = 100 total.
Appends to research/benchmarks/held-out/questions.jsonl (preserving existing seeds).
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import ROOT, parse_frontmatter

HELD_OUT = ROOT / "research" / "benchmarks" / "held-out" / "questions.jsonl"
CLAIMS_PATH = ROOT / "data" / "claims.json"
CONTRADICTIONS_PATH = ROOT / "data" / "contradictions.json"
CONCEPTS_DIR = ROOT / "notes" / "Concepts"
SOURCES_DIR = ROOT / "notes" / "Sources"

TARGETS = {"lookup": 20, "synthesis": 20, "freshness": 20, "code": 20, "trap": 20}

random.seed(42)  # deterministic


def qid(cls: str, n: int) -> str:
    return f"held-{cls}-{n:03d}"


def load_existing() -> tuple[str, list[dict]]:
    lines = HELD_OUT.read_text().splitlines() if HELD_OUT.exists() else []
    comment = (
        next((line for line in lines if "_comment" in line), None)
        or '{"_comment": "FROZEN — do not edit, regenerate, or reuse in dev-probes. See plan.md T6."}'
    )
    seeds = []
    for line in lines:
        line = line.strip()
        if line and "_comment" not in line:
            try:
                seeds.append(json.loads(line))
            except Exception:
                pass
    return comment, seeds


def load_claims() -> list[dict]:
    data = json.loads(CLAIMS_PATH.read_text())
    return data.get("claims", [])


def load_contradictions() -> list[dict]:
    data = json.loads(CONTRADICTIONS_PATH.read_text())
    return data.get("contradictions", [])


def load_source_meta() -> dict[str, dict]:
    meta: dict[str, dict] = {}
    for p in SOURCES_DIR.rglob("*.md"):
        try:
            fm, body = parse_frontmatter(p.read_text())
            sid = fm.get("source_id") or p.stem
            if sid.startswith("src-"):
                meta[sid] = {**fm, "_body": body, "_path": str(p)}
        except Exception:
            pass
    return meta


def load_concept(name: str) -> tuple[dict, str]:
    p = CONCEPTS_DIR / f"{name}.md"
    if p.exists():
        return parse_frontmatter(p.read_text())
    return {}, ""


# ── helpers ────────────────────────────────────────────────────────────────


def snippet(text: str, keyword: str, width: int = 120) -> str:
    idx = text.lower().find(keyword.lower())
    if idx < 0:
        return text[:width].strip()
    start = max(0, idx - 30)
    return text[start : start + width].strip()


def first_bullet(body: str) -> str:
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("- ") and len(line) > 10:
            return re.sub(r"\[\[[^\]]+\|([^\]]+)\]\]", r"\1", line[2:]).strip()
    return ""


def clean(text: str) -> str:
    text = re.sub(r"\[\[[^\]]+\|([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    return text.strip()


# ── generators ─────────────────────────────────────────────────────────────


def gen_lookup(claims: list[dict], source_meta: dict, n_existing: int) -> list[dict]:
    """One specific fact per supported/provisional directly-cited claim."""
    pool = [
        c
        for c in claims
        if c["evidence_status"] == "direct"
        and c["claim_quality"] in ("supported", "provisional")
        and c["inline_source_ids"]
    ]
    random.shuffle(pool)
    out, seen_concepts = [], set()
    for c in pool:
        if len(out) >= TARGETS["lookup"] - n_existing:
            break
        concept = c["concept"]
        if concept in seen_concepts:
            continue
        seen_concepts.add(concept)
        sid = c["inline_source_ids"][0]
        sm = source_meta.get(sid, {})
        title = sm.get("title", sid)
        claim = clean(c["claim_text"])
        if len(claim) < 20:
            continue
        # Build question from claim text
        question = (
            f"According to the source note for '{clean(title)}' ({sid}), "
            f'what specific fact or capability is described by this claim: "{claim[:120]}"?'
        )
        out.append(
            {
                "id": qid("lookup", n_existing + len(out) + 1),
                "class": "lookup",
                "question": question,
                "required_source_ids": [sid],
                "expected_answer_facts": [claim],
                "forbidden_unsupported_claims": [
                    f"The source does not address {concept.replace('_', ' ')}."
                ],
                "acceptable_uncertainty": "The answer may paraphrase rather than quote verbatim.",
                "reviewer_notes": "held-out",
            }
        )
    return out


def gen_synthesis(claims: list[dict], source_meta: dict, n_existing: int) -> list[dict]:
    """Questions needing 2+ sources from the same concept page."""
    # Group direct claims by concept, keep those with ≥2 distinct sources
    by_concept: dict[str, list[dict]] = {}
    for c in claims:
        if c["evidence_status"] == "direct" and len(c["inline_source_ids"]) >= 1:
            by_concept.setdefault(c["concept"], []).append(c)

    out = []
    concepts = list(by_concept.keys())
    random.shuffle(concepts)
    for concept in concepts:
        if len(out) >= TARGETS["synthesis"] - n_existing:
            break
        cc = by_concept[concept]
        # collect distinct sources across all claims for this concept
        all_sids: list[str] = []
        for c in cc:
            for s in c["inline_source_ids"]:
                if s not in all_sids:
                    all_sids.append(s)
        if len(all_sids) < 2:
            continue
        sids = all_sids[:3]
        titles = [clean(source_meta.get(s, {}).get("title", s)) for s in sids]
        claims_sample = [clean(c["claim_text"]) for c in cc[:3]]
        topic = concept.replace("_", " ")
        question = (
            f"The vault concept page '{topic}' cites multiple sources. "
            f"Synthesize what sources {', '.join(titles[:2])} collectively establish "
            f"about {topic}. What key points do they agree on, and what does each uniquely contribute?"
        )
        out.append(
            {
                "id": qid("synthesis", n_existing + len(out) + 1),
                "class": "synthesis",
                "question": question,
                "required_source_ids": sids,
                "expected_answer_facts": claims_sample[:3],
                "forbidden_unsupported_claims": [
                    f"All sources say exactly the same thing about {topic}.",
                    "No synthesis is possible; the sources are unrelated.",
                ],
                "acceptable_uncertainty": "Partial synthesis is acceptable if the major claims are covered.",
                "reviewer_notes": "held-out",
            }
        )
    return out


def gen_freshness(contradictions: list[dict], claims: list[dict], n_existing: int) -> list[dict]:
    """One question per documented contradiction."""
    claim_map = {c["claim_id"]: c for c in claims}
    out = []
    for ctr in contradictions:
        if len(out) >= TARGETS["freshness"] - n_existing:
            break
        cids = ctr.get("claim_ids", [])
        sids = ctr.get("source_ids", [])
        open_q = clean(ctr.get("open_question", ""))
        concept = clean(ctr.get("concept", ""))
        if not open_q or not cids:
            continue
        # Build question from the contradiction's open question
        question = (
            f"The vault documents a contradiction in concept '{concept.replace('_', ' ')}'. "
            f'The documented tension is: "{open_q[:200]}". '
            f"What does the vault say about this conflict, and which claim IDs are involved?"
        )
        involved_claims = [claim_map[cid]["claim_text"] for cid in cids[:3] if cid in claim_map]
        out.append(
            {
                "id": qid("freshness", n_existing + len(out) + 1),
                "class": "freshness",
                "question": question,
                "required_source_ids": sids[:3]
                if sids
                else [
                    c["source_ids"][0]
                    for c in [claim_map.get(cid, {}) for cid in cids[:1]]
                    if c.get("source_ids")
                ],
                "expected_answer_facts": [
                    f"The contradiction is documented in the vault under concept '{concept}'.",
                    open_q[:200],
                ]
                + involved_claims[:2],
                "forbidden_unsupported_claims": [
                    f"There is no documented conflict about {concept.replace('_', ' ')} in the vault.",
                    "The vault resolves this tension with a definitive answer.",
                ],
                "acceptable_uncertainty": "Acknowledging the contradiction is a correct answer.",
                "reviewer_notes": "held-out",
            }
        )
    return out


def gen_code(source_meta: dict, n_existing: int) -> list[dict]:
    """Questions about specific code/repo facts from github source notes."""
    github = [
        (sid, sm)
        for sid, sm in source_meta.items()
        if sm.get("source_kind") == "github-repo-snapshot"
        and sm.get("evidence_strength") in ("primary-doc", "strong", "code", "primary-doc-partial")
    ]
    random.shuffle(github)

    _BULLET = re.compile(r"^\s*[-*]\s+(.+)", re.MULTILINE)

    out = []
    for sid, sm in github:
        if len(out) >= TARGETS["code"] - n_existing:
            break
        body = sm.get("_body", "")
        title = clean(sm.get("title", sid))
        # Find a bullet with a specific code fact (file path, tool name, command)
        bullets = _BULLET.findall(body)
        code_bullets = [
            b
            for b in bullets
            if any(
                k in b
                for k in [
                    ".py",
                    ".ts",
                    ".js",
                    ".go",
                    ".rs",
                    "npm",
                    "cargo",
                    "pip",
                    "docker",
                    "make",
                    "pytest",
                    "jest",
                    "vitest",
                    "README",
                    "package.json",
                    "pyproject",
                    "Makefile",
                    "main.",
                    "src/",
                    "lib/",
                    "cmd/",
                    "api/",
                    "uv run",
                    "yarn",
                    "pnpm",
                ]
            )
        ]
        if not code_bullets:
            continue
        fact = clean(code_bullets[0])[:160]
        question = (
            f"According to the vault's source note for the GitHub repository '{title}' ({sid}), "
            f'what specific file, tool, command, or build artifact is described by: "{fact[:100]}"? '
            f"Provide the exact name mentioned in the source note."
        )
        out.append(
            {
                "id": qid("code", n_existing + len(out) + 1),
                "class": "code",
                "question": question,
                "required_source_ids": [sid],
                "expected_answer_facts": [fact],
                "forbidden_unsupported_claims": [
                    f"The source note for {title} does not mention any specific files or build tools.",
                ],
                "acceptable_uncertainty": "The answer must name a specific artifact, not describe it generically.",
                "reviewer_notes": "held-out",
            }
        )
    return out


def gen_trap(claims: list[dict], source_meta: dict, n_existing: int) -> list[dict]:
    """Questions where the 'obvious' answer is wrong or unsupported."""
    # Use weak/provisional claims — the trap is asserting them as certain
    pool = [
        c
        for c in claims
        if c["claim_quality"] in ("weak", "provisional")
        and c["evidence_status"] in ("inherited", "unsupported")
    ]
    random.shuffle(pool)

    out, seen = [], set()
    for c in pool:
        if len(out) >= TARGETS["trap"] - n_existing:
            break
        if c["concept"] in seen:
            continue
        seen.add(c["concept"])
        claim = clean(c["claim_text"])
        if len(claim) < 20:
            continue
        concept = c["concept"].replace("_", " ")
        sids = c.get("inline_source_ids") or c.get("source_ids", [])
        # Frame the question to elicit overconfident assertion
        question = (
            f"Is the following claim definitively supported by strong evidence in the vault? "
            f'"{claim[:160]}" '
            f"(This claim appears in the '{concept}' concept page.)"
        )
        out.append(
            {
                "id": qid("trap", n_existing + len(out) + 1),
                "class": "trap",
                "question": question,
                "required_source_ids": sids[:2] if sids else [],
                "expected_answer_facts": [
                    f"The claim is marked as '{c['claim_quality']}' quality in the vault.",
                    f"The evidence status is '{c['evidence_status']}' — not directly cited.",
                    "A cautious answer must express uncertainty about this claim.",
                ],
                "forbidden_unsupported_claims": [
                    "Yes, this claim is definitively proven by strong evidence.",
                    "The vault fully supports this claim without qualification.",
                ],
                "acceptable_uncertainty": "The answer should express explicit uncertainty or note the claim is weakly supported.",
                "reviewer_notes": "held-out",
            }
        )
    return out


# ── main ───────────────────────────────────────────────────────────────────


def main() -> None:
    print("Loading vault data...")
    claims = load_claims()
    contradictions = load_contradictions()
    source_meta = load_source_meta()
    print(
        f"  {len(claims)} claims, {len(contradictions)} contradictions, {len(source_meta)} source notes"
    )

    comment, seeds = load_existing()
    existing_by_class: dict[str, int] = {}
    for s in seeds:
        cls = s.get("class", "?")
        existing_by_class[cls] = existing_by_class.get(cls, 0) + 1
    print(f"  Existing seeds: {existing_by_class}")

    print("Generating questions...")
    new_questions: list[dict] = []

    n_lookup = existing_by_class.get("lookup", 0)
    if n_lookup < TARGETS["lookup"]:
        qs = gen_lookup(claims, source_meta, n_lookup)
        print(f"  lookup: +{len(qs)}")
        new_questions.extend(qs)

    n_synth = existing_by_class.get("synthesis", 0)
    if n_synth < TARGETS["synthesis"]:
        qs = gen_synthesis(claims, source_meta, n_synth)
        print(f"  synthesis: +{len(qs)}")
        new_questions.extend(qs)

    n_fresh = existing_by_class.get("freshness", 0)
    if n_fresh < TARGETS["freshness"]:
        qs = gen_freshness(contradictions, claims, n_fresh)
        print(f"  freshness: +{len(qs)}")
        new_questions.extend(qs)

    n_code = existing_by_class.get("code", 0)
    if n_code < TARGETS["code"]:
        qs = gen_code(source_meta, n_code)
        print(f"  code: +{len(qs)}")
        new_questions.extend(qs)

    n_trap = existing_by_class.get("trap", 0)
    if n_trap < TARGETS["trap"]:
        qs = gen_trap(claims, source_meta, n_trap)
        print(f"  trap: +{len(qs)}")
        new_questions.extend(qs)

    all_questions = seeds + new_questions
    # Write
    HELD_OUT.parent.mkdir(parents=True, exist_ok=True)
    lines = [comment] + [json.dumps(q, ensure_ascii=False) for q in all_questions]
    HELD_OUT.write_text("\n".join(lines) + "\n")
    print(f"\nWrote {len(all_questions)} questions to {HELD_OUT.relative_to(ROOT)}")
    by_class: dict[str, int] = {}
    for q in all_questions:
        by_class[q["class"]] = by_class.get(q["class"], 0) + 1
    for cls, n in sorted(by_class.items()):
        print(f"  {cls}: {n}")


if __name__ == "__main__":
    main()
