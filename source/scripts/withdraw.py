#!/usr/bin/env python3
"""
withdraw.py - Withdraw a paper from the wiki (archive it).

Usage:
    python withdraw.py <topic> <citekey>

Logic:
1. Move PDF/MD to wikis/<topic>/_archive/<citekey>/
2. Update ledger (ingested-keys.json)
3. Flag 'contested: true' in notes
"""

import sys
import os
import json
import shutil
import argparse
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


def withdraw_paper(topic: str, citekey: str, config: dict, reason: str = "") -> None:
    """
    Withdraw a paper from the wiki and archive it.
    
    Args:
        topic: Topic name
        citekey: Citekey of the paper to withdraw
        config: Configuration dictionary
        reason: Optional reason for withdrawal
    """
    print(f"\n{'='*60}")
    print(f"Withdrawing paper: {citekey}")
    print(f"Topic: {topic}")
    print(f"{'='*60}\n")
    
    wiki_path = get_wiki_path(topic, config)
    papers_dir = Path(wiki_path) / "raw" / "papers"
    notes_dir = Path(wiki_path) / "concepts"
    archive_dir = Path(wiki_path) / "_archive" / citekey
    
    # Check if paper exists
    pdf_path = papers_dir / f"{citekey}.pdf"
    note_path = papers_dir / f"{citekey}.md"
    
    if not pdf_path.exists() and not note_path.exists():
        print(f"Error: Paper '{citekey}' not found in wiki")
        return
    
    # Create archive directory
    archive_dir.mkdir(parents=True, exist_ok=True)
    print(f"Creating archive directory: {archive_dir}")
    
    # Move PDF to archive
    if pdf_path.exists():
        print(f"Moving PDF to archive: {pdf_path.name}")
        shutil.move(str(pdf_path), str(archive_dir / f"{citekey}.pdf"))
    
    # Move note to archive
    if note_path.exists():
        print(f"Moving note to archive: {note_path.name}")
        shutil.move(str(note_path), str(archive_dir / f"{citekey}.md"))
    
    # Update note to add contested flag
    archived_note_path = archive_dir / f"{citekey}.md"
    if archived_note_path.exists():
        with open(archived_note_path, 'r') as f:
            content = f.read()
        
        # Add contested flag to frontmatter
        if "contested: true" not in content:
            # Insert after the first --- line
            lines = content.split('\n')
            new_lines = [lines[0]]  # First ---
            new_lines.append(f"contested: true")
            new_lines.append(f"withdrawn: {datetime.now().isoformat()}")
            if reason:
                new_lines.append(f"withdrawal_reason: {reason}")
            new_lines.extend(lines[1:])
            
            content = '\n'.join(new_lines)
            
            with open(archived_note_path, 'w') as f:
                f.write(content)
            print("Added contested flag to note")
    
    # Update ingested keys - mark as withdrawn
    keys_path = get_ingested_keys_path(topic, config)
    if Path(keys_path).exists():
        with open(keys_path, 'r') as f:
            data = json.load(f)
        
        # Add to withdrawn list
        if "withdrawn" not in data:
            data["withdrawn"] = []
        
        if citekey not in data["withdrawn"]:
            data["withdrawn"].append(citekey)
        
        # Add withdrawal metadata
        if "withdrawals" not in data:
            data["withdrawals"] = {}
        
        data["withdrawals"][citekey] = {
            "withdrawn_at": datetime.now().isoformat(),
            "reason": reason,
            "archive_path": str(archive_dir)
        }
        
        with open(keys_path, 'w') as f:
            json.dump(data, f, indent=2)
        print("Updated ingested-keys.json")
    
    # Remove from embeddings index (soft)
    print("Removing from embeddings index...")
    import subprocess
    cmd = [
        sys.executable,
        str(Path(__file__).parent / "embed_index.py"),
        "--topic", topic,
        "remove-paper", citekey
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Warning: embed_index failed: {result.stderr}")
    else:
        print("  Removed from embeddings")
    
    print(f"\n{'='*60}")
    print(f"Withdrawal complete!")
    print(f"Archived to: {archive_dir}")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Withdraw Paper from Wiki")
    parser.add_argument("topic", help="Topic name")
    parser.add_argument("citekey", help="Citekey of paper to withdraw")
    parser.add_argument("--reason", help="Reason for withdrawal", default="")
    
    args = parser.parse_args()
    
    # Load configuration
    try:
        config = load_config()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    # Run withdrawal
    withdraw_paper(args.topic, args.citekey, config, args.reason)


if __name__ == "__main__":
    main()
