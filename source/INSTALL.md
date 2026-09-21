# Installation — auto-LLMRAG (user side)

Deploys the Research Wiki Factory onto a Hermes setup. Tested on Linux
(Fedora 43, python 3.14, Hermes Agent git install).

## 0. Prerequisites

- Hermes Agent (`hermes --version`), plus a **dedicated Hermes profile** to
  host the pipeline. A separate profile is required, not optional: the
  wiki-factory plugin is profile-scoped so the bib watcher only runs while
  sessions of THAT profile are active — your everyday profile stays clean.
  Create and verify one (we use `researcher` throughout; any name works):
  ```bash
  hermes profile create researcher
  hermes profile list          # should show the new profile
  ```
- Zotero with **Better BibTeX** and **Attanger** plugins.
- A LiteLLM (or any OpenAI-compatible) endpoint serving an embedding model
  (default `qwen3-embedding-8b`, 4096-dim).
- System packages: `pdftotext` (poppler-utils), git.
- Credentials (**to be filled by you** — the repo ships none):
  1. `SEMANTIC_SCHOLAR_API_KEY` — free key from
     https://www.semanticscholar.org/product/api#api-key-form
     (recommended; without it the sweep works but is heavily rate-limited)
  2. An OpenAI-compatible embedding endpoint (e.g. LiteLLM proxy serving
     `qwen3-embedding-8b`) — you provide its URL/model in the config
  3. If that endpoint requires auth, its API key as well
  4. Your normal Hermes LLM provider credentials (e.g. OpenRouter) —
     part of standard Hermes profile setup, not this project
- Python deps (system python3, user site is fine):
  ```bash
  python3 -m ensurepip --user   # only if pip is missing
  python3 -m pip install --user watchfiles pyyaml requests numpy
  ```

## 1. Get the source

```bash
git clone <this-repo-url> ~/source/auto-LLMRAG
# or unzip the release zip into ~/source/auto-LLMRAG
cd ~/source/auto-LLMRAG
```

## 2. Configure

```bash
mkdir -p ~/Prog/research-wiki-factory
cp source/wiki-factory.yaml ~/Prog/research-wiki-factory/wiki-factory.yaml
```

Edit `~/Prog/research-wiki-factory/wiki-factory.yaml`:
- `litellm.base_url` → your proxy (`http://<host>:<port>/v1/`)
- `litellm.embedding_model` → your served model id
- `topics:` → your first topic name (mapping form; see inline comments)

Add your Semantic Scholar key to the profile env:
```bash
echo 'SEMANTIC_SCHOLAR_API_KEY=<your-key>' >> ~/.hermes/profiles/<profile>/.env
```

## 3. Deploy

```bash
bash source/deploy.sh <profile>
```

This rsyncs scripts → `~/Prog/research-wiki-factory/scripts/`, plugin →
`~/.hermes/profiles/<profile>/plugins/wiki-factory/`, skill →
`~/.hermes/profiles/<profile>/skills/research/research-wiki-factory/`,
and enables the plugin in the profile config (idempotent).

Verify:
```bash
python3 ~/Prog/research-wiki-factory/scripts/test_wf_common.py     # 15 tests OK
hermes -p <profile> skills list | grep research-wiki-factory
```

## 4. Zotero wiring (per topic)

1. Create a Zotero collection for the topic (e.g. `Wiki/llm-agents`).
2. Better BibTeX → Preferences → Automatic export → add the collection,
   format BibTeX, path `~/Prog/research-wiki-factory/zotero/exports/wiki-<topic>.bib`,
   "on change".
3. Attanger: set rename pattern
   `{{ firstCreator suffix=" - " }}{{ year suffix=" - " }}{{ title truncate="100" }}`
   and destination `~/Prog/research-wiki-factory/inbox/<topic>/` (or one shared library —
   the watcher scans recursively and matches by bib).

## 5. Initialize the topic

```bash
python3 ~/Prog/research-wiki-factory/scripts/wf_init.py <topic>   # dirs + kanban board
```

## 6. Scheduled jobs (optional but recommended)

Under the pipeline profile:

```bash
hermes -p <profile> cron create "0 6 * * *" \
  "Run the daily Semantic Scholar literature sweep for all topics in ~/Prog/research-wiki-factory/wiki-factory.yaml: for each topic run 'python3 ~/Prog/research-wiki-factory/scripts/s2_sweep.py <topic>'. Log to ~/Prog/research-wiki-factory/state/." \
  --name wiki-factory-daily-sweep --deliver local --skill research-wiki-factory

hermes -p <profile> cron create "0 8 * * 0" \
  "Weekly wiki maintenance: run coverage_audit.py per topic, then master_sync.py. Log to ~/Prog/research-wiki-factory/state/." \
  --name wiki-factory-weekly --deliver local --skill research-wiki-factory
```

Note: cron fires only while `hermes gateway` runs (or trigger manually:
`hermes -p <profile> cron run <id>`).

## 7. Daily use

All pipeline interaction goes through the dedicated profile: prefix commands
with `hermes -p <profile>` (or use the profile alias). The bib watcher runs
only while at least one session of that profile is open.

- New suggestions: kanban board `hermes -p <profile> kanban --board wiki-<topic> list`
  and `~/Prog/research-wiki-factory/candidates/<topic>-new.bib`.
- Import the candidates bib into Zotero, drag keepers into the topic
  collection. While any session of the profile is open, the watcher
  ingests automatically (ingest cards appear within seconds).
- Check watcher health: `tail ~/Prog/research-wiki-factory/state/bibwatch-<topic>.log`.

## 8. Backup & transfer to another machine

```bash
# On machine A:
python3 ~/Prog/research-wiki-factory/scripts/backup.py
# -> ~/Prog/research-wiki-factory/backups/backup-<timestamp>.tar.gz

# Copy the tar.gz to machine B (scp/usb/…). On machine B:
#   1. deploy from the repo first (steps 1-5 above) to get scripts
#   2. then restore:
python3 ~/Prog/research-wiki-factory/scripts/restore_backup.py backup-<timestamp>.tar.gz
```

- The script validates the archive (manifest, per-file sha256,
  path-traversal and secret checks) and refuses anything malformed.
- If machine B already has NEWER artifacts, restore aborts — pass
  `--force` only when you really want the backup to overwrite them.
- API keys and credentials are never inside backups; provision them on
  the new machine separately (see §0).
- Zotero on machine B must re-point its Better BibTeX auto-export to the
  new machine's `zotero/exports/` path.

## Uninstall

```bash
rm -rf ~/.hermes/profiles/<profile>/plugins/wiki-factory \
       ~/.hermes/profiles/<profile>/skills/research/research-wiki-factory
# remove 'wiki-factory' from plugins.enabled in the profile config.yaml
# runtime data in ~/Prog/research-wiki-factory/ is yours to keep or delete
```
