#!/usr/bin/env python3
"""
restore.py - Restore a withdrawn paper from the archive.

Usage:
    python restore.py <topic> <citekey>

Logic:
1. Move PDF/MD back from wikis/<topic>/_archive/<citekey>/
2. Update ledger (ingested-keys.json)
3. Remove 'contested: true' flag from notes
"""

import sys
import os
import json
import shutil
import argparse
import re
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from wf_common import load_config, get_wiki_path


def get_ingested_keys_path(topic: str, config: dict) -> str:
    """Get path to ingested-keys.json for a topic."""
    from wf_common import get_research_root
    wiki_path = Path(get_research_root()) / "wikis" / topic
    return str(wiki_path / "ingested-keys.json")


def restore_paper(topic: str, citekey: str, config: dict) -> None:
    """
    Restore a withdrawn paper from the archive.
    
    Args:
        topic: Topic name
        citekey: Citekey of the paper to restore
        config: Configuration dictionary
    """
    print(f"\n{'='*60}")
    print(f"Restoring paper: {citekey}")
    print(f"Topic: {topic}")
    print(f"{'='*60}\n")
    
    wiki_path = get_wiki_path(topic, config)
    papers_dir = Path(wiki_path) / "raw" / "papers"
    archive_dir = Path(wiki_path) / "_archive" / citekey
    
    # Check if paper exists in archive
    if not archive_dir.exists():
        print(f"Error: Paper '{citekey}' not found in archive")
        return
    
    archived_pdf = archive_dir / f"{citekey}.pdf"
    archived_note = archive_dir / f"{citekey}.md"
    
    # Ensure target directories exist
    papers_dir.mkdir(parents=True, exist_ok=True)
    
    # Move PDF back
    if archived_pdf.exists():
        print(f"Restoring PDF: {archived_pdf.name}")
        shutil.move(str(archived_pdf), str(papers_dir / f"{citekey}.pdf"))
    
    # Move note back and remove contested flag
    if archived_note.exists():
        print(f"Restoring note: {archived_note.name}")
        
        with open(archived_note, 'r') as f:
            content = f.read()
        
        # Remove contested flag and withdrawal metadata from frontmatter
        lines = content.split('\n')
        new_lines = []
        in_frontmatter = False
        skip_next = False
        
        for i, line in enumerate(lines):
            if line.strip() == '---':
                if not in_frontmatter:
                    in_frontmatter = True
                    new_lines.append(line)
                else:
                    in_frontmatter = False
                    new_lines.append(line)
            elif in_frontmatter:
                # Skip contested, withdrawn, withdrawal_reason lines
                if (line.startswith('contested:') or 
                    line.startswith('withdrawn:') or 
                    line.startswith('withdrawal_reason:')):
                    continue
                new_lines.append(line)
            else:
                new_lines.append(line)
        
        content = '\n'.join(new_lines)
        
        # Write restored note
        with open(papers_dir / f"{citekey}.md", 'w') as f:
            f.write(content)
        
        # Remove archived note
        os.remove(archived_note)
        print("Removed contested flag from note")
    
    # Remove archive directory
    if archive_dir.exists():
        shutil.rmtree(archive_dir)
        print("Removed archive directory")
    
    # Update ingested keys - mark as restored
    keys_path = get_ingested_keys_path(topic, config)
    if Path(keys_path).exists():
        with open(keys_path, 'r') as f:
            data = json.load(f)
        
        # Remove from withdrawn list
        if "withdrawn" in data and citekey in data["withdrawn"]:
            data["withdrawn"].remove(citekey)
        
        # Remove withdrawal metadata
        if "withdrawals" in data and citekey in data["withdrawals"]:
            del data["withdrawals"][citekey]
        
        with open(keys_path, 'w') as f:
            json.dump(data, f, indent=2)
        print("Updated ingested-keys.json")
    
    # Restore in embeddings index
    print("Restoring in embeddings index...")
    import subprocess
    cmd = [
        sys.executable,
        str(Path(__file__).parent / "embed_index.py"),
        "--topic", topic,
        "restore-paper", citekey
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Warning: embed_index failed: {result.stderr}")
    else:
        print("  Restored in embeddings")
    
    print(f"\n{'='*60}")
    print(f"Restoration complete!")
    print(f"Paper restored to active wiki")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Restore Paper from Archive")
    parser.add_argument("topic", help="Topic name")
    parser.add_argument("citekey", help="Citekey of paper to restore")
    
    args = parser.parse_args()
    
    # Load configuration
    try:
        config = load_config()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    # Run restoration
    restore_paper(args.topic, args.citekey, config)


if __name__ == "__main__":
    main()
