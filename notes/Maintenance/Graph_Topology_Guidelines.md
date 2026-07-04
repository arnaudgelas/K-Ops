# Graph Topology Guidelines

Derived from a degree audit conducted 2026-07-04 on the vault knowledge graph.
Expected topology per node type and the code invariants that enforce it.

## Expected topology

| Node type | Expected in-degree | Expected out-degree | Enforcement |
|---|---|---|---|
| source | low (evidence leaf) | 0 | `supported_by` edges from claims; no edges out |
| claim | 1 (single concept owner) | ≥1 (inline citations) | `has_claim` in; `supported_by` out |
| concept | bounded hub (~10–100) | balanced with in | `related_to`, `links_to`, `has_claim` |
| contradiction | 0 (no inbound) | 2 (both conflicting claims) | `conflicts_with` edges |
| answer | 0 (pure sink) | ≥1 (concept refs) | `mentions`/`updates` edges |
| index | low in | high out | `links_to` edges |
| tag | N/A (metadata, not a node) | N/A | deweighted in retrieval scoring |

## Invariants

1. **Claim ownership**: every claim has exactly 1 inbound `has_claim` edge from its concept.
2. **Claim evidence**: every claim has ≥1 outbound `supported_by` edge derived from **inline citations in that bullet**, not page-level Evidence section sources.
3. **`derived_from` direction**: claim→concept (backward nav); NOT used for source attribution.
4. **Contradiction cluster**: a contradiction node connects to exactly 2 claims via `conflicts_with` and to the owning concept via `involves_concept`.
5. **Source leaves**: sources have no outbound edges in the claim layer (only `supports_concept` from their Related Concepts section).
6. **Tag deweighting**: tags with membership > 10% of all nodes are structural type tags and must be penalized in retrieval BM25 scoring.

## Scorecard signals

The following signals must fire when invariants are violated:

- `orphaned-sources` (warning): > 50% of source nodes have in-degree 0 via `supported_by` edges.
- `isolated-concepts` (warning): any concept node has total degree 0.
- `isolated-answers` (info): any answer node has out-degree 0 (no concept mentions).
- `undocumented-contradictions` (warning): already exists; keep.

## Remediation

- Orphaned sources: run `ingest-sources` to compile them, then cite in concept Key Claims.
- Isolated concepts: add wikilinks to Related Concepts on the stub page.
- Isolated answers: add `## Vault Updates` section with concept wikilinks, or archive.
- `derived_from` pointing to source: rename to `supported_by` and fix graph builder.
