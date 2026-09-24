# Working Rules — research-wiki-factory Project

Agreed conventions between the user and the Hermes agent for building,
testing, and documenting this project. These rules override agent defaults.

## Roles of the directories

- Source (canonical, transferable, git-versioned): the repository at
  `~/source/auto-LLMRAG` (origin: github.com/osbama/research-wiki-factory,
  private, branch master). Contains `docs/`, `source/`, `servers/`.
- Deployment (live testbed): `~/Prog/research-wiki-factory` — where the
  scripts, wikis, bibs, inbox, and state actually live and run. New or
  changed implementations are installed and exercised here first.

## Rules

1. Edits to the deployment directory are allowed for testing; each change
   is announced before it lands.
2. The source repo is the canonical, transferable copy. Commits happen
   only after the change has been verified working in the deployment
   directory (deploy-first workflow).
3. Secrets scan before and after every commit: API keys, tokens,
   passwords, email addresses, private/Tailscale IPs, credentials,
   hostnames, user names. Nothing sensitive may appear in docs, scripts,
   or git history. No emojis anywhere.
4. No git commit or push without explicit user approval. The agent
   proposes the commit message and a diff summary first. After every
   approved commit, push to GitHub (private repo
   osbama/research-wiki-factory, branch master) — the push is covered by
   the commit approval and needs no separate one.
5. Documentation lives in `docs/` as plain Markdown and must be
   transferable: no absolute machine-specific paths beyond the declared
   deployment root, no machine-specific hosts, accounts, or user names.
   Use relative paths or clearly marked placeholders.
6. All scripts live in `source/scripts/` of the repo; the deployment
   directory receives them only via `source/deploy.sh`.
7. Verification is by real executed output shown to the user, never by
   self-report. Re-runs must be idempotent. Never fabricate results.
   Subagent summaries are self-reports — always verify on disk before
   believing them.
8. The Zotero Better BibTeX export (`wiki-<topic>.bib`) is the sole
   ingestion gate and kill switch. Scripts never modify bib files; a
   citekey absent from the bib must not be ingested, and its pending
   kanban cards are void.
9. Withdrawal of any user artifact (paper, wiki page content, embedding
   rows) is soft and reversible: files move to `_archive/`, flags are
   set, nothing is hard-deleted. One-command restore must exist.
10. User-configurable paths (deployment root, endpoints, model names,
    thresholds) live in `wiki-factory.yaml` and are never hard-coded in
    scripts. `wf_common.get_research_root()` resolves the deployment
    root; `WIKI_FACTORY_ROOT` overrides it.
11. Modifications to the local LLM fleet required by this project are
    proposed to the user first (what, why, exact commands, rollback),
    applied only after explicit confirmation, then documented in
    `servers/` (one dated file per change).
12. The agent pauses for confirmation before giving step-by-step
    instructions or starting implementation of a new component.
13. Every feature addition or behavior change updates the affected docs
    in the same commit (ALGORITHMS / ARCHITECTURE / CONTENTS /
    ONBOARDING as applicable), plus a dated PLAN.md amendment.
    Documentation that lags code is a bug.
