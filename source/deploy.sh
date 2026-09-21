#!/usr/bin/env bash
# deploy.sh — install auto-LLMRAG from this repo onto a Hermes profile.
# Usage: bash source/deploy.sh <profile>
# Idempotent: safe to re-run after git pulls.
set -euo pipefail

PROFILE="${1:?usage: deploy.sh <profile>}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE_DIR="$HOME/.hermes/profiles/$PROFILE"
RESEARCH="$HOME/Prog/research-wiki-factory"

[ -d "$PROFILE_DIR" ] || { echo "error: profile '$PROFILE' not found at $PROFILE_DIR"; exit 1; }

echo "==> Deploying from $REPO_ROOT to profile '$PROFILE'"

# 1. Runtime dirs + scripts
mkdir -p "$RESEARCH"/{scripts,zotero/exports,candidates,inbox,state,wikis}
rsync -a --delete --exclude '__pycache__' --exclude 'test_*.py' \
  "$REPO_ROOT/source/scripts/" "$RESEARCH/scripts/"
# tests are deployed too (useful for verification) but not deleted-targeted:
rsync -a "$REPO_ROOT/source/scripts/test_wf_common.py" "$RESEARCH/scripts/" 2>/dev/null || true

# 2. Plugin + skill
mkdir -p "$PROFILE_DIR/plugins/wiki-factory" \
         "$PROFILE_DIR/skills/research/research-wiki-factory"
rsync -a --delete --exclude '__pycache__' \
  "$REPO_ROOT/source/plugin/wiki-factory/" "$PROFILE_DIR/plugins/wiki-factory/"
rsync -a "$REPO_ROOT/source/skill/" "$PROFILE_DIR/skills/research/research-wiki-factory/"

# 3. Config template (never overwrite a live config)
if [ ! -f "$RESEARCH/wiki-factory.yaml" ]; then
  cp "$REPO_ROOT/source/wiki-factory.yaml" "$RESEARCH/wiki-factory.yaml"
  echo "==> Installed config template at $RESEARCH/wiki-factory.yaml — EDIT IT before use"
else
  echo "==> Keeping existing $RESEARCH/wiki-factory.yaml"
fi

# 4. Enable plugin in profile config (append to plugins.enabled if absent)
CFG="$PROFILE_DIR/config.yaml"
if [ -f "$CFG" ]; then
  if ! grep -q 'wiki-factory' "$CFG"; then
    if grep -q '^plugins:' "$CFG"; then
      python3 - "$CFG" <<'EOF'
import re, sys
p = sys.argv[1]
s = open(p).read()
m = re.search(r'^plugins:\n((?:  .*\n)+)', s, re.M)
if m and 'enabled:' in m.group(1):
    block = m.group(0)
    new_block = block.rstrip('\n') + '\n    - wiki-factory\n'
    s = s.replace(block, new_block, 1)
else:
    s = s.rstrip('\n') + '\nplugins:\n  enabled:\n    - wiki-factory\n'
open(p, 'w').write(s)
print("==> Enabled wiki-factory plugin in profile config")
EOF
    else
      printf '\nplugins:\n  enabled:\n    - wiki-factory\n' >> "$CFG"
      echo "==> Enabled wiki-factory plugin in profile config"
    fi
  else
    echo "==> Plugin already enabled in profile config"
  fi
fi

echo "==> Done. Run: python3 $RESEARCH/scripts/test_wf_common.py"
