# Snapshot 03 — retraction / contradiction

Builds on 02 (keeps the v2.1.1 versioned source). New diff:

- `src-5ec0000016` (the 5M events/sec blog) is RETRACTED: `source_status: revoked` plus `retracted_at` and `retraction_reason`.
- Consequence: q-trap-03 must now REFUSE to cite the revoked source; the only surviving throughput figure is the vendor's 1.2M (src-fac0000007).
- The exactly-once and governance contradictions remain live.

`state.json` is the authoritative logical state; the `notes/Sources/*.md` files here override the corresponding files in `corpus/`.
