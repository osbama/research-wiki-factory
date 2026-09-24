# ONBOARDING — brief a new agent (or human) to continue this project

This file is the handover document. Section 1 is a ready-to-paste prompt
for a fresh Hermes agent session; the rest is the context that prompt
refers to.

## 1. Paste-this prompt (adapt paths if cloned elsewhere)

    You are continuing development of the research-wiki-factory project.

    Repository (canonical): the cloned repo at CLONE_PATH
    (origin: github.com/osbama/research-wiki-factory, private, branch master).
    Deployment testbed: DEPLOY_DIR (default ~/Prog/research-wiki-factory —
    a working copy where scripts, wikis, bibs, and state live).

    Before anything else, read IN THIS ORDER:
      1. docs/RULES.md          — binding working rules (they override
                                  your defaults; in particular: deploy-first
                                  testing, no commit without my approval,
                                  secrets scan before and after every
                                  commit, push after each approved commit,
                                  Zotero bib is the sole ingestion gate,
                                  soft-delete only, no emojis, docs must
                                  not contain machine-specific paths/hosts)
      2. README.md              — what the project is
      3. docs/OVERVIEW.md       — what it does and the daily workflow
      4. docs/PLAN.md           — design decisions and amendments
      5. docs/ALGORITHMS.md     — how each component works
      6. docs/ARCHITECTURE.md   — layout, data flow, file formats
      7. docs/CONTENTS.md       — repo map

    Then verify your footing with real commands, not assumptions:
      - cd DEPLOY_DIR/scripts && python3 test_wf_common.py   (15 tests OK)
      - python3 embed_index.py --topic <topic> status        (vectors on disk)
      - hermes -p researcher kanban --board wiki-<topic> list
      - git -C CLONE_PATH log --oneline | head

    Wait for my first task. Propose before implementing; show real
    command output when you claim something works.

## 2. Design goals (the "why" behind the code)

- Zotero is the human gate. Papers enter a wiki only when the user moves
  them into a Zotero collection (Better BibTeX auto-export). Machines
  propose (Semantic Scholar candidates) and verify (embedding checks);
  the human disposes. Never build a path that bypasses the bib.
- One deployment, many topics. Topics are isolated under per-topic
  directories and kanban boards; wiki-factory.yaml registers them. Never
  design topic-specific state into scripts.
- Soft-delete everything. Withdrawn papers, archived content, and
  embedding rows are flagged or moved, never hard-deleted; every
  withdrawal has a one-command restore.
- The embedding server is a similarity oracle, not a fact checker. It
  flags unsupported claims and coverage gaps; it cannot detect
  contradictions. Keep thresholds configurable and honest.
- Plain dependencies. Python stdlib + numpy + PyYAML + requests +
  watchfiles + poppler-utils. Justify any new dependency first.
- Portable by construction. Backups carry artifacts and a sha256
  manifest, never code, never secrets. Secrets are environment-only.

## 3. The workflow contract

1. New work happens in the deployment directory first and is verified
   there with real command output.
2. Verified changes are ported to the repo, docs updated (PLAN /
   ALGORITHMS / ARCHITECTURE / CONTENTS / ONBOARDING as applicable).
3. Secrets scan, then the agent proposes commit message + diff summary.
4. On approval: commit, then push to origin master.

## 4. Non-obvious operational facts

- The pipeline runs under a dedicated Hermes profile (researcher). The
  wiki-factory plugin is profile-scoped: bibwatch runs only while at
  least one session of that profile is open. Other profiles see nothing.
- Cron jobs (daily sweep, weekly audit/sync) deliver local-only: output
  lands in DEPLOY_DIR/state/ and on the kanban board; nothing messages
  the user. They fire only while the Hermes gateway runs.
- restore_backup.py (whole-deployment backup restore) and restore.py
  (single-paper withdrawal restore) are different scripts. Do not merge
  or rename them; the naming collision is deliberate and documented.
- Backups do not store empty directories (tar limitation); wf_init.py
  recreates the wiki skeleton after a restore onto a fresh machine.
- attanger renames PDFs with SPACES preserved ("Author - Year - Title
  truncate=100.pdf"); matchers must not convert to underscores. The bib
  `file` field (absolute Zotero path stripped to basename) is the
  highest-precedence match.
- Without SEMANTIC_SCHOLAR_API_KEY the sweep still runs but hits 429
  backoff frequently; that is expected behavior, not a bug.
- The kanban CLI is the only supported way to create cards
  (idempotency keys: bib:<citekey>, s2:<paperId>,
  verify:<topic>:<page>:<sha1>, coverage:<topic>:<date>).
- Delegated subagents on this stack have repeatedly filed false reports;
  always verify on disk before believing a summary.
- Host python may lack pip (bootstrap: python3 -m ensurepip --user) and
  pytest (use unittest; test_wf_common.py runs standalone).
