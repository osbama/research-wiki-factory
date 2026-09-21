#!/usr/bin/env python3
"""backup.py — Create a portable backup of a research-wiki-factory deployment.

Usage:
    python3 backup.py [--root <dir>] [--out <dir>] [--full]

Creates ~/Prog/research-wiki-factory/backups/backup-YYYYmmdd-HHMMSS.tar.gz

Backup contents (relative to the deployment root):
    wiki-factory.yaml, wikis/, candidates/, zotero/, inbox/, state/
Excludes:
    scripts/   (code comes from the source repo / deploy.sh)
    backups/   (no recursive backups of backups)
    __pycache__, *.pyc, .git, any *.key / .env files, anything matching
    secret patterns (API keys never leave the machine).

A manifest (backup-manifest.json) is embedded with:
    created_at, host, root, file list with sha256 + sizes.
With --full, also includes raw/papers PDFs (default: include; PDFs are the
irreplaceable human-curated artifacts — always included in practice).
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

INCLUDE_DIRS = ["wikis", "candidates", "zotero", "inbox", "state"]
INCLUDE_FILES = ["wiki-factory.yaml"]
EXCLUDE_DIRS = {"scripts", "backups", "__pycache__", ".git", "_archive"}
SECRET_PATTERNS = (".env", ".key", "credentials", "secret", "token", "api_key", "apikey")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def looks_secret(relpath: str) -> bool:
    low = relpath.lower()
    return any(p in low for p in SECRET_PATTERNS)


def collect(root: Path):
    manifest_files = []
    skipped = []
    for name in INCLUDE_FILES:
        p = root / name
        if p.exists():
            manifest_files.append((p, name))
    for d in INCLUDE_DIRS:
        base = root / d
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            parts = set(p.relative_to(root).parts[:-1])
            if parts & EXCLUDE_DIRS:
                skipped.append((rel, "excluded dir"))
                continue
            if p.suffix in (".pyc",):
                skipped.append((rel, "bytecode"))
                continue
            if looks_secret(rel):
                skipped.append((rel, "secret-pattern"))
                continue
            manifest_files.append((p, rel))
    return manifest_files, skipped


def main():
    ap = argparse.ArgumentParser(description="Backup a research-wiki-factory deployment")
    ap.add_argument("--root", default=None, help="Deployment root (default: WIKI_FACTORY_ROOT or ~/Prog/research-wiki-factory)")
    ap.add_argument("--out", default=None, help="Output directory (default: <root>/backups)")
    ap.add_argument("--full", action="store_true", help="Accepted for clarity; PDFs are always included")
    args = ap.parse_args()

    root = Path(args.root or get_research_root()).expanduser().resolve()
    if not (root / "wiki-factory.yaml").exists():
        print(f"ERROR: {root} does not look like a deployment (wiki-factory.yaml missing)")
        sys.exit(1)

    out_dir = Path(args.out).expanduser() if args.out else root / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = time.strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"backup-{ts}.tar.gz"

    files, skipped = collect(root)
    manifest = {
        "format": "research-wiki-factory-backup",
        "version": 1,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "epoch": int(time.time()),
        "host": os.uname().nodename,
        "root": str(root),
        "n_files": len(files),
        "files": [],
    }

    print(f"Creating backup: {out_path}")
    with tarfile.open(out_path, "w:gz") as tar:
        for path, rel in files:
            tar.add(path, arcname=rel)
            manifest["files"].append({
                "path": rel,
                "size": path.stat().st_size,
                "sha256": sha256_of(path),
            })
        # embed manifest
        m_bytes = json.dumps(manifest, indent=2).encode()
        info = tarfile.TarInfo("backup-manifest.json")
        info.size = len(m_bytes)
        import io
        tar.addfile(info, io.BytesIO(m_bytes))

    total = sum(f["size"] for f in manifest["files"])
    print(f"  Files: {len(files)}  ({total/1e6:.1f} MB uncompressed)")
    if skipped:
        print(f"  Skipped {len(skipped)} file(s):")
        for rel, why in skipped[:10]:
            print(f"    - {rel} ({why})")
        if len(skipped) > 10:
            print(f"    ... and {len(skipped)-10} more")
    print("Done.")
    print(out_path)


if __name__ == "__main__":
    main()
