---
title: Torque Security and Stability
type: concept
claim_quality: provisional
evidence_status: synthesized
tags:
- kb/concept
- torque
---

# Torque Security and Stability

## What It Is

Known security and stability issues across Torque releases.

## Why It Matters

Running an affected version in production is unsafe until patched.

## Key Claims

- Advisory TQ-SA-2026-001 is a critical deserialization RCE (CVSS 9.1) affecting
  2.0.0-2.1.0, fixed in v2.1.1 ([[Sources/src-fac0000004|src-fac0000004]]).
- A memory leak in windowed aggregation (#812) is open on v2.1.0 and fixed in v2.1.1
  ([[Sources/src-fac0000003|src-fac0000003]], [[Sources/src-fac0000002|src-fac0000002]]).
- Recommendation: do not run 2.1.0 in production; upgrade to 2.1.1.

## Evidence / Source Basis

- Security: [[Sources/src-fac0000004|src-fac0000004]].
- Stability: [[Sources/src-fac0000003|src-fac0000003]], [[Sources/src-fac0000002|src-fac0000002]].

## Related Concepts

- [[Concepts/Torque_Project_Overview|Torque Project Overview]]

## Open Questions

- Whether other unreported vulnerabilities exist is unknown from the corpus.

## Backlinks

- [[Home]]
