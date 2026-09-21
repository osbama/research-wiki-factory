#!/usr/bin/env python3
"""
bibwatch.py - BibTeX watcher for research topics.

Usage:
    python bibwatch.py <topic>

Logic:
1. Monitor zotero/exports/wiki-<topic>.bib using watchfiles
2. Diff keys in bib vs ingested-keys.json
3. If new key found, locate PDF in inbox/<topic>/
4. Create kanban card: 'ingest: <citekey>' or 'waiting-pdf: <citekey>'

Idempotency key format: bib:<citekey>
"""

import sys
import os
import json
import time
import argparse
import re
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from wf_common import (
    load_config, get_zotero_export_path, get_inbox_path,
    load_bibtex_file, match_pdf_to_citekey, PDFMatch
)

try:
    from watchfiles import watch
    WATCHFILES_AVAILABLE = True
except ImportError:
    WATCHFILES_AVAILABLE = False
    print("Warning: watchfiles not installed. Running in one-shot mode.")
    print("Install with: pip install watchfiles")


def get_ingested_keys_path(topic: str, config: dict) -> str:
    """Get path to ingested-keys.json for a topic (lives in _meta/)."""
    wiki_path = Path("~/research/wikis").expanduser() / topic
    meta = wiki_path / "_meta"
    if meta.exists():
        return str(meta / "ingested-keys.json")
    return str(wiki_path / "ingested-keys.json")  # legacy fallback


def load_ingested_keys(topic: str, config: dict) -> set:
    """Load set of already-ingested citekeys."""
    keys_path = get_ingested_keys_path(topic, config)
    if Path(keys_path).exists():
        with open(keys_path, 'r') as f:
            data = json.load(f)
            return set(data.get("keys", []))
    return set()


def find_pdf_for_citekey(citekey: str, inbox_path: str, bibtex_entries: dict, config: dict) -> str:
    """
    Find PDF file for a citekey in the inbox (searches subdirectories).

    Strategy (in order):
    1. bib 'file' field basename -> exact filename match anywhere under inbox
    2. Attanger-pattern filename match anywhere under inbox
    3. Fuzzy citekey-in-filename match (last resort)
    """
    inbox = Path(inbox_path).expanduser()
    if not inbox.exists():
        return None

    # Get all PDFs in inbox, RECURSIVELY (rglob covers subfolders)
    pdf_files = sorted(inbox.rglob("*.pdf"))
    by_name = {}
    for p in pdf_files:
        by_name.setdefault(p.name, p)  # first occurrence wins on name clash

    entry = bibtex_entries.get(citekey, {})
    fields = entry.get("fields", {})

    # 1. Preferred: bib 'file' field (Zotero attachment, absolute path ->
    #    strip to basename; handle 'path.pdf:application/pdf' and ';' lists)
    file_field = fields.get("file", "")
    if file_field:
        for part in file_field.split(";"):
            part = part.split(":")[0].strip()
            if not part:
                continue
            basename = os.path.basename(part)
            if basename.lower().endswith(".pdf") and basename in by_name:
                print(f"  Found via bib file field: {by_name[basename]}")
                return str(by_name[basename])

    # 2. Exact match on citekey.pdf anywhere in tree
    for p in pdf_files:
        if p.stem == citekey:
            print(f"  Found exact citekey match: {p}")
            return str(p)

    # 3. Attanger pattern match (spaces preserved, not underscores)
    if fields:
        pattern_config = config.get("attanger_pattern", {})
        title = fields.get("title", "")
        year = fields.get("year", "")
        author = fields.get("author", "Unknown").split(" and ")[0].split(",")[0].strip()

        suffix1 = pattern_config.get("first_creator_suffix", " - ")
        suffix2 = pattern_config.get("year_suffix", " - ")
        truncate_len = pattern_config.get("title_truncate", 100)

        truncated_title = title[:truncate_len] if len(title) > truncate_len else title
        # attanger keeps spaces; strip only characters illegal in filenames
        sanitized_title = re.sub(r'[\\/:*?"<>|]', '', truncated_title).strip()

        expected_name = f"{author}{suffix1}{year}{suffix2}{sanitized_title}.pdf"
        if expected_name in by_name:
            print(f"  Found Attanger match: {by_name[expected_name]}")
            return str(by_name[expected_name])

    # 4. Fuzzy match: citekey appears in filename
    for p in pdf_files:
        if citekey.lower() in p.name.lower():
            print(f"  Found fuzzy match: {p}")
            return str(p)

    return None


def create_kanban_card(topic: str, card_type: str, citekey: str, bibtex_entries: dict) -> None:
    """Create a kanban card for ingestion or waiting-for-PDF."""
    entry = bibtex_entries.get(citekey, {})
    fields = entry.get("fields", {})
    
    title = fields.get("title", "Untitled")
    authors = fields.get("author", "Unknown")
    year = fields.get("year", "n.d.")
    
    if card_type == "ingest":
        card_title = f"ingest: {citekey}"
        card_body = f"""Paper: {title}
Authors: {authors}
Year: {year}
Citekey: {citekey}

PDF found in inbox. Ready for ingestion.
"""
    else:  # waiting-pdf
        card_title = f"waiting-pdf: {citekey}"
        card_body = f"""Paper: {title}
Authors: {authors}
Year: {year}
Citekey: {citekey}

PDF not found in inbox. Waiting for PDF upload.
"""
    
    idempotency_key = f"bib:{citekey}"
    
    # Use subprocess for proper argument handling
    import subprocess
    cmd = [
        "hermes", "kanban", "--board", f"wiki-{topic}",
        "create", card_title,
        "--body", card_body,
        "--idempotency-key", idempotency_key
    ]
    
    print(f"  Creating kanban card: {card_title}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Warning: Command failed: {result.stderr}")
    else:
        print(f"  Card created successfully")


def process_bib(topic: str, config: dict) -> None:
    """Process BibTeX file and create kanban cards for new entries."""
    print(f"\n{'='*60}")
    print(f"Processing BibTeX for topic: {topic}")
    print(f"{'='*60}\n")
    
    # Get paths
    bib_path = get_zotero_export_path(topic, config)
    inbox_path = get_inbox_path(topic, config)
    keys_path = get_ingested_keys_path(topic, config)
    
    # Check if bib exists
    if not Path(bib_path).exists():
        print(f"BibTeX file not found: {bib_path}")
        return
    
    # Load BibTeX entries
    bibtex_entries = load_bibtex_file(bib_path)
    print(f"Loaded {len(bibtex_entries)} entries from BibTeX")
    
    # Load ingested keys
    ingested_keys = load_ingested_keys(topic, config)
    print(f"Already ingested: {len(ingested_keys)} keys")
    
    # Find new keys
    new_keys = set(bibtex_entries.keys()) - ingested_keys
    print(f"New keys to process: {len(new_keys)}")
    
    if not new_keys:
        print("No new entries to process.")
        return
    
    # Process each new key
    for citekey in new_keys:
        print(f"\nProcessing: {citekey}")
        
        # Find PDF in inbox
        pdf_path = find_pdf_for_citekey(citekey, inbox_path, bibtex_entries, config)
        
        if pdf_path:
            print(f"  PDF found: {pdf_path}")
            create_kanban_card(topic, "ingest", citekey, bibtex_entries)
        else:
            print(f"  PDF not found in inbox")
            create_kanban_card(topic, "waiting-pdf", citekey, bibtex_entries)
    
    print(f"\n{'='*60}")
    print(f"Processing complete!")
    print(f"{'='*60}\n")


def watch_bib(topic: str, config: dict) -> None:
    """Watch BibTeX file for changes."""
    bib_path = get_zotero_export_path(topic, config)
    
    print(f"\n{'='*60}")
    print(f"Watching BibTeX file: {bib_path}")
    print(f"{'='*60}\n")
    
    # Ensure inbox directory exists
    inbox_path = get_inbox_path(topic, config)
    Path(inbox_path).expanduser().mkdir(parents=True, exist_ok=True)
    
    # Watch for changes
    for changes in watch(bib_path):
        print(f"\n[watchfiles] Detected changes in {bib_path}")
        process_bib(topic, config)


def main():
    parser = argparse.ArgumentParser(description="BibTeX Watcher for Research Topics")
    parser.add_argument("topic", help="Topic name")
    parser.add_argument("--watch", action="store_true", help="Watch for changes (requires watchfiles)")
    
    args = parser.parse_args()
    
    # Load configuration
    try:
        config = load_config()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    if args.watch and WATCHFILES_AVAILABLE:
        watch_bib(args.topic, config)
    else:
        process_bib(args.topic, config)


if __name__ == "__main__":
    main()
