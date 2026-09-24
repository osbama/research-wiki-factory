# Algorithms — auto-LLMRAG

This document describes every algorithmic component of the pipeline. It is
updated in the same commit as any behavioral change (Rule R4).

## 1. Literature Sweep (`s2_sweep.py`)

Goal: surface new candidate papers for a topic, seeded from the user's
existing curated library.

1. Load the topic's Zotero export (`wiki-<topic>.bib`) → seed citekeys.
2. Resolve each citekey to a Semantic Scholar paperId:
   DOI field → direct; arXiv eprint → `ARXIV:<id>`; else title search (first hit).
3. Expand:
   - Citation chase: `GET /paper/{id}/citations` (paginated, limit=1000),
     ranked by citationCount desc, capped at `per_seed_citation_cap` (25) per seed.
   - Recommendations: `POST /recommendations/v1/papers/` with the seed set as positives.
4. Filter a candidate OUT if:
   - its DOI/normalized-title+year matches any entry in any topic bib, or
   - it was offered within 30 days AND its citation count has not at least
     doubled since the last offer (tracked in `_meta/seen-paperids.json`).
5. Emit survivors: rebuild `candidates/<topic>-new.bib` (valid BibTeX, braces
   escaped; `note = {S2:<paperId>}`) + one kanban card per paper
   (idempotency `s2:<paperId>`).

Re-offer rationale: a rejected/ignored paper is never permanently suppressed;
it re-enters consideration at most monthly and only with fresh signal.

## 2. The Gate: Bib Diff (`bibwatch.py`)

Goal: only papers the user moved into the Zotero collection get ingested.

1. Parse the bib → citekey set.
2. pending = bib keys − ingested ledger (`_meta/ingested-keys.json`).
3. removed = ledger keys − bib keys → withdraw cards (see §6).
4. For each pending key, locate its PDF (see §3) → `ingest:` card;
   not found → `waiting-pdf:` card (idempotency `bib:<citekey>`).
5. Watch mode polls the bib via watchfiles; one-shot mode for cron/manual.

## 3. PDF↔Citekey Matching

Precedence (first hit wins), searched recursively under the topic inbox:

1. Bib `file` field: strip Zotero absolute path to basename (handle
   `path.pdf:application/pdf` and `;`-separated lists) → exact filename match.
2. Rename-template reconstruction: the configured Zotero 7 template
   (`attanger_pattern.rename_template`, default
   `{{ firstCreator suffix=" - " }}{{ year suffix=" - " }}{{ title truncate="100" }}`)
   is rendered against the bib entry and compared. The renderer supports
   the documented syntax (variables, case modes, affixes, truncate/start,
   replace, if/elseif/else conditionals; an empty variable drops the
   whole statement including affixes). firstCreator follows Zotero
   semantics: 1 author -> A, 2 -> A and B, 3+ -> A et al. Spaces are
   preserved; only filename-illegal chars are stripped.
3. Fuzzy: citekey substring in filename.

Ambiguity guard: two fuzzy candidates within 0.05 similarity → no auto-match;
a waiting-pdf card is created instead. The bib is also a kill switch: a worker
claiming an ingest card must re-verify the citekey is still in the bib.

## 4. Ingest (`ingest_paper.py` + `embed_index.py`)

1. Copy PDF → `wikis/<topic>/raw/papers/<citekey>.pdf` (immutable).
2. `pdftotext` → text is sanitized against prompt injection before any
   page is written: lines matching instruction-attack patterns
   ("ignore previous instructions", role hijacks, system-prompt probes,
   tool-call tokens, markdown image exfil URLs, AI-reviewer manipulation)
   are wrapped in a visible `[POSSIBLE INJECTION NEUTRALIZED]` marker —
   never deleted (auditable, reversible). The count lands in the note
   frontmatter (`injection_spans_neutralized`) and the ingest log.
   Notes carry `trusted: false` and a SECURITY NOTE header; query
   result pages carry the same header above quoted evidence, and
   snippets are backtick-escaped. Untrusted document text must never be
   followed as instructions by any agent reading the wiki.
3. Ledger update + chunking: ~500-token overlapping chunks.
4. Embed chunks via LiteLLM `/v1/embeddings` (batch ≤32, 3 retries w/ backoff).
   Documents embedded raw; queries use the Qwen3 instruction prefix:
   `Instruct: Given a research question, retrieve relevant passages that
   answer the question\nQuery: `.
5. Store: `_meta/embeddings.npz` (float32, L2-normalized rows → cosine =
   matmul) + `embeddings_meta.json` (parallel rows: citekey, chunk_id, text,
   source: paper|wiki, withdrawn flag).

## 5. Verification & Coverage (embedding server as oracle)

Hallucination check (`verify_page.py`):
- Split page into claim units (paragraphs/list items; skip frontmatter,
  headings, prior reports).
- Embed each as a query; max cosine vs ACTIVE paper chunks.
- Below `support_threshold` (0.65) → unsupported. Report written between
  `<!-- verify-report -->` markers (idempotent); `confidence: low` set;
  kanban card with content-addressed idempotency
  `verify:<topic>:<page>:<sha1(body)>` (edits re-trigger, unchanged pages don't).

Coverage audit (`coverage_audit.py`):
- Wiki paragraphs are also embedded (source="wiki", citekey="wiki:<page>").
- Active paper chunk with max wiki-similarity below `coverage_threshold`
  (0.60) = uncovered. Papers >30% uncovered → report + daily-deduped card.

Query fallback (`wiki_query_fallback.py`):
- Embed question. Wiki hit ≥0.75 → answer from wiki (exit 0).
- Else top-5 paper chunks → `queries/<slug>.md` draft with sources (exit 2).

Limits: cosine similarity detects UNSUPPORTED claims and coverage gaps; it
cannot detect claims CONTRADICTED by a well-matching source. Contradiction
handling remains an LLM/human lint responsibility.

## 6. Withdrawal (soft, reversible)

`withdraw.py`: PDF+md → `raw/_archive/<citekey>/`; embedding rows flagged
`withdrawn: true` (excluded from all searches, kept on disk); ledger status;
withdraw-log entry. `restore.py` reverses everything. Rationale: withdrawn
papers must not validate wiki claims, but restoration must be instant.

## 7. Master Wiki (`master_sync.py`)

Structure-only sync (no LLM prose): per topic, parse index.md + last 30
log.md lines → `_master/concepts/<topic>.md` (page counts, recent activity,
links to 5 newest pages) + `_master/index.md` + log. Synthesis prose is a
human/agent task layered on top.

## 8. Backup & Transfer (`backup.py` / `restore_backup.py`)

Goal: a deployment's artifacts must be portable to another machine.

Backup (`backup.py`):
1. Collects wiki-factory.yaml + wikis/, candidates/, zotero/, inbox/, state/
   (the irreplaceable human-curated data). Scripts are EXCLUDED — code comes
   from the source repo via deploy.sh on the target machine.
2. Secret hygiene: files matching secret patterns (.env/.key/credentials/
   secret/token/api_key) are skipped and reported, never archived.
3. Every file is sha256-hashed into an embedded backup-manifest.json
   (format, version, created_at, epoch, host, file list).
4. Output: backups/backup-YYYYmmdd-HHMMSS.tar.gz.

Restore (`restore_backup.py <file.tar.gz>`):
1. Validation chain: gzip tar → manifest present → format check →
   per-file sha256 → path-traversal guard → secret-pattern refusal.
   Any failure rejects the whole archive (exit 1).
2. Timestamp rule: if the LOCAL deployment's newest artifact is newer than
   the backup's epoch, restore aborts (newer state is never silently
   overwritten). --force overrides with a warning.
3. Extraction is confined to the deployment root; scripts/ is untouched.
4. Named restore_backup.py to avoid collision with paper-level restore.py.

Portability flow: backup on machine A → copy tar.gz to machine B →
deploy scripts from the repo → restore_backup.py → re-point Zotero
exports; keys/credentials are provisioned on B separately, never
transferred.
