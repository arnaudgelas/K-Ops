import datetime
import json
import re
from utils import CONFIG, ROOT, parse_frontmatter


def get_year(fm):
    for field in ["year", "published_date", "published", "date"]:
        val = fm.get(field)
        if val:
            m = re.search(r"\b(19\d\d|20\d\d)\b", str(val))
            if m:
                return m.group(1)
    ingested_at = fm.get("ingested_at") or fm.get("ingested")
    if ingested_at:
        m = re.search(r"\b(19\d\d|20\d\d)\b", str(ingested_at))
        if m:
            return m.group(1)
        if len(str(ingested_at)) >= 4:
            yr = str(ingested_at)[:4]
            if yr.isdigit() and (1900 <= int(yr) <= 2100):
                return yr
    return "Unknown"


def get_sources_data():
    sources = []
    for path in sorted(CONFIG.summaries_dir.rglob("src-*.md")):
        text = path.read_text(encoding="utf-8")
        frontmatter, _ = parse_frontmatter(text)
        rel_path = path.relative_to(CONFIG.vault_dir).with_suffix("").as_posix()
        sources.append(
            {"source_id": path.stem, "relative_path": rel_path, "frontmatter": frontmatter}
        )
    return sources


def get_concepts_data():
    concepts = []
    for path in sorted(CONFIG.concepts_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        frontmatter, _ = parse_frontmatter(text)
        # Skip redirects
        if frontmatter.get("type") == "redirect":
            continue
        concepts.append(
            {
                "stem": path.stem,
                "title": frontmatter.get("title") or path.stem,
                "frontmatter": frontmatter,
            }
        )
    return concepts


def generate_source_atlas_content(sources):
    grouped = {}
    for src in sources:
        year = get_year(src["frontmatter"])
        kind = src["frontmatter"].get("source_kind") or src["frontmatter"].get("kind") or "Unknown"
        strength = src["frontmatter"].get("evidence_strength") or "Unknown"
        grouped.setdefault(year, {}).setdefault(kind, {}).setdefault(strength, []).append(src)

    lines = [
        "---",
        'title: "Source Atlas"',
        "type: index",
        "tags:",
        "  - kb/index",
        "---",
        "# Source Atlas",
        "",
        "## What It Is",
        "",
        "This page is the navigation layer for source summaries. Use it when you want to inspect evidence coverage directly rather than starting from a concept page.",
        "",
        "## Source Groups",
        "",
    ]

    for year in sorted(grouped.keys(), reverse=True):
        lines.append(f"### {year}")
        lines.append("")
        for kind in sorted(grouped[year].keys()):
            lines.append(f"#### {kind}")
            lines.append("")
            for strength in sorted(grouped[year][kind].keys()):
                lines.append(f"##### {strength}")
                lines.append("")
                sorted_sources = sorted(grouped[year][kind][strength], key=lambda x: x["source_id"])
                for src in sorted_sources:
                    rel_path = src["relative_path"]
                    title = src["frontmatter"].get("title") or src["source_id"]
                    lines.append(f"- [[{rel_path}|{src['source_id']}]] ({title})")
                lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def generate_topic_atlas_content(concepts):
    tagged_concepts = {}
    for c in concepts:
        tags = [
            t for t in c["frontmatter"].get("tags", []) if t not in ("kb/concept", "kb/redirect")
        ]
        if not tags:
            tags = ["uncategorized"]
        for tag in tags:
            tagged_concepts.setdefault(tag, []).append(c)

    lines = [
        "---",
        'title: "Topic Atlas"',
        "type: index",
        "tags:",
        "  - kb/index",
        "---",
        "# Topic Atlas",
        "",
        "## What It Is",
        "",
        "This page is the topic map for the durable concept layer. Use it when you want to move across clusters instead of drilling through a single hub page. Auto-generated from `notes/Concepts/`.",
        "",
        "## Topic Clusters",
        "",
    ]

    for tag in sorted(tagged_concepts.keys()):
        heading = tag.replace("-", " ").replace("/", " ").title()
        lines.append(f"### {heading}")
        lines.append("")
        sorted_concepts = sorted(tagged_concepts[tag], key=lambda x: x["title"])
        for c in sorted_concepts:
            lines.append(f"- [[Concepts/{c['stem']}|{c['title']}]]")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def generate_source_registry_content():
    registry = json.loads(CONFIG.registry_path.read_text(encoding="utf-8"))
    TITLE_RE = re.compile(r'^title:\s*["\'](.+?)["\']', re.MULTILINE)
    rows = []
    for item in registry:
        sid = item.get("id", "")
        source = item.get("source", "")
        kind = item.get("kind", "")
        notes_path = item.get("notes_path", "")
        title = item.get("title_guess", sid)
        if notes_path:
            npath = ROOT / notes_path
            if npath.exists():
                m = TITLE_RE.search(npath.read_text(encoding="utf-8"))
                if m:
                    title = m.group(1)
        rows.append((sid, kind, title, source, notes_path))
    rows.sort(key=lambda x: x[0])
    lines = [
        "---",
        'title: "Source Registry"',
        "type: index",
        "tags:",
        "  - kb/index",
        "---",
        "# Source Registry",
        "",
        f"Flat lookup: source_id -> title, kind, origin. {len(rows)} sources.",
        "",
        "| source_id | kind | title | origin |",
        "|-----------|------|-------|--------|",
    ]
    for sid, kind, title, source, notes_path in rows:
        short_title = (title[:55] + "...") if len(title) > 55 else title
        short_source = (source[:55] + "...") if len(source) > 55 else source
        short_title = short_title.replace("|", "-")
        short_source = short_source.replace("|", "-")
        if notes_path:
            rel = notes_path
            if rel.startswith("notes/Sources/"):
                rel = rel[len("notes/Sources/") :]
            if rel.endswith(".md"):
                rel = rel[:-3]
            sid_link = f"[[Sources/{rel}|{sid}]]"
        else:
            sid_link = sid
        lines.append(f"| {sid_link} | {kind} | {short_title} | {short_source} |")
    return "\n".join(lines) + "\n"


def generate_updated_home_content(concepts):
    home_text = CONFIG.home_note.read_text(encoding="utf-8")
    sorted_concepts = sorted(concepts, key=lambda x: x["title"])
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    count = len(sorted_concepts)

    new_header = f"## All Concepts *(auto-generated {date_str} — {count} pages)*"
    bullets = [f"- [[Concepts/{c['stem']}|{c['title']}]]" for c in sorted_concepts]

    # Clean up the human presentation of Home.md by putting all concepts in a details/summary wrapper
    new_section = (
        new_header
        + "\n\n<details>\n<summary>Expand Flat Concept List</summary>\n\n"
        + "\n".join(bullets)
        + "\n</details>\n"
    )

    match = re.search(r"(?mi)^##\s+All Concepts\b", home_text)
    if not match:
        raise ValueError("Could not find ## All Concepts section in Home.md")
    start_idx = match.start()

    remainder = home_text[start_idx + len(match.group(0)) :]
    next_heading_match = re.search(r"(?m)^\s*##\s", remainder)
    if next_heading_match:
        end_idx = start_idx + len(match.group(0)) + next_heading_match.start()
    else:
        end_idx = len(home_text)

    return home_text[:start_idx] + new_section + home_text[end_idx:]


def get_author_org(fm):
    authors_list = []
    auths = fm.get("authors") or fm.get("author")
    if auths:
        if isinstance(auths, list):
            authors_list.extend([str(a).strip() for a in auths if a])
        else:
            authors_list.append(str(auths).strip())

    org = fm.get("organization")
    if org:
        org_str = str(org).strip()
        if org_str not in authors_list:
            authors_list.append(org_str)

    final_list = []
    for a in authors_list:
        if a and a.lower() not in ("unknown", "none", "null"):
            final_list.append(a)
    return final_list


def format_sources_list(src_list, limit_details=10):
    sorted_srcs = sorted(src_list, key=lambda x: x["source_id"])
    lines = []
    for src in sorted_srcs:
        title = src["frontmatter"].get("title") or src["source_id"]
        rel_path = src["relative_path"]
        title_esc = str(title).replace("[", "").replace("]", "").replace("|", "-")
        lines.append(f"- [[{rel_path}|{src['source_id']}]] ({title_esc})")

    if len(lines) > limit_details:
        return (
            "<details>\n<summary>Expand {count} sources</summary>\n\n{content}\n</details>".format(
                count=len(lines), content="\n".join(lines)
            )
        )
    else:
        return "\n".join(lines)


def generate_vault_dashboard_content(sources, concepts):
    # 1. Load Graph for retention scores
    retention_map = {}
    try:
        from vault_graph import load_graph

        graph = load_graph()
        for node in graph.get("nodes", []):
            if node.get("kind") == "source":
                sid = node.get("id", "").split(":", 1)[-1]
                retention_map[sid] = {
                    "score": node.get("retention_score", 1.0),
                    "tier": node.get("retention_tier", "fresh"),
                    "age_days": node.get("age_days", 0.0),
                }
    except Exception:
        pass

    # Build groupings
    # Alphabetical grouping by title
    alpha_groups = {}
    for src in sources:
        title = src["frontmatter"].get("title") or ""
        title = title.strip()
        if not title:
            title = src["source_id"]
        first_char = title[0].upper() if title else "#"
        if not first_char.isalpha():
            first_char = "#"
        alpha_groups.setdefault(first_char, []).append(src)

    # Author/Organization grouping
    author_groups = {}
    for src in sources:
        names = get_author_org(src["frontmatter"])
        if not names:
            names = ["Unknown / Unspecified"]
        for name in names:
            author_groups.setdefault(name, []).append(src)

    # Publication Year grouping
    year_groups = {}
    for src in sources:
        year = get_year(src["frontmatter"])
        year_groups.setdefault(year, []).append(src)

    # Evidence Strength grouping
    strength_groups = {}
    for src in sources:
        strength = src["frontmatter"].get("evidence_strength") or "Unknown"
        strength_groups.setdefault(strength, []).append(src)

    # Topic Tags grouping
    tag_groups = {}
    for src in sources:
        tags = src["frontmatter"].get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        clean_tags = [t for t in tags if t not in ("kb/source", "kb/index", "kb/concept")]
        if not clean_tags:
            clean_tags = ["uncategorized"]
        for tag in clean_tags:
            tag_groups.setdefault(tag, []).append(src)

    # Freshness / Low Retention
    stale_sources = []
    for src in sources:
        sid = src["source_id"]
        ret = retention_map.get(sid, {"score": 1.0, "tier": "fresh", "age_days": 0.0})
        stale_sources.append(
            {
                "source_id": sid,
                "relative_path": src["relative_path"],
                "title": src["frontmatter"].get("title") or sid,
                "score": ret["score"],
                "tier": ret["tier"],
                "age_days": ret["age_days"],
            }
        )
    stale_sources.sort(key=lambda x: (x["score"], x["source_id"]))
    top_stale = stale_sources[:30]

    # Render Markdown
    lines = [
        "---",
        'title: "Vault Dashboard"',
        "type: index",
        "tags:",
        "  - kb/dashboard",
        "  - kb/index",
        "---",
        "# Vault Dashboard",
        "",
        "Welcome to the human-oriented search and discovery interface for the living research vault. Use this page to browse and explore the curated evidence layer.",
        "",
        "## Quick Links",
        "- [[Indexes/Source_Atlas|Source Atlas]] — Grouped by year, kind, and evidence strength",
        "- [[Indexes/Topic_Atlas|Topic Atlas]] — Concept clusters grouped by tag",
        "- [[Indexes/Source_Registry|Source Registry]] — Flat tabular list of all sources",
        "- [[Indexes/Workflow_Atlas|Workflow Atlas]] — Active research and runbooks",
        "- [[TODO|TODO]] — Open tasks and maintenance queues",
        "",
        "## Freshness Alerts (Low Retention Score)",
        "These are the most stale or aging sources in the vault, sorted by their retention score (lowest first). They may require verification or updating.",
        "",
        "| Source ID | Title | Retention Score | Tier | Age (Days) |",
        "|---|---|---|---|---|",
    ]

    for s in top_stale:
        title_esc = str(s["title"]).replace("[", "").replace("]", "").replace("|", "-")
        if len(title_esc) > 60:
            title_esc = title_esc[:57] + "..."
        lines.append(
            f"| [[{s['relative_path']}|{s['source_id']}]] | {title_esc} | {s['score']:.4f} | {s['tier']} | {s['age_days']} |"
        )

    lines.append("")
    lines.append("## Browse by Source Title (Alphabetical Index)")
    lines.append("")

    sorted_letters = sorted(alpha_groups.keys())
    if "#" in sorted_letters:
        sorted_letters.remove("#")
        sorted_letters.append("#")

    links = [f"[[#Section {letter}|{letter}]]" for letter in sorted_letters]
    lines.append(" | ".join(links))
    lines.append("")

    for letter in sorted_letters:
        lines.append(f"### Section {letter}")
        lines.append("")
        lines.append(format_sources_list(alpha_groups[letter]))
        lines.append("")

    lines.append("## Browse by Author / Organization")
    lines.append("")
    sorted_authors = sorted(
        [(name, srcs) for name, srcs in author_groups.items() if name != "Unknown / Unspecified"],
        key=lambda x: (-len(x[1]), x[0]),
    )
    if "Unknown / Unspecified" in author_groups:
        sorted_authors.append(("Unknown / Unspecified", author_groups["Unknown / Unspecified"]))

    for name, srcs in sorted_authors[:40]:
        lines.append(f"### {name} ({len(srcs)} sources)")
        lines.append("")
        lines.append(format_sources_list(srcs))
        lines.append("")

    lines.append("## Browse by Publication Year")
    lines.append("")
    for year in sorted(year_groups.keys(), reverse=True):
        srcs = year_groups[year]
        lines.append(f"### {year} ({len(srcs)} sources)")
        lines.append("")
        lines.append(format_sources_list(srcs))
        lines.append("")

    lines.append("## Browse by Evidence Strength")
    lines.append("")
    for strength in sorted(strength_groups.keys(), key=lambda x: (-len(strength_groups[x]), x)):
        srcs = strength_groups[strength]
        lines.append(f"### {strength} ({len(srcs)} sources)")
        lines.append("")
        lines.append(format_sources_list(srcs))
        lines.append("")

    lines.append("## Browse by Topic Tag")
    lines.append("")
    for tag in sorted(tag_groups.keys()):
        srcs = tag_groups[tag]
        tag_heading = tag.replace("-", " ").replace("/", " ").title()
        lines.append(f"### {tag_heading} (`{tag}`) ({len(srcs)} sources)")
        lines.append("")
        lines.append(format_sources_list(srcs))
        lines.append("")

    lines.append("## Backlinks")
    lines.append("")
    lines.append("- [[Home]]")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def generate_okf_progressive_indexes():
    # 1. Generate notes/Concepts/index.md
    concepts_dir = CONFIG.concepts_dir
    concept_lines = ["# Concepts", "", "A curated layer of durable knowledge pages.", ""]
    for path in sorted(concepts_dir.glob("*.md")):
        if path.name == "index.md":
            continue
        try:
            fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            if fm.get("type") == "redirect":
                continue
            title = fm.get("title") or path.stem
            desc = fm.get("description") or "Durable concept page."
            concept_lines.append(f"* [{title}]({path.name}) - {desc}")
        except Exception:
            pass
    concepts_dir.joinpath("index.md").write_text("\n".join(concept_lines) + "\n", encoding="utf-8")
    print(f"Updated {concepts_dir / 'index.md'}")

    # 2. Generate notes/Sources/index.md
    sources_dir = CONFIG.summaries_dir
    source_lines = ["# Sources", "", "Normalised source evidence summaries.", ""]
    # Group by subdirectory name under notes/Sources
    subdirs = sorted([d for d in sources_dir.iterdir() if d.is_dir()])
    for subdir in subdirs:
        source_lines.append(f"## {subdir.name.capitalize()}")
        source_lines.append("")
        for path in sorted(subdir.glob("src-*.md")):
            try:
                fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
                title = fm.get("title") or path.stem
                desc = fm.get("description") or f"Source summary for {path.stem}."
                # OKF path is relative to the subdirectory's index
                source_lines.append(f"* [{path.stem}: {title}]({subdir.name}/{path.name}) - {desc}")
            except Exception:
                pass
        source_lines.append("")
    # Also flat sources directly under notes/Sources
    flat_sources = sorted(sources_dir.glob("src-*.md"))
    if flat_sources:
        source_lines.append("## General")
        source_lines.append("")
        for path in flat_sources:
            try:
                fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
                title = fm.get("title") or path.stem
                desc = fm.get("description") or f"Source summary for {path.stem}."
                source_lines.append(f"* [{path.stem}: {title}]({path.name}) - {desc}")
            except Exception:
                pass
        source_lines.append("")
    sources_dir.joinpath("index.md").write_text("\n".join(source_lines) + "\n", encoding="utf-8")
    print(f"Updated {sources_dir / 'index.md'}")

    # 3. Generate notes/Answers/index.md
    answers_dir = CONFIG.answers_dir
    answer_lines = ["# Answers", "", "Durable answer memos from Q&A runs.", ""]
    for path in sorted(answers_dir.glob("*.md")):
        if path.name == "index.md":
            continue
        try:
            fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            title = fm.get("title") or path.stem
            desc = fm.get("description") or "Grounded Q&A response memo."
            answer_lines.append(f"* [{title}]({path.name}) - {desc}")
        except Exception:
            pass
    answers_dir.joinpath("index.md").write_text("\n".join(answer_lines) + "\n", encoding="utf-8")
    print(f"Updated {answers_dir / 'index.md'}")

    # 4. Generate notes/Runbooks/index.md
    runbooks_dir = CONFIG.vault_dir / "Runbooks"
    if runbooks_dir.exists():
        runbook_lines = ["# Runbooks", "", "Operational runbooks and quick references.", ""]
        for path in sorted(runbooks_dir.glob("*.md")):
            if path.name == "index.md":
                continue
            try:
                fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
                title = fm.get("title") or path.stem
                desc = fm.get("description") or "K-Ops operational guide."
                runbook_lines.append(f"* [{title}]({path.name}) - {desc}")
            except Exception:
                pass
        runbooks_dir.joinpath("index.md").write_text(
            "\n".join(runbook_lines) + "\n", encoding="utf-8"
        )
        print(f"Updated {runbooks_dir / 'index.md'}")

    # 5. Generate notes/index.md (Bundle Root)
    root_lines = [
        "---",
        'okf_version: "0.1"',
        "---",
        "# K-Ops Knowledge Bundle",
        "",
        "A local, agent-first research vault for Obsidian and OKF.",
        "",
        "## Vault Sections",
        "",
        "* [Concepts](Concepts/) - Curated layer of durable concept pages",
        "* [Sources](Sources/) - Normalised source summaries and evidence links",
        "* [Answers](Answers/) - Durable answer memos from Q&A runs",
        "* [Runbooks](Runbooks/) - Operational guides and quick references",
        "* [Indexes](Indexes/) - Vault indexes, atlases, and dashboards",
    ]
    CONFIG.vault_dir.joinpath("index.md").write_text("\n".join(root_lines) + "\n", encoding="utf-8")
    print(f"Updated {CONFIG.vault_dir / 'index.md'}")


def main():
    sources = get_sources_data()
    concepts = get_concepts_data()

    # 1. Source Atlas
    source_atlas_path = CONFIG.indexes_dir / "Source_Atlas.md"
    source_atlas_content = generate_source_atlas_content(sources)
    source_atlas_path.write_text(source_atlas_content, encoding="utf-8")
    print(f"Updated {source_atlas_path}")

    # 2. Topic Atlas
    topic_atlas_path = CONFIG.indexes_dir / "Topic_Atlas.md"
    topic_atlas_content = generate_topic_atlas_content(concepts)
    topic_atlas_path.write_text(topic_atlas_content, encoding="utf-8")
    print(f"Updated {topic_atlas_path}")

    # 3. Source Registry
    source_registry_path = CONFIG.indexes_dir / "Source_Registry.md"
    source_registry_content = generate_source_registry_content()
    source_registry_path.write_text(source_registry_content, encoding="utf-8")
    print(f"Updated {source_registry_path}")

    # 4. Home Concepts
    home_content = generate_updated_home_content(concepts)
    CONFIG.home_note.write_text(home_content, encoding="utf-8")
    print(f"Updated {CONFIG.home_note}")

    # 5. Vault Dashboard
    vault_dashboard_path = CONFIG.indexes_dir / "Vault_Dashboard.md"
    vault_dashboard_content = generate_vault_dashboard_content(sources, concepts)
    vault_dashboard_path.write_text(vault_dashboard_content, encoding="utf-8")
    print(f"Updated {vault_dashboard_path}")

    # 6. OKF Progressive Indexes
    generate_okf_progressive_indexes()


if __name__ == "__main__":
    main()
