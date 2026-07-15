# K-Ops — Design Partner Brief (P0.1)

This document implements roadmap task [`P0.1`](ROADMAP.md) — *Choose one initial
user and corpus*. It records the initial wedge (target user + corpus) and the
recruitment plan for three to five design partners.

For what K-Ops does and how far the guarantees currently reach, see
[`docs/DESIGN.md`](DESIGN.md); for the governing backlog and the M0 exit gate,
see [`docs/ROADMAP.md`](ROADMAP.md).

> **Status of the M0 exit signal.** The exit gate requires that *at least three
> prospective users confirm that stale or unsupported conclusions are a
> meaningful problem*. That confirmation is an external, human activity. It is
> **PENDING** — no partner has been contacted or confirmed inside this
> repository. This document is the instrument for collecting those
> confirmations, not evidence that they exist. See
> [Confirmation ledger](#confirmation-ledger-pending).

---

## Part 1 — The initial wedge

### The chosen wedge

> **Technical and open-source project intelligence used for consequential
> product or investment decisions.**

Chosen because it lines up with what K-Ops already does rather than with what it
might one day do:

- **GitHub ingestion is a first-class path.** `add`/`ingest` route GitHub repo
  URLs to a repository-snapshot ingest that extracts key concepts,
  architectural decisions, and high-signal files — the raw material of a
  technical due-diligence read.
- **The corpus is public and text-first.** URLs, PDFs, repos, release notes, and
  blog posts are exactly the source types the deterministic layer normalizes
  into `data/raw/`, which suits K-Ops's grep-aligned, file-native bias.
- **The domain generates real contradictions and staleness.** Project claims
  (maintenance status, license, funding, security posture, benchmark numbers)
  change and conflict across sources — the conditions under which the
  contradiction registry, freshness flags, and `retract` blast-radius earn their
  keep.
- **The decision is consequential and reviewable.** "Should we depend on / adopt
  / invest in project X" is a decision a human already signs off on, so a
  governed, auditable answer has obvious value and a natural review step.

### The recurring research decision

The target user repeatedly answers a variant of:

> **"Is project X a safe thing to depend on, adopt, or invest in — and is that
> judgment still true today?"**

Concrete instances:

- *Adoption / dependency:* a staff engineer or architect deciding whether to
  build on an open-source library, framework, or infrastructure project (Is it
  actively maintained? Is the license compatible? Is there a single-maintainer
  bus-factor risk? Are there unresolved security advisories? Is the "production
  ready" claim in the README supported by anything?).
- *Investment / diligence:* an early-stage technical investor or a
  developer-tools scout assessing an open-source-first company or project (Is
  traction real or narrated? Are the growth numbers current? Do the funding,
  team, and roadmap claims corroborate across independent sources or trace back
  to one press release?).
- *Build-vs-adopt / vendor selection:* a platform or DevRel lead comparing two
  or three comparable projects and needing a defensible, sourced recommendation
  rather than a vibe.

The unit of work is a decision about **one project (or a small comparison set)**,
producing a recommendation someone else will rely on.

### The source corpus

Per project, the evidence set is bounded and public:

- the GitHub repository (README, docs, license, `CHANGELOG`, release notes,
  tags/releases cadence, contributor graph);
- issues and pull requests (open security issues, stale-bot activity,
  maintainer responsiveness, roadmap threads);
- project/product documentation sites and design docs;
- maintainer or company blog posts and engineering write-ups;
- funding / acquisition / milestone announcements (and the press coverage that
  repeats them);
- third-party commentary: benchmark posts, comparison articles, aggregator
  threads, model-generated summaries.

This corpus has the properties the M1 benchmark ([`E1.1`](ROADMAP.md)) needs:
primary vs secondary sources, multiple versions of the same source over time,
explicit contradictions, retractable/revocable sources, and derivative reporting
(the same announcement echoed by many outlets).

### Current workflow and tools

Today the user does this by hand:

1. Opens 15-40 browser tabs across GitHub, docs, blogs, and news.
2. Skims for signals (last commit date, release cadence, open critical issues,
   funding, license).
3. Copies fragments into a Google Doc, Notion page, or Slack thread — often
   pasting an LLM/NotebookLM summary of a repo or thread as if it were a source.
4. Writes a recommendation or diligence memo from memory and scattered notes.
5. Ships the memo; the tabs and the provenance are lost.

Tooling in use: browser + tabs, ad-hoc LLM chat (ChatGPT/Claude), NotebookLM,
GitHub search, spreadsheets, and a doc/wiki. None of these track *which claim an
answer relied on*, *whether the evidence still says that*, or *whether a source
was derivative or has since been retracted*.

### Known costly failures

These are the failure modes K-Ops is positioned to prevent, and the ones the
screening below must confirm are real for the candidate:

- **Stale conclusion.** The memo says "actively maintained" or "$X ARR growing
  fast," but the underlying repo went quiet or the number is a year old. The
  decision is made on evidence that has since moved.
- **Unsupported claim.** A confident sentence ("SOC 2 compliant," "used in
  production by N companies," "faster than Y") that no source in the corpus
  actually supports — it came from a summary, an assumption, or a hallucination.
- **Missed contradiction.** Two sources disagree (README vs issues on
  maintenance status; blog vs changelog on a feature; two benchmark posts) and
  the disagreement is silently averaged away instead of surfaced.
- **Missed retraction / revision.** A source that was corrected, deprecated, or
  withdrawn (a retracted benchmark, a walked-back claim, a deleted advisory)
  still underpins the conclusion.
- **Acting on a synthetic / derivative source.** Treating an AI summary of a
  repo, or five outlets repeating one press release, as independent
  corroboration — false confidence from a single upstream source.

Each of these can turn into a real, expensive mistake: adopting an abandoned
dependency, recommending a project with an unpatched CVE, or advising an
investment on narrated rather than corroborated traction.

### Acceptable review time per answer

- **Exploratory scan:** seconds to ~2 minutes. The user will not wait for a
  governed pipeline just to browse.
- **Recommendation-grade memo:** up to **5-10 minutes of review per answer** is
  acceptable *if* the output makes review cheaper than the manual read it
  replaces (i.e. it points at the exact claims and spans to check).
- **Decision- / diligence-grade answer:** up to **15-30 minutes** of review is
  acceptable for a memo someone will act on, because the manual alternative is
  hours and the downside of a wrong call is large.

The hard constraint: review time must stay **below the value of the errors it
prevents**. If K-Ops adds review overhead without preventing costly mistakes,
the user reverts to tabs. (This mirrors the roadmap stop condition "review time
exceeds the value of the prevented errors.")

### Required output format

- A **short recommendation / diligence memo** (roughly one page) with an
  explicit verdict or verdict-with-qualification, or an explicit abstention when
  evidence is insufficient.
- Every material claim **traceable to a source span**, not to a vibe — so a
  reviewer can jump from a sentence to the evidence.
- **Contradictions and freshness surfaced, not hidden**: "these two sources
  disagree," "this figure is N months old."
- A **declared consequence tier** (exploratory / recommendation / decision) so
  the reader knows what standard the answer was held to.
- **Markdown, file-native, reviewable in Git / Obsidian**, matching how K-Ops
  already writes answer memos into `notes/Answers/`.

### Stop conditions — what makes them abandon K-Ops

The wedge is only validated if the user keeps using it. They will stop if:

1. **It is slower than tabs without preventing errors** — governance overhead
   with no caught mistake.
2. **It produces confidently wrong or unsupported answers anyway** — a false
   "supported" defeats the entire pitch; trust does not survive one bad
   decision-grade answer.
3. **The review burden exceeds the value** — more minutes per answer than the
   mistakes are worth.
4. **Setup / ingestion friction is too high** — if getting a project's corpus in
   takes longer than reading it, they won't.
5. **It only offers generic search and chat** — if the governance (traceability,
   staleness, contradiction, retraction) is invisible or unused, they will use a
   cheaper general LLM instead. (Roadmap: "Users value generic search and chat
   but not governance.")
6. **Freshness/invalidation is unreliable** — if a source changes and the answer
   silently stays stale, the core promise is broken.

---

## Part 2 — Recruitment brief

### The ask

Recruit **3-5 design partners / rigorous pilot users** who make the decision
above for real and will run a handful of real projects through K-Ops, then tell
us the truth about whether it prevented anything.

### Ideal partner profile

Any one of:

- **Staff / principal engineer or architect** who owns dependency and
  build-vs-adopt decisions for a team.
- **Platform / DevEx / DevRel lead** who evaluates and recommends open-source
  tooling.
- **Early-stage technical investor, scout, or diligence analyst** covering
  developer tools / open-source / infrastructure.
- **Open-source program office (OSPO) or security/supply-chain reviewer** who
  vets third-party projects before adoption.

Qualifying traits:

- makes this kind of call **repeatedly** (not once a year);
- the decisions are **consequential** (a wrong call costs real money, time, or
  risk);
- works from **public, technical sources** (fits K-Ops's corpus);
- is **comfortable with Git / Markdown / CLI** (the current surface) and can
  tolerate an early tool;
- willing to **review outputs honestly**, including telling us when governance
  caught nothing.

### Where to find them

- open-source and platform-engineering communities (CNCF / Kubernetes SIGs,
  language ecosystems, DevOps and platform Slacks/Discords);
- OSPO networks and supply-chain-security groups;
- developer-tools investor and scout networks; angel/seed communities focused on
  infra and OSS;
- author networks around technical due-diligence, "state of X" reports, and
  project-comparison writing;
- direct outreach to people who publicly write adopt/avoid or comparison posts —
  they already do this work manually.

### The commitment we request

- one **45-60 minute intake interview** (guide below);
- run **3-5 real projects** through K-Ops over ~2-4 weeks;
- **one feedback session per cycle** (~30 minutes), ideally two cycles so we can
  measure return usage (ties to the M3 gate: "at least two return for a second
  research cycle");
- permission to record, anonymized, **which failures K-Ops caught or missed**.

In return: hands-on help with setup, direct influence on the roadmap, and their
real questions used as the seed for the benchmark corpus ([`E1.1`](ROADMAP.md)).

### Screening checklist — is the target failure meaningful?

This is the **M0 exit-gate signal**. A candidate counts as a confirmation only if
they answer *yes* to the core question and can give at least one concrete past
example. Do not infer confirmations; record them.

- [ ] Do they make the recurring decision (adopt / depend / invest / vendor-
      select on a technical project) **more than a few times a quarter**?
- [ ] **Core question:** Have **stale or unsupported conclusions** actually
      caused them a costly mistake or a scare? *(This is the exit-gate signal.)*
- [ ] Can they name a **specific past instance** (adopted an abandoned/insecure
      dependency, acted on an out-of-date number, trusted an unsupported claim,
      or mistook a derivative source for corroboration)?
- [ ] Do they currently have **no reliable way** to know which claim an answer
      relied on or whether it is still true?
- [ ] Is the decision **consequential enough** that 15-30 minutes of review is
      worth preventing the error?
- [ ] Are their sources **public and technical** (repos, docs, blogs,
      announcements)?

A candidate who cannot recall any stale/unsupported-conclusion pain is **not** a
valid confirmation for the M0 gate, however enthusiastic — the gate is about the
specific failure K-Ops exists to prevent.

### Interview guide

Ask these to fill in Part 1 for each candidate (they map one-to-one to the seven
documentation questions in [`P0.1`](ROADMAP.md)).

1. **Recurring decision.** "Walk me through the last time you had to decide
   whether to depend on, adopt, or invest in a technical/open-source project.
   How often does that come up?"
2. **Source corpus.** "When you assess a project, what do you actually read —
   which repos, docs, posts, announcements, threads? How do you know a source is
   trustworthy or current?"
3. **Current workflow and tools.** "Show me how you do it today, step by step.
   Where do the notes and the final recommendation live? Do you paste in LLM or
   NotebookLM summaries, and do you treat them as sources?"
4. **Costly failures.** "Tell me about a time a conclusion turned out to be wrong
   or out of date — a project you adopted that was abandoned or insecure, a
   number that had moved, a claim nothing actually supported. What did it cost?"
5. **Acceptable review time.** "For a recommendation someone will act on, how
   many minutes of checking are you willing to do — and what would make that
   checking feel worth it versus like busywork?"
6. **Required output.** "What does the deliverable look like — a memo, a slide, a
   Slack message? What has to be in it for someone else to trust and act on it?"
7. **Stop conditions.** "Imagine you tried a tool for this for two weeks. What
   would make you drop it and go back to browser tabs?"

Follow-ups to probe governance value specifically: "How would you find out today
if a source you cited last month has changed or been retracted?" and "Have you
ever been burned by several articles that all turned out to repeat one press
release?"

---

## Confirmation ledger (PENDING)

**Owner:** maintainer. **Status:** not started — 0 of 3 required confirmations.

This ledger records the external, human confirmations the M0 exit gate depends
on. Fill one row per screened candidate. A confirmation is valid only when the
screening core question is *yes* with a concrete example (see checklist).

| # | Candidate (role, not necessarily name) | Date screened | Recurring decision confirmed? | Stale/unsupported failure is meaningful? (core signal) | Concrete past example recorded? | Counts toward gate? |
|---|---|---|---|---|---|---|
| 1 | _pending_ | _pending_ | ☐ | ☐ | ☐ | ☐ |
| 2 | _pending_ | _pending_ | ☐ | ☐ | ☐ | ☐ |
| 3 | _pending_ | _pending_ | ☐ | ☐ | ☐ | ☐ |
| 4 (optional) | _pending_ | _pending_ | ☐ | ☐ | ☐ | ☐ |
| 5 (optional) | _pending_ | _pending_ | ☐ | ☐ | ☐ | ☐ |

**M0 exit-gate rule:** the gate's user-confirmation clause is satisfied only when
**at least three** rows have the core signal confirmed with a concrete example.
Do not mark the gate passed on the strength of this document alone.

### What is done vs pending

- **Done (in-repo):** the wedge is chosen and documented; the recurring
  decision, corpus, workflow, failure modes, review budget, output format, and
  stop conditions are specified; the recruitment profile, screening checklist,
  and interview guide are written.
- **Pending (external human action by the maintainer):** identify and contact
  candidates; run the screening interviews; record 3-5 confirmations in the
  ledger above. Until three valid confirmations exist, the M0 exit gate's
  user-confirmation clause is **not** met.
