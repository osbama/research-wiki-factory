# auto-LLMRAG — Project Overview

**What it is:** a self-hosted research pipeline that turns a pile of PDFs
into a living, verified knowledge base. It watches your Zotero library,
and every paper you approve flows automatically into a topic wiki whose
claims are continuously checked against the source papers by a local
embedding model.

**The one-sentence loop:**
Semantic Scholar suggests papers → you curate them in Zotero → approved
papers are ingested into a structured wiki → a local embedding server
verifies what the wiki says against what the papers actually say.

---

## 1. The Problem It Solves

Reading groups and literature reviews decay: notes scatter, summaries
hallucinate details, new papers pile up unread, and nobody remembers why
a claim was made. auto-LLMRAG addresses all four failure modes:

| Failure | Countermeasure |
|---|---|
| Scattered notes | One interlinked markdown wiki per topic (entities, concepts, queries), plus a master wiki across topics |
| Hallucinated summaries | Every wiki claim is embedding-matched against the ingested papers; unsupported claims are flagged automatically |
| Paper backlog | Daily Semantic Scholar sweep (citation chase + recommendations) delivers a pre-filtered candidate list |
| Lost provenance | Every wiki page cites its sources by citekey; withdrawing a paper from Zotero flags everything it supported |

## 2. Who Does What

```
┌─────────────────────────────────────────────────────────────┐
│  YOU (human)          │  MACHINES (automated)               │
├─────────────────────────────────────────────────────────────┤
│  Curate in Zotero     │  Suggest papers (Semantic Scholar)  │
│  (the ONLY gate)      │  Watch for approvals (bib watcher)  │
│  Read kanban board    │  Ingest PDFs into wikis             │
│  Review flagged pages │  Verify claims vs sources           │
│  Write synthesis      │  Audit coverage, sync master wiki   │
└─────────────────────────────────────────────────────────────┘
```

The design principle: **machines propose and verify; the human disposes.**
Nothing enters a wiki unless you moved the paper into a Zotero collection.

## 3. End-to-End Data Flow

```
                 ┌────────────────────────┐
                 │   Semantic Scholar API  │
                 └───────────┬─────────────┘
            citations + recommendations (daily sweep)
                             ▼
              candidates/<topic>-new.bib  +  kanban cards
                             │
                     ═══ HUMAN GATE ═══
                     │  import to Zotero,  │
                     │  drag keepers into  │
                     │  topic collection   │
                     ══════════════════════
                             ▼
        Better BibTeX auto-export → wiki-<topic>.bib   (read-only gate)
        attanger → renamed PDFs → inbox/<topic>/       (recursively scanned)
                             ▼
              bibwatch (profile plugin, runs with Hermes)
              bib diff → match PDF → kanban ingest cards
                             ▼
              ingest_paper: raw/papers/ + pdftotext + wiki pages
                             ▼
              embed_index (LiteLLM: qwen3-embedding-8b, 4096-dim)
                             ▼
        ┌──────────────┬──────────────┬────────────────┐
        ▼              ▼              ▼                ▼
   verify_page   coverage_audit   query_fallback   withdraw/restore
   (per-claim    (missing-info    (wiki-first Q&A, (soft-delete,
    support)      report)          corpus backup)   reversible)
                             ▼
                    master_sync → _master/ wiki
```

## 4. The Verification Model (honest version)

The embedding server is a **similarity oracle**, not a fact checker:

- **Hallucination check:** each wiki claim is embedded and compared
  against all chunks of all ingested papers. No similar source passage
  → claim flagged `unsupported`, page gets `confidence: low`, and a
  kanban card asks for review.
- **Coverage audit:** every paper chunk is compared against the wiki.
  Chunks nothing in the wiki covers → "missing information" report.
- **Query fallback:** ask a question; if the wiki can't answer it, the
  corpus is searched directly and the evidence is filed as a draft page
  so the gap closes permanently.

**What it cannot do:** detect a claim that is *contradicted* by a
well-matching source (similarity finds support, not contradiction), and
judge quality of support at threshold boundaries. Those remain human /
LLM-lint tasks. Thresholds (0.65 support / 0.60 coverage / 0.75 wiki-hit)
are starting points, tuned after the first real audit.

## 5. How to Use It (10-minute version)

Full instructions: `source/INSTALL.md`. The daily rhythm after setup:

1. **Morning:** check the kanban board for new candidate cards
   (`hermes -p <profile> kanban --board wiki-<topic> list`).
2. **In Zotero:** import `~/Prog/research-wiki-factory/candidates/<topic>-new.bib`,
   drag keepers into the topic collection. Attanger downloads and
   renames PDFs automatically.
3. **That's it.** While any session of the profile is open, the watcher
   notices the bib change, finds the PDF, and queues ingestion. Wiki
   pages, embeddings, and the ledger update themselves.
4. **Weekly-ish:** skim `verify:` and `coverage-audit:` cards on the
   board — those are the pipeline telling you where the wiki is weak.
5. **Changed your mind?** Remove the entry from the Zotero collection;
   the paper is soft-withdrawn (files archived, embeddings excluded,
   citing pages flagged) and can be restored with one command.
6. **Moving machines?** `backup.py` packs the deployment into a
   timestamped, secret-free tar.gz; `restore_backup.py` validates and
   installs it on the new machine (see INSTALL.md §8).

## 6. Required API Keys & Accounts

Everything below is **to be filled by the user**. The repo contains no
credentials — scripts read them from environment variables or the config
file at runtime.

| # | Credential / Account | Required? | Where it goes | What it's for |
|---|---|---|---|---|
| 1 | **Semantic Scholar API key** (free: https://www.semanticscholar.org/product/api#api-key-form) | Recommended — without it the sweep works but hits aggressive rate limits (429s) | `SEMANTIC_SCHOLAR_API_KEY` in `~/.hermes/profiles/<profile>/.env` | Literature sweep: citation chase + recommendations |
| 2 | **Embedding endpoint** (OpenAI-compatible `/v1/embeddings`; e.g. LiteLLM proxy serving `qwen3-embedding-8b`) | Required | `litellm.base_url` + `litellm.embedding_model` in `~/Prog/research-wiki-factory/wiki-factory.yaml` | All verification: hallucination check, coverage audit, query fallback |
| 3 | **Embedding endpoint auth** (if your server needs a key) | Only if your endpoint requires it | `litellm.api_key` in `~/Prog/research-wiki-factory/wiki-factory.yaml` (or env `LITELLM_API_KEY`) | Same as above |
| 4 | **Zotero + Better BibTeX + attanger** (desktop apps/plugins, not API keys) | Required | Installed and configured by the user (see INSTALL.md §4) | The curation gate and PDF fetching/renaming |
| 5 | **LLM provider for Hermes itself** (e.g. OpenRouter key) | Required by Hermes, not this project | Standard Hermes profile setup | Running the agents/workers that process kanban cards |

No cloud accounts are otherwise needed. All wiki data stays local;
Semantic Scholar is the only external API called.

## 7. Where Things Live

```
~/source/auto-LLMRAG/     ← this repo (code + docs, git-tracked)
~/Prog/research-wiki-factory/               ← runtime: wikis, inbox, bibs, embeddings
~/.hermes/profiles/<p>/   ← installed plugin, skill, cron jobs
```

| To read about... | See |
|---|---|
| Component algorithms | `docs/ALGORITHMS.md` |
| Design decisions & rationale | `docs/PLAN.md` |
| Layout, data flow, file formats | `docs/ARCHITECTURE.md` |
| Installation | `source/INSTALL.md` |
| Fleet-change protocol | `servers/README.md` |
