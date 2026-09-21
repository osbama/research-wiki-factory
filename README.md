# auto-LLMRAG

Zotero-gated research wiki pipeline for Hermes Agent: Semantic Scholar
literature discovery → human curation in Zotero (Better BibTeX + attanger)
→ automated ingest into Karpathy-style LLM wikis → embedding-based
verification (hallucination check, coverage audit, query fallback) on a
local LiteLLM embedding server. Cross-topic master wiki included.

License: GPL-3.0-or-later. See LICENSE.

- docs/OVERVIEW.md — start here: what it does, how, and the daily workflow
- docs/ALGORITHMS.md — how every component works
- docs/PLAN.md — approved design decisions
- docs/ARCHITECTURE.md — layout, data flow, formats
- source/INSTALL.md — installation instructions
- source/deploy.sh — one-command deployment to a Hermes profile
- servers/ — fleet-change documentation protocol
