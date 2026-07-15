# Snapshot 02 — source-update

Diff from 01: the versioned source `src-fac0000002` changes from the v2.1.0 release notes to the v2.1.1 release notes.

- content_hash: `23488f41aa` (v2.1.0) -> `aab20eb443` (v2.1.1).
- Claim support flips: the memory leak (#812) is now FIXED and the RCE is patched.
- Freshness answers change: latest release becomes v2.1.1; #812 becomes fixed.

Apply by replacing `corpus/notes/Sources/src-fac0000002.md` with `notes/Sources/src-fac0000002.md` from this snapshot. `state.json` is the authoritative logical state.
