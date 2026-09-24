# Repository Contents — research-wiki-factory

## Layout

    .
    |-- README.md                  overview and doc map
    |-- LICENSE                    GPL-3.0
    |-- VERSION                    semver (1.0.0)
    |-- .gitignore                 runtime artifacts, secrets, user data
    |-- docs/
    |   |-- RULES.md               binding working rules (read first)
    |   |-- ONBOARDING.md          paste-ready prompt + design goals
    |   |-- OVERVIEW.md            what it does, how, daily workflow
    |   |-- PLAN.md                design decisions, frozen + amendments
    |   |-- ALGORITHMS.md          how each component works
    |   |-- ARCHITECTURE.md        layout, data flow, file formats
    |   |-- CONTENTS.md            this file
    |-- servers/
    |   |-- README.md              fleet-change protocol + requirements
    |-- source/
        |-- INSTALL.md             user-side installation instructions
        |-- deploy.sh              repo -> deployment + profile installer
        |-- wiki-factory.yaml      config template (placeholders)
        |-- plugin/wiki-factory/   Hermes profile plugin (watcher lifecycle)
        |-- skill/SKILL.md         research-wiki-factory skill
        |-- scripts/
            |-- wf_common.py       config, S2 client, bib parser, matchers,
            |                      get_research_root()
            |-- wf_init.py         topic dirs + kanban board scaffolding
            |-- s2_sweep.py        S2 citation chase + recommendations ->
            |                      candidates bib + kanban cards
            |-- bibwatch.py        bib/inbox watcher -> ingest/waiting cards
            |-- ingest_paper.py    PDF -> raw/papers + note + ledger + embed
            |-- embed_index.py     embedding cache (npz + meta, add/remove/
            |                      restore/status)
            |-- verify_page.py     per-claim support check vs embeddings
            |-- coverage_audit.py  corpus-vs-wiki gap report
            |-- wiki_query_fallback.py  wiki-first Q&A, corpus fallback
            |-- withdraw.py        soft-archive a paper (+embedding flag)
            |-- restore.py         undo a paper withdrawal
            |-- master_sync.py     cross-topic master wiki (stats only)
            |-- backup.py          timestamped tar.gz of artifacts
            |                      (sha256 manifest, no code, no secrets)
            |-- restore_backup.py  validate + install a backup
            |                      (timestamp rule, --force override)
            |-- test_wf_common.py  15 unit tests (unittest, standalone)

## Runtime layout (deployment dir, not committed)

    DEPLOY_DIR/ (default ~/Prog/research-wiki-factory)
    |-- wiki-factory.yaml        live config (endpoints, topics, thresholds)
    |-- scripts/                 deployed copy of source/scripts/
    |-- zotero/exports/          Better BibTeX auto-exports (READ-ONLY)
    |-- candidates/              sweep output bibs for Zotero import
    |-- inbox/<topic>/           attanger-renamed PDFs (recursive scan)
    |-- state/                   watcher lockfile + logs, sweep logs
    |-- backups/                 backup-*.tar.gz archives
    |-- wikis/<topic>/           llm-wiki per topic:
    |   |-- SCHEMA.md index.md log.md
    |   |-- raw/papers/ raw/_archive/
    |   |-- entities/ concepts/ comparisons/ queries/
    |   |-- _meta/               ledgers, embeddings.npz+meta, reports
    |-- wikis/_master/           cross-topic overview wiki

## Dependencies

Python 3 (stdlib + numpy + PyYAML + requests + watchfiles), poppler-utils
(pdftotext), git, Hermes Agent with a dedicated profile. External services:
Semantic Scholar Graph API (key recommended), an OpenAI-compatible
embeddings endpoint (e.g. LiteLLM serving qwen3-embedding-8b). Desktop
side: Zotero + Better BibTeX + attanger. Secrets via environment only:
SEMANTIC_SCHOLAR_API_KEY, optional LITELLM_API_KEY.
