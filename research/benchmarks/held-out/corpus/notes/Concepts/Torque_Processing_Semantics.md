---
title: Torque Processing Semantics
type: concept
claim_quality: conflicting
evidence_status: contested
tags:
- kb/concept
- torque
---

# Torque Processing Semantics

## What It Is

Whether Torque delivers true exactly-once processing.

## Why It Matters

Exactly-once vs at-least-once changes correctness guarantees for downstream systems.

## Key Claims

- Vendor release notes claim exactly-once for windowed aggregations, enabled by
  `processing.guarantee = exactly_once` in `torque.toml` ([[Sources/src-fac0000001|src-fac0000001]]).
- A community thread disputes this, arguing it is at-least-once plus deduplication ([[Sources/src-5ec0000014|src-5ec0000014]]).
- This is an unresolved CONTRADICTION between a primary vendor claim and community commentary.

## Evidence / Source Basis

- Vendor claim: [[Sources/src-fac0000001|src-fac0000001]].
- Dispute: [[Sources/src-5ec0000014|src-5ec0000014]].

## Related Concepts

- [[Concepts/Torque_Project_Overview|Torque Project Overview]]

## Open Questions

- No neutral third-party test of the end-to-end exactly-once guarantee exists in the corpus.

## Backlinks

- [[Home]]
