#!/usr/bin/env python3
"""restore_backup.py — Integrate a research-wiki-factory backup into a deployment.

Usage:
    python3 restore_backup.py <backup.tar.gz> [--root <dir>] [--dry-run] [--force]

Behaviour:
- Validates the archive: must be a gzip tar containing backup-manifest.json
  with format == "research-wiki-factory-backup" and a file list with sha256s.
- Verifies every extracted file against its manifest sha256.
- Timestamp rule: the BACKUP's created_at is compared against the newest
  local state (max mtime over wikis/, candidates/, zotero/, inbox/, state/,
  wiki-factory.yaml). If the local deployment is NEWER than the backup,
  restore aborts unless --force is given.
- --force bypasses the timestamp check and overwrites local artifacts.
- Never touches scripts/ (code) or anything outside the deployment root
  (path traversal is rejected).
- Secrets are not expected in backups; any file matching secret patterns
  in the archive is refused.

After restore, run deploy.sh (from the source repo) to refresh scripts.
"""

import argparse
import hashlib
import json
import os
import sys
import tarfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from wf_common import get_research_root

SECRET_PATTERNS = (".env", ".key", "credentials", "secret", "token", "api_key", "apikey")
REQUIRED_KEYS = {"format", "created_at", "epoch", "files"}


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def fail(msg, code=1):
    print(f"ERROR: {msg}")
    sys.exit(code)


def newest_local_epoch(root: Path) -> int:
    """Newest mtime among the data a backup covers."""
    candidates = []
    for sub in ("wikis", "candidates", "zotero", "inbox", "state"):
        base = root / sub
        if base.exists():
            for p in base.rglob("*"):
                if p.is_file():
                    candidates.append(p.stat().st_mtime)
    cfg = root / "wiki-factory.yaml"
    if cfg.exists():
        candidates.append(cfg.stat().st_mtime)
    return int(max(candidates)) if candidates else 0


def main():
    ap = argparse.ArgumentParser(description="Restore a research-wiki-factory backup")
    ap.add_argument("backup", help="Path to backup-*.tar.gz")
    ap.add_argument("--root", default=None,
                    help="Deployment root (default: WIKI_FACTORY_ROOT or ~/Prog/research-wiki-factory)")
    ap.add_argument("--dry-run", action="store_true", help="Validate and report, extract nothing")
    ap.add_argument("--force", action="store_true",
                    help="Restore even if local state is newer than the backup")
    args = ap.parse_args()

    backup_path = Path(args.backup).expanduser()
    if not backup_path.exists():
        fail(f"backup not found: {backup_path}")

    root = Path(args.root or get_research_root()).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    # 1. Open + validate archive
    try:
        tf = tarfile.open(backup_path, "r:gz")
    except (tarfile.TarError, OSError) as e:
        fail(f"not a valid gzip tar: {e}")

    names = tf.getnames()
    if "backup-manifest.json" not in names:
        fail("missing backup-manifest.json — not a research-wiki-factory backup")

    manifest_raw = tf.extractfile("backup-manifest.json").read()
    try:
        manifest = json.loads(manifest_raw)
    except json.JSONDecodeError:
        fail("backup-manifest.json is not valid JSON")

    missing = REQUIRED_KEYS - set(manifest.keys())
    if missing:
        fail(f"manifest missing keys: {sorted(missing)}")
    if manifest["format"] != "research-wiki-factory-backup":
        fail(f"unrecognized format: {manifest['format']!r}")

    # 2. Timestamp rule
    backup_epoch = int(manifest["epoch"])
    local_epoch = newest_local_epoch(root)
    print(f"Backup created: {manifest['created_at']} (host: {manifest.get('host','?')})")
    print(f"Local newest state: "
          f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(local_epoch)) if local_epoch else '(empty deployment)'}")
    if local_epoch > backup_epoch and not args.force:
        fail("local deployment state is NEWER than this backup — aborting "
             "(use --force to override, or restore a newer backup)")
    if local_epoch > backup_epoch and args.force:
        print("WARNING: --force given — overwriting NEWER local artifacts with older backup")

    # 3. Validate members: paths, secrets, hashes
    manifest_files = {f["path"]: f for f in manifest["files"]}
    problems = []
    members = [m for m in tf.getmembers() if m.isfile() and m.name != "backup-manifest.json"]

    for m in members:
        dest = (root / m.name).resolve()
        if not str(dest).startswith(str(root) + os.sep):
            problems.append(f"path traversal: {m.name}")
            continue
        low = m.name.lower()
        if any(p in low for p in SECRET_PATTERNS):
            problems.append(f"secret-pattern file refused: {m.name}")
            continue
        entry = manifest_files.get(m.name)
        if entry is None:
            problems.append(f"not in manifest: {m.name}")
            continue
        data = tf.extractfile(m).read()
        if sha256_bytes(data) != entry["sha256"]:
            problems.append(f"sha256 mismatch: {m.name}")
    manifest_listed = set(manifest_files) - {m.name for m in members}
    if manifest_listed:
        problems.append(
            f"manifest lists {len(manifest_listed)} file(s) absent from archive: "
            f"{sorted(manifest_listed)[:5]}")

    if problems:
        for p in problems[:20]:
            print(f"  INVALID: {p}")
        fail(f"{len(problems)} validation problem(s) — backup rejected")

    print(f"Validated: {len(members)} files, sha256 OK, no secrets, no traversal")
    if args.dry_run:
        print("Dry run — nothing extracted.")
        sys.exit(0)

    # 4. Extract (newer backup overrides older local state)
    for m in members:
        dest = root / m.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(tf.extractfile(m).read())
    tf.close()
    print(f"Restored {len(members)} files into {root}")
    print("Next step: refresh scripts from the source repo (deploy.sh) if needed.")


if __name__ == "__main__":
    main()
