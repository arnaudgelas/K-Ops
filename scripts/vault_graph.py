from __future__ import annotations

import csv
import datetime as dt
import json
import math
import re
from collections import Counter, deque
from pathlib import Path
from typing import Iterable

import yaml

from utils import CONFIG, ROOT, ensure_dir, parse_frontmatter


GRAPH_DIR = ROOT / "data" / "graph"
GRAPH_PATH = GRAPH_DIR / "vault_graph.json"
RETENTION_REPORT_PATH = GRAPH_DIR / "retention_report.json"

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
ANSWER_VAULT_UPDATES_RE = re.compile(r"## Vault Updates\s+(.*?)(?:\n## |\Z)", re.DOTALL)
RELATED_SECTION_RE = re.compile(r"## Related Concepts\s+(.*?)(?:\n## |\Z)", re.DOTALL)
EVIDENCE_SECTION_RE = re.compile(r"## Evidence / Source Basis\s+(.*?)(?:\n## |\Z)", re.DOTALL)
CLAIMS_SECTION_RE = re.compile(r"## Key Claims\s+(.*?)(?:\n## |\Z)", re.DOTALL)
SOURCE_LINK_RE = re.compile(r"\[\[Sources/(src-[0-9a-f]{10})\|")
CONCEPT_LINK_RE = re.compile(r"\[\[Concepts/([^|\]]+)")
GENERIC_LINK_RE = re.compile(r"\[\[((?:Concepts|Sources)/[^|\]]+)")
ANSWER_LINK_RE = re.compile(r"\[\[(Answers/[^|\]]+)")
BULLET_RE = re.compile(r"^\s*[-*]\s+(.*\S.*?)\s*$")



def read_note(path: Path) -> tuple[dict, str]:
    return parse_frontmatter(path.read_text(encoding="utf-8"))


def file_age_days(path: Path) -> float:
    return max(0.0, (dt.datetime.now().date() - dt.datetime.fromtimestamp(path.stat().st_mtime).date()).days)


def parse_iso_date(value: str | None) -> dt.datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        return dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None


def note_kind(path: Path) -> str:
    if path.parent == CONFIG.concepts_dir:
        return "concept"
    if path.parent == CONFIG.summaries_dir:
        return "source"
    if path.parent == CONFIG.answers_dir:
        return "answer"
    return "note"


def note_scope(kind: str, frontmatter: dict) -> str:
    if kind == "answer":
        return str(frontmatter.get("scope") or ("shared" if frontmatter.get("answer_quality") == "durable" else "private"))
    return "shared"


def retention_half_life(kind: str, frontmatter: dict) -> float:
    if kind == "claim":
        quality = str(frontmatter.get("claim_quality") or "")
        if quality == "supported":
            return 365.0
        if quality in {"provisional", "conflicting"}:
            return 120.0
        if quality in {"weak", "stale"}:
            return 45.0
        return 180.0
    if kind == "answer":
        return 180.0 if frontmatter.get("answer_quality") == "durable" else 21.0
    if kind == "source":
        strength = str(frontmatter.get("evidence_strength") or "")
        if strength in {"primary-doc", "strong"}:
            return 365.0
        if strength == "secondary":
            return 180.0
        return 45.0
    quality = str(frontmatter.get("claim_quality") or "")
    if quality == "supported":
        return 365.0
    if quality in {"provisional", "conflicting"}:
        return 120.0
    if quality in {"weak", "stale"}:
        return 45.0
    return 180.0


def retention_score(age_days: float, half_life_days: float) -> float:
    if half_life_days <= 0:
        return 0.0
    return round(math.pow(0.5, age_days / half_life_days), 6)


def retention_tier(score: float) -> str:
    if score >= 0.7:
        return "fresh"
    if score >= 0.4:
        return "healthy"
    if score >= 0.2:
        return "aging"
    return "stale"


def node_id(kind: str, stem: str) -> str:
    return f"{kind}:{stem}"


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def json_safe(value):
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def extract_bullets(text: str) -> list[str]:
    bullets: list[str] = []
    for line in text.splitlines():
        match = BULLET_RE.match(line)
        if match:
            bullets.append(normalize_whitespace(match.group(1)))
    return bullets


def base_node(kind: str, stem: str, path: Path, frontmatter: dict, body: str) -> dict:
    title = str(frontmatter.get("title") or stem)
    if kind == "answer":
        age_source = parse_iso_date(str(frontmatter.get("asked_at") or ""))
    elif kind == "source":
        raw_id = str(frontmatter.get("source_id") or stem)
        metadata_path = CONFIG.raw_dir / raw_id / "metadata.json"
        checked_at = None
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                checked_at = parse_iso_date(str(metadata.get("last_checked_at") or ""))
            except json.JSONDecodeError:
                checked_at = None
        age_source = checked_at
    else:
        age_source = parse_iso_date(str(frontmatter.get("created") or frontmatter.get("updated") or ""))

    age_days = file_age_days(path) if age_source is None else max(0.0, (dt.datetime.now().date() - age_source.date()).days)
    half_life = retention_half_life(kind, frontmatter)
    score = retention_score(age_days, half_life)

    if kind == "answer":
        quality = str(frontmatter.get("answer_quality") or "memo-only")
        scope = note_scope(kind, frontmatter)
    elif kind == "source":
        quality = str(frontmatter.get("evidence_strength") or "")
        scope = "shared"
    else:
        quality = str(frontmatter.get("claim_quality") or "")
        scope = "shared"

    return {
        "id": node_id(kind, stem),
        "kind": kind,
        "title": title,
        "path": path.relative_to(ROOT).as_posix(),
        "scope": scope,
        "status": quality,
        "age_days": round(age_days, 2),
        "retention_score": score,
        "retention_tier": retention_tier(score),
        "half_life_days": half_life,
        "tags": json_safe(frontmatter.get("tags", [])),
        "frontmatter": json_safe(frontmatter),
        "search_text": f"{title}\n{body}".strip(),
    }


def claim_node(concept_path: Path, concept_frontmatter: dict, concept_body: str, claim_text: str, claim_index: int) -> dict:
    concept_stem = concept_path.stem
    concept_title = str(concept_frontmatter.get("title") or concept_stem)
    claim_id = node_id("claim", f"{concept_stem}-{claim_index:02d}")
    claim_quality = str(concept_frontmatter.get("claim_quality") or "")
    age_source = parse_iso_date(str(concept_frontmatter.get("created") or concept_frontmatter.get("updated") or ""))
    age_days = file_age_days(concept_path) if age_source is None else max(0.0, (dt.datetime.now().date() - age_source.date()).days)
    half_life = retention_half_life("claim", concept_frontmatter)
    score = retention_score(age_days, half_life)
    claim_title = claim_text[:96].rstrip(" ,;:") or f"{concept_title} claim {claim_index}"
    return {
        "id": claim_id,
        "kind": "claim",
        "title": claim_title,
        "path": f"{concept_path.relative_to(ROOT).as_posix()}#claim-{claim_index}",
        "scope": "shared",
        "status": claim_quality,
        "age_days": round(age_days, 2),
        "retention_score": score,
        "retention_tier": retention_tier(score),
        "half_life_days": half_life,
        "tags": json_safe(concept_frontmatter.get("tags", [])),
        "concept_id": node_id("concept", concept_stem),
        "claim_index": claim_index,
        "claim_text": claim_text,
        "frontmatter": {
            "concept": concept_stem,
            "claim_quality": claim_quality,
        },
        "search_text": f"{concept_title}\n{claim_text}",
    }


def extract_section_links(text: str, section_re: re.Pattern[str]) -> list[str]:
    match = section_re.search(text)
    if not match:
        return []
    return sorted(set(re.findall(r"\[\[(?:Concepts|Sources|Answers)/([^|\]]+)", match.group(1))))


def extract_any_links(text: str) -> list[str]:
    return sorted(set(GENERIC_LINK_RE.findall(text) + ANSWER_LINK_RE.findall(text)))


def build_nodes_and_edges() -> dict:
    nodes: list[dict] = []
    edges: list[dict] = []
    node_map: dict[str, dict] = {}

    def add_node(kind: str, path: Path, frontmatter: dict, body: str) -> None:
        stem = path.stem
        node = base_node(kind, stem, path, frontmatter, body)
        nodes.append(node)
        node_map[node["id"]] = node

    for path in sorted(CONFIG.concepts_dir.glob("*.md")):
        frontmatter, body = read_note(path)
        add_node("concept", path, frontmatter, body)
        concept_id = node_id("concept", path.stem)
        claims_match = CLAIMS_SECTION_RE.search(body)
        if claims_match:
            claim_texts = extract_bullets(claims_match.group(1))
            evidence_sources = extract_section_links(body, EVIDENCE_SECTION_RE)
            for index, claim_text in enumerate(claim_texts, start=1):
                node = claim_node(path, frontmatter, body, claim_text, index)
                nodes.append(node)
                node_map[node["id"]] = node
                edges.append(
                    {
                        "source": concept_id,
                        "target": node["id"],
                        "relation": "has_claim",
                        "section": "Key Claims",
                        "weight": 1.0,
                    }
                )
                edges.append(
                    {
                        "source": node["id"],
                        "target": concept_id,
                        "relation": "derived_from",
                        "section": "Key Claims",
                        "weight": 1.0,
                    }
                )
                for linked_source in evidence_sources:
                    target = node_id("source", linked_source)
                    edges.append(
                        {
                            "source": node["id"],
                            "target": target,
                            "relation": "supported_by",
                            "section": "Evidence / Source Basis",
                            "weight": 1.0,
                        }
                    )

    for path in sorted(CONFIG.summaries_dir.glob("src-*.md")):
        frontmatter, body = read_note(path)
        add_node("source", path, frontmatter, body)

    for path in sorted(CONFIG.answers_dir.glob("*.md")):
        frontmatter, body = read_note(path)
        if frontmatter.get("type") != "answer":
            continue
        add_node("answer", path, frontmatter, body)

    def add_edge(source: str, target: str, relation: str, section: str, weight: float = 1.0) -> None:
        if source == target:
            return
        if source not in node_map or target not in node_map:
            return
        edges.append(
            {
                "source": source,
                "target": target,
                "relation": relation,
                "section": section,
                "weight": weight,
            }
        )

    for path in sorted(CONFIG.concepts_dir.glob("*.md")):
        frontmatter, body = read_note(path)
        source_id = node_id("concept", path.stem)
        for linked_source in extract_section_links(body, EVIDENCE_SECTION_RE):
            add_edge(source_id, node_id("source", linked_source), "cites_source", "Evidence / Source Basis")
        for related in extract_section_links(body, RELATED_SECTION_RE):
            add_edge(source_id, node_id("concept", related), "related_to", "Related Concepts")
            add_edge(node_id("concept", related), source_id, "related_to", "Related Concepts")

    for path in sorted(CONFIG.summaries_dir.glob("src-*.md")):
        frontmatter, body = read_note(path)
        source_id = node_id("source", path.stem)
        for related in extract_section_links(body, RELATED_SECTION_RE):
            add_edge(source_id, node_id("concept", related), "supports_concept", "Related Concepts")

    for path in sorted(CONFIG.answers_dir.glob("*.md")):
        frontmatter, body = read_note(path)
        if frontmatter.get("type") != "answer":
            continue
        answer_id = node_id("answer", path.stem)
        updates_match = ANSWER_VAULT_UPDATES_RE.search(body)
        updates_section = updates_match.group(1) if updates_match else ""
        for linked in extract_any_links(updates_section or body):
            target_kind = "source" if linked.startswith("Sources/") else "concept" if linked.startswith("Concepts/") else "answer"
            if linked.startswith("Answers/"):
                target_kind = "answer"
            stem = linked.split("/", 1)[1] if "/" in linked else linked
            relation = "updates" if updates_section else "mentions"
            add_edge(answer_id, node_id(target_kind, stem), relation, "Vault Updates")

    return {
        "project": CONFIG.project_name,
        "nodes": nodes,
        "edges": edges,
    }


def save_graph(graph: dict, path: Path = GRAPH_PATH) -> bool:
    ensure_dir(path.parent)
    content = json.dumps(graph, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def load_graph(path: Path = GRAPH_PATH) -> dict:
    if not path.exists():
        return build_nodes_and_edges()
    return json.loads(path.read_text(encoding="utf-8"))


def adjacency(graph: dict) -> dict[str, list[dict]]:
    adj: dict[str, list[dict]] = {}
    for edge in graph["edges"]:
        adj.setdefault(edge["source"], []).append(edge)
    return adj


def node_lookup(graph: dict) -> dict[str, dict]:
    return {node["id"]: node for node in graph["nodes"]}


def term_score(text: str, query_terms: list[str]) -> float:
    hay = text.lower()
    return float(sum(hay.count(term) for term in query_terms if term))


def visible_node(node: dict, scope: str) -> bool:
    if scope == "all":
        return True
    return node.get("scope") == "shared"


def lexical_rank(graph: dict, query: str, scope: str = "all") -> list[tuple[str, float]]:
    terms = [term for term in re.split(r"\W+", query.lower()) if term]
    scored: list[tuple[str, float]] = []
    for node in graph["nodes"]:
        if not visible_node(node, scope):
            continue
        score = term_score(node["title"], terms) * 3.0
        score += term_score(node.get("search_text", ""), terms)
        score += term_score(" ".join(map(str, node.get("tags", []))), terms)
        score += term_score(node["id"], terms)
        if score > 0:
            scored.append((node["id"], score))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored


def graph_rank(graph: dict, query: str, max_depth: int = 2, scope: str = "all") -> list[tuple[str, float]]:
    terms = [term for term in re.split(r"\W+", query.lower()) if term]
    lookup = node_lookup(graph)
    adj = adjacency(graph)
    seeds = [node_id for node_id, _ in lexical_rank(graph, query, scope=scope)]
    if not seeds:
        return []
    seen: set[str] = set()
    queue: deque[tuple[str, int]] = deque((seed, 0) for seed in seeds[:5])
    scored: dict[str, float] = {}
    while queue:
        current, depth = queue.popleft()
        if current in seen or depth > max_depth:
            continue
        seen.add(current)
        node = lookup.get(current)
        if not node:
            continue
        if not visible_node(node, scope):
            continue
        base = 2.0 / (depth + 1)
        score = base + term_score(node["title"], terms)
        scored[current] = max(scored.get(current, 0.0), score)
        for edge in adj.get(current, []):
            target = lookup.get(edge["target"])
            if target and not visible_node(target, scope):
                continue
            queue.append((edge["target"], depth + 1))
    ranked = sorted(scored.items(), key=lambda item: (-item[1], item[0]))
    return ranked


def reciprocal_rank_fusion(rankings: Iterable[list[tuple[str, float]]], k: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, (node_id, _score) in enumerate(ranking, start=1):
            scores[node_id] = scores.get(node_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def search_graph(graph: dict, query: str, limit: int = 10, scope: str = "all") -> list[dict]:
    lexical = lexical_rank(graph, query, scope=scope)
    graph_based = graph_rank(graph, query, scope=scope)
    fused = reciprocal_rank_fusion([lexical, graph_based])
    lookup = node_lookup(graph)
    results: list[dict] = []
    for node_id, score in fused[:limit]:
        node = lookup.get(node_id)
        if not node:
            continue
        if not visible_node(node, scope):
            continue
        results.append({**node, "score": round(score, 6)})
    return results


def traverse_graph(graph: dict, start: str, depth: int = 2, relations: set[str] | None = None, scope: str = "all") -> list[dict]:
    lookup = node_lookup(graph)
    adj = adjacency(graph)
    matches = [
        node
        for node in graph["nodes"]
        if visible_node(node, scope)
        and (start.lower() in {node["id"].lower(), node["title"].lower()} or start.lower() in node["path"].lower())
    ]
    if not matches:
        matches = [node for node in graph["nodes"] if visible_node(node, scope) and start.lower() in node["title"].lower()]
    if not matches:
        return []
    start_ids = [node["id"] for node in matches[:3]]
    seen: set[str] = set()
    queue: deque[tuple[str, int, str | None]] = deque((node_id, 0, None) for node_id in start_ids)
    results: list[dict] = []
    while queue:
        current, current_depth, via = queue.popleft()
        if current in seen or current_depth > depth:
            continue
        seen.add(current)
        node = lookup.get(current)
        if not node:
            continue
        if not visible_node(node, scope):
            continue
        if current_depth > 0:
            results.append({"node": node, "depth": current_depth, "via": via})
        for edge in adj.get(current, []):
            if relations and edge["relation"] not in relations:
                continue
            target = lookup.get(edge["target"])
            if target and not visible_node(target, scope):
                continue
            queue.append((edge["target"], current_depth + 1, edge["relation"]))
    return results


def retention_report(graph: dict, limit: int = 50) -> list[dict]:
    ranked = sorted(graph["nodes"], key=lambda node: (node["retention_score"], node["title"]))
    return ranked[:limit]


def write_retention_report(graph: dict, path: Path = RETENTION_REPORT_PATH, limit: int = 50) -> bool:
    ensure_dir(path.parent)
    top_nodes = retention_report(graph, limit=limit)
    summary = Counter((node["kind"], node["retention_tier"]) for node in graph["nodes"])
    payload = {
        "project": CONFIG.project_name,
        "counts": {
            "nodes": len(graph["nodes"]),
            "edges": len(graph["edges"]),
            "by_kind": dict(Counter(node["kind"] for node in graph["nodes"])),
            "by_tier": dict(Counter(node["retention_tier"] for node in graph["nodes"])),
            "by_kind_and_tier": {f"{kind}:{tier}": count for (kind, tier), count in summary.items()},
        },
        "lowest_retention": top_nodes,
    }
    content = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def export_csv_rows(graph: dict) -> list[dict]:
    rows: list[dict] = []
    for node in graph["nodes"]:
        rows.append(
            {
                "kind": node["kind"],
                "id": node["id"],
                "title": node["title"],
                "path": node["path"],
                "scope": node["scope"],
                "status": node["status"],
                "retention_score": node["retention_score"],
                "retention_tier": node["retention_tier"],
            }
        )
    return rows
