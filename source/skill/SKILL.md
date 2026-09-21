---
name: research-wiki-factory
description: "Zotero-gated research wiki pipeline: S2 literature sweep, bib watcher, PDF ingest, embedding verification, master wiki sync."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [research, wiki, zotero, semantic-scholar, embeddings, kanban]
    category: research
    related_skills: [llm-wiki, semantic-scholar]
---

# Research Wiki Factory

Operate the Zotero-gated research wiki pipeline at `~/research/`.

**Core invariant:** nothing enters a topic wiki unless its citekey is present
in that topic's Zotero Better BibTeX export (`~/research/zotero/exports/wiki-<topic>.bib`).
The user curates in Zotero; the pipeline reacts.

## Layout

```
~/research/
  wiki-factory.yaml          # topics (mapping), litellm, s2, attanger config
  scripts/                   # all pipeline scripts (system python3)
  zotero/exports/wiki-<topic>.bib   # Better BibTeX auto-export (READ-ONLY)
  inbox/<topic>/             # PDF drop folder (recursively scanned)
  wikis/<topic>/             # llm-wiki layout (SCHEMA/index/log/raw/entities/...)
  wikis/_master/             # cross-topic overview wiki
  state/                     # watcher lockfile + logs (bibwatch.json, bibwatch-<topic>.log)
```

## Components

| Script | Purpose | Key invocations |
|--------|---------|-----------------|
| `wf_init.py <topic>` | Create wiki dirs + kanban board `wiki-<topic>` | once per new topic |
| `s2_sweep.py <topic>` | S2 citation chase (top-25/seed) + recommendations → `candidates/<topic>-new.bib` + kanban candidate cards | daily (cron) |
| `bibwatch.py <topic> [--watch]` | Bib diff → ingest/waiting-pdf cards; `--watch` runs continuously (plugin-managed) | auto via plugin |
| `ingest_paper.py <topic> <citekey>` | PDF → raw/papers/, extract text, note stub, ledger, auto-embed | per paper |
| `embed_index.py --topic <t> <cmd>` | Embedding cache ops | `add-paper`, `remove-paper`, `restore-paper`, `status` |
| `verify_page.py --topic <t> --page <path>` | Claim-level support check vs embeddings; flags `confidence: low` + kanban card | on demand |
| `coverage_audit.py --topic <t>` | Corpus-vs-wiki gap report + card | weekly |
| `wiki_query_fallback.py --topic <t> --question "<q>"` | Wiki-first Q&A, corpus fallback | on demand |
| `withdraw.py <topic> <citekey>` / `restore.py <topic> <citekey>` | Soft-archive (reversible) + embedding flag | on Zotero removal |
| `master_sync.py` | Rebuild `_master/` overview from topic indexes/logs | weekly (cron) |

## Embeddings

- Endpoint: `http://localhost:4000/v1/embeddings (or your LiteLLM proxy)`, model `qwen3-embedding-8b`
  (4096-dim, no auth). Documents embedded raw; queries get the Qwen3
  instruction prefix (see `embed_index.py`).
- Cache: `wikis/<topic>/_meta/embeddings.npz` + `embeddings_meta.json`.
  Withdrawn papers stay on disk but `withdrawn: true` excludes them from all
  similarity searches (soft-delete, reversible).

## Thresholds (wiki-factory.yaml `verify:` section; tune after first real audit)

- `support_threshold: 0.65` — claim below this vs all sources = unsupported
- `coverage_threshold: 0.60` — paper chunk below this vs all wiki pages = uncovered
- Query fallback wiki-hit threshold: 0.75

## Environment

- `SEMANTIC_SCHOLAR_API_KEY` — in the researcher profile's `.env`. Without it
  s2_sweep still runs but hits 429 backoff frequently.

## Watcher lifecycle (wiki-factory plugin)

The `wiki-factory` plugin (profile-scoped) starts `bibwatch.py --watch` for
every configured topic when the first researcher session starts and stops them
when the last session ends. State: `~/research/state/bibwatch.json`.
Check watcher health: `tail ~/research/state/bibwatch-<topic>.log`.

## Pitfalls

- NEVER edit `zotero/exports/wiki-<topic>.bib` from scripts — Zotero owns it.
- Matching precedence: bib `file` field basename > attanger pattern (spaces
  preserved) > fuzzy citekey-in-filename. Ambiguous fuzzy matches must not
  auto-ingest — they surface as waiting-pdf cards.
- Idempotency keys: `bib:<citekey>`, `s2:<paperId>`, `verify:<topic>:<page>:<sha1>`,
  `coverage:<topic>:<YYYY-MM-DD>` — safe to re-run everything.
- If a kanban card's citekey has vanished from the bib before a worker claims
  it, the worker must abort (bib is the kill switch).
