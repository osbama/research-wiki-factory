# Architecture — auto-LLMRAG

## Repository vs Runtime

| | Path | Purpose |
|---|---|---|
| Source (this repo) | `~/source/auto-LLMRAG/` | Canonical code, docs, plugin, skill, config template. Git-tracked. |
| Runtime (deployment) | `~/Prog/research-wiki-factory/` | Live wikis, inbox, bibs, embeddings, kanban state. NOT in git. |
| Profile integration | `~/.hermes/profiles/<profile>/` | Installed plugin + skill + cron jobs. |

Deploy with `source/deploy.sh <profile>` (rsync repo → runtime + profile).

## Runtime Layout

```
~/Prog/research-wiki-factory/
  wiki-factory.yaml          # live config (endpoints, topics, thresholds)
  scripts/                   # deployed copy of source/scripts/
  zotero/exports/wiki-<t>.bib  # Better BibTeX auto-export (READ-ONLY)
  candidates/<t>-new.bib     # sweep output, Zotero-importable
  inbox/<t>/                 # PDF drop dirs (recursive scan)
  state/                     # watcher lockfile + logs, sweep logs
  wikis/<t>/                 # llm-wiki per topic:
    SCHEMA.md index.md log.md
    raw/papers/ raw/_archive/ entities/ concepts/ comparisons/ queries/
    _meta/  (ingested-keys, seen-paperids, embeddings.npz+meta,
             withdraw-log, coverage-report)
  wikis/_master/             # cross-topic overview wiki
```

## Data Flow

```
Semantic Scholar ──s2_sweep──> candidates/<t>-new.bib + kanban cards
                                     │ (user imports, triages)
                       Zotero + Better BibTeX auto-export
                                     ▼
                     zotero/exports/wiki-<t>.bib  ──bibwatch──> ingest cards
                                     │                    (gate + kill switch)
              attanger PDFs → inbox/<t>/ ────────────────────────┘
                                     ▼
        ingest_paper → raw/papers/ + llm-wiki pages → embed_index
                                     ▼
   verify_page / coverage_audit / wiki_query_fallback (LiteLLM embeddings)
                                     ▼
                            master_sync → _master/
```

## Components

| Component | Type | Trigger |
|---|---|---|
| s2_sweep.py | script | daily Hermes cron (researcher profile) |
| bibwatch.py --watch | daemon | wiki-factory profile plugin (session lifecycle) |
| ingest_paper.py | script | worker claims kanban card |
| embed_index.py | library+CLI | hooked by ingest/withdraw/restore |
| verify_page.py / coverage_audit.py | scripts | on demand / weekly cron |
| wiki_query_fallback.py | script | on demand |
| withdraw.py / restore.py | scripts | watcher detects bib removal / manual |
| master_sync.py | script | weekly cron |
| backup.py / restore_backup.py | scripts | manual (transfer between machines) |
| wiki-factory plugin | Hermes plugin | profile session start/end |
| research-wiki-factory | skill | loaded by agents working the pipeline |

## File Formats

- `embeddings.npz`: single `vectors` float32 array, L2-normalized rows.
- `embeddings_meta.json`: list parallel to rows: `{citekey, chunk_id, text,
  source: "paper"|"wiki", withdrawn: bool}`.
- `ingested-keys.json`: `{keys, ingested_at{citekey:ts}, withdrawn[],
  withdrawals{}}`.
- `seen-paperids.json`: `{paperId: {first_seen, last_offered, offer_count,
  citation_count}}`.

## External Dependencies

- LiteLLM proxy serving `qwen3-embedding-8b` (OpenAI-compatible
  `/v1/embeddings`, no auth on the user's LAN).
- Semantic Scholar Graph API (key in profile .env).
- Zotero + Better BibTeX (auto-export per collection) + attanger.
- Hermes kanban CLI; watchfiles; numpy; pyyaml; requests; pdftotext.
