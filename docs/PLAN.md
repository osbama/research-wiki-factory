# auto-LLMRAG — Approved Design Plan (v0.5, frozen 2026-07-22)

> Historical record of the design decisions. Amendments go in new dated
> sections at the bottom (Rule R4); this top section is frozen.

## Goal
A repeatable routine where each research topic gets: a Hermes kanban board,
an llm-wiki (Karpathy-style interlinked markdown KB), Semantic Scholar
literature discovery, Zotero as the human-in-the-loop curation gate, and
embedding-based verification (hallucination/coverage/query-fallback) served
by the user's local LiteLLM fleet. A master wiki links sub-wikis.

## Locked Decisions (from design dialogue)
1. One Better BibTeX auto-export per topic collection → `wiki-<topic>.bib`;
   the bib is the ONLY ingestion gate. Scripts never modify it.
2. BibTeX (not RIS) everywhere; candidates bib pre-filtered against all
   topic bibs so Zotero import creates no duplicates.
3. attanger naming: `<FirstCreator> - <Year> - <Title truncate=100>.pdf`
   (spaces preserved); bib `file` field basename is the primary PDF matcher.
4. Rejected candidates may be re-offered (30-day window, 2x-citation reset).
5. Withdrawal is soft/reversible: files to `_archive/`, embedding rows
   flagged (excluded from search), one-command restore.
6. Embeddings: `qwen3-embedding-8b` via LiteLLM proxy, 4096-dim; flat
   per-topic `.npz` cache (≤10 topics × ~100 papers — no vector DB needed).
7. Candidate cards stay on the kanban board; auto-complete when the citekey
   appears in a bib.
8. Citation chase from seed citekeys: 1 hop, top-25/seed/sweep, plus S2
   recommendations. Newly imported papers become next sweep's seeds
   (organic snowballing through the user's curation gate).
9. Watcher (not cron) for the bib/inbox gate, scoped to the `researcher`
   Hermes profile via a profile plugin (on_session_start/end, refcounted).
10. Sweeps + audits via Hermes cron under the researcher profile,
    deliver=local only.
11. Thresholds start at 0.65 (support) / 0.60 (coverage) / 0.75 (wiki hit);
    tune after first real audit.
12. S2 API key deferred at design time (later added to profile .env).

## Pipeline Stages
A. Daily sweep: S2 citations ∪ recommendations → filter → candidates bib +
   kanban cards.
B. User triage in Zotero: import candidates bib → staging; attanger fetches
   PDFs; drag keepers into topic collection → Better BibTeX re-export.
C. Watcher: bib diff vs ledger → match PDF (file-field → attanger → fuzzy)
   → ingest / waiting-pdf / withdraw cards.
D. Ingest (worker claims card): re-check bib → raw/papers/ + pdftotext →
   llm-wiki pages (orient → entities/concepts → ≥2 wikilinks → index/log)
   → embed chunks → ledger.
E. Verification: claim-level support check; coverage audit; query fallback.
F. Weekly master sync: structure/stats only, prose synthesis on top.

## Amendments

### 2026-07-23 — Project governance added
Project moved to `~/source/auto-LLMRAG` (git). Rules R1-R6 adopted:
canonical source in `source/` (deployments are copies), conventional
commits with tests green, fleet changes user-confirmed + documented in
`servers/`, docs updated with code, no host specifics or secrets in
source, semver + tagged zip builds. License: GPL.

### 2026-07-23 (later) — Deployment root moved; deploy-first workflow (R7)
- Runtime root moved from `~/research` to `~/Prog/research-wiki-factory`.
  All runtime data (scripts, wikis, inbox, zotero exports, candidates,
  state) lives under that single directory. `wf_common.get_research_root()`
  resolves it: env `WIKI_FACTORY_ROOT` overrides the default.
- R7 (deploy-first workflow): new changes are implemented in the
  deployment directory first, tested there, and only after explicit user
  confirmation are they sanitized and committed to the source repo.

### 2026-07-23 (later still) — Backup & transfer feature
- backup.py / restore_backup.py: portable tar.gz backups of deployment
  artifacts (never scripts, never secrets), sha256 manifest, timestamp
  rule (newer local state aborts restore; --force overrides), traversal
  and secret-pattern rejection. Live-tested with an 11-case battery
  including crafted evil archives.


### 2026-07-23 (hand-off) — Agent hand-off instrumentation adopted
- docs/RULES.md, docs/ONBOARDING.md, docs/CONTENTS.md added, modeled on
  the learn_and_teach repo conventions: standalone binding rules,
  paste-ready onboarding prompt, repo map. New rules adopted beyond the
  original R1-R7: no emojis anywhere; secrets scan before AND after
  every commit; push to origin master covered by commit approval;
  ONBOARDING/CONTENTS updated in the same commit as feature changes;
  agent pauses for confirmation before new components.
