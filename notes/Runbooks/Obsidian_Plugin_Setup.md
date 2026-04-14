---
title: "Obsidian Plugin Setup"
type: maintenance
tags:
  - kb/runbook
  - kb/obsidian
---

# Obsidian Plugin Setup

K-Ops uses frontmatter properties (`evidence_strength`, `claim_quality`, `answer_quality`) throughout the vault. The following community plugins unlock powerful querying and management of these properties inside Obsidian.

## Recommended Plugins

### 1. Dataview (Essential)

Enables SQL-like queries against frontmatter properties, making it possible to build dashboards directly inside the vault.

**Install:** Settings → Community Plugins → Browse → search "Dataview"

**Example queries to add to `notes/Home.md`:**

```dataview
TABLE claim_quality, file.mtime as "Updated"
FROM "notes/Concepts"
WHERE claim_quality != "supported"
SORT file.mtime DESC
```

```dataview
TABLE evidence_strength, file.mtime as "Ingested"
FROM "notes/Sources"
WHERE evidence_strength = "stub"
SORT file.mtime ASC
```

### 2. Templater (Recommended)

Provides dynamic templates with JavaScript capabilities. Use it to auto-fill `source_id`, timestamps, and other frontmatter fields when creating new notes from the templates in `notes/_Templates/`.

**Install:** Settings → Community Plugins → Browse → search "Templater"

**Setup:** Point Templater's template folder to `notes/_Templates`.

### 3. Tasks (Optional)

Enables task tracking across the vault using `- [ ]` syntax. Useful for tracking `notes/TODO.md` items inside Obsidian's task view.

**Install:** Settings → Community Plugins → Browse → search "Tasks"

### 4. Git (Optional)

Enables committing vault changes directly from Obsidian. Useful if you edit notes in Obsidian and want to keep git history without switching to a terminal.

**Install:** Settings → Community Plugins → Browse → search "Obsidian Git"

## Dataview Property Reference

| Property | Valid values | Appears on |
|---|---|---|
| `evidence_strength` | `primary-doc`, `secondary`, `strong`, `stub`, `image-only` | Source summaries (`notes/Sources/`) |
| `claim_quality` | `supported`, `provisional`, `weak`, `conflicting`, `stale` | Concept pages (`notes/Concepts/`) |
| `answer_quality` | `durable`, `memo-only` | Answer memos (`notes/Answers/`) |
| `scope` | `shared`, `private` | Answer memos |
| `type` | `source-summary`, `concept`, `answer`, `home`, etc. | All notes |

## Notes

- Community plugins require enabling "Community plugins" in Settings → Community plugins (toggle off Restricted Mode).
- Dataview queries work best with consistent frontmatter — run `lint` and `backfill-concept-quality` to normalize the vault before building dashboards.
