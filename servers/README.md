# servers/ — Fleet-Change Documentation Protocol

## The Rule (R3)

Every modification to the local LLM fleet required by this project is:

1. **Proposed first** — what, why, exact config/commands, rollback path.
   The change is applied ONLY after the user's explicit confirmation.
2. **Documented after** — one file per applied change, named
   `YYYY-MM-DD-<short-slug>.md`, containing:
   - Date & motivation
   - Exact change applied (config diffs / commands)
   - Verification output (real command + real output)
   - Rollback instructions
   - Which pipeline component depends on it

## Index of Applied Changes

| Date | Change | Doc | Status |
|------|--------|-----|--------|
| — | (none applied by this project yet) | — | — |

## Existing Fleet Requirements (not changes — prerequisites)

These are pre-existing capabilities the pipeline RELY on. If your fleet
lacks them, provisioning one is a change that goes through the protocol above.

| Requirement | Used by | Notes |
|---|---|---|
| OpenAI-compatible `/v1/embeddings` serving `qwen3-embedding-8b` (4096-dim) | embed_index, verify_page, coverage_audit, wiki_query_fallback | Any LiteLLM/OpenAI-compatible server works; configure in `wiki-factory.yaml` |
| Semantic Scholar Graph API access (API key recommended) | s2_sweep | Key goes in the Hermes profile `.env` |
