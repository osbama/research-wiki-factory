#!/usr/bin/env python3
"""
ingest_paper.py - Ingest a paper into the wiki.

Usage:
    python ingest_paper.py <topic> <citekey>

Triggered by ingest card. Logic:
1. Copy PDF to wikis/<topic>/papers/<citekey>.pdf
2. Extract text via pdftotext
3. Create wikis/<topic>/notes/<citekey>.md with frontmatter and stub
4. Update ingested-keys.json
"""

import sys
import os
import json
import shutil
import subprocess
import argparse
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from wf_common import (
    load_config, get_wiki_path, get_inbox_path,
    load_bibtex_file, get_zotero_export_path
)


def get_ingested_keys_path(topic: str, config: dict) -> str:
    """Get path to ingested-keys.json for a topic."""
    from wf_common import get_research_root
    wiki_path = Path(get_research_root()) / "wikis" / topic
    return str(wiki_path / "ingested-keys.json")


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text from PDF using pdftotext."""
    try:
        result = subprocess.run(
            ["pdftotext", pdf_path, "-"],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode == 0:
            return result.stdout
        else:
            print(f"Warning: pdftotext returned {result.returncode}")
            return ""
    except FileNotFoundError:
        print("Warning: pdftotext not found. Install poppler-utils.")
        return ""
    except subprocess.TimeoutExpired:
        print("Warning: pdftotext timed out")
        return ""


def create_note_md(topic: str, citekey: str, bibtex_entry: dict, extracted_text: str, config: dict) -> str:
    """Create markdown note with frontmatter and stub."""
    fields = bibtex_entry.get("fields", {})
    
    title = fields.get("title", "Untitled")
    authors = fields.get("author", "Unknown")
    year = fields.get("year", "n.d.")
    abstract = fields.get("abstract", "")
    
    # Build frontmatter
    frontmatter = f"""---
title: "{title}"
authors: "{authors}"
year: {year}
citekey: {citekey}
topic: {topic}
ingested: {datetime.now().isoformat()}
tags:
  - paper
  - {topic}
---

# {title}

## Citation

```bibtex
@{bibtex_entry.get('type', 'article')}{{{citekey},
"""
    
    # Add fields to citation
    for key, value in fields.items():
        if key != "title":  # Already in frontmatter
            frontmatter += f"  {key} = {{{value}}},\n"
    frontmatter += "}\n```\n\n"
    
    # Add abstract if available
    if abstract:
        frontmatter += f"## Abstract\n\n{abstract}\n\n"
    
    # Add extracted text (first 2000 chars as preview)
    if extracted_text:
        preview = extracted_text[:2000]
        frontmatter += f"## Extracted Text (Preview)\n\n{preview}\n\n"
        frontmatter += "*Full text extracted from PDF.*\n\n"
    
    # Add stub sections
    frontmatter += f"""## Summary

<!-- TODO: Add your summary of this paper -->

## Key Insights

<!-- TODO: Add key insights -->

## Related Work

<!-- TODO: Add connections to other papers -->

## Questions

<!-- TODO: Add questions for future research -->
"""
    
    return frontmatter


def update_ingested_keys(topic: str, citekey: str, config: dict) -> None:
    """Add citekey to ingested-keys.json."""
    keys_path = get_ingested_keys_path(topic, config)
    
    # Load existing keys
    if Path(keys_path).exists():
        with open(keys_path, 'r') as f:
            data = json.load(f)
    else:
        data = {"keys": [], "ingested_at": {}}
    
    # Add new key
    if citekey not in data["keys"]:
        data["keys"].append(citekey)
        data["ingested_at"][citekey] = datetime.now().isoformat()
    
    # Write back
    with open(keys_path, 'w') as f:
        json.dump(data, f, indent=2)


def ingest_paper(topic: str, citekey: str, config: dict) -> None:
    """
    Ingest a paper into the wiki.
    
    Args:
        topic: Topic name
        citekey: Citekey of the paper to ingest
        config: Configuration dictionary
    """
    print(f"\n{'='*60}")
    print(f"Ingesting paper: {citekey}")
    print(f"Topic: {topic}")
    print(f"{'='*60}\n")
    
    # Get paths
    wiki_path = get_wiki_path(topic, config)
    inbox_path = get_inbox_path(topic, config)
    bib_path = get_zotero_export_path(topic, config)
    
    papers_dir = Path(wiki_path) / "papers"
    notes_dir = Path(wiki_path) / "notes"
    
    # Ensure directories exist
    papers_dir.mkdir(parents=True, exist_ok=True)
    notes_dir.mkdir(parents=True, exist_ok=True)
    
    # Load BibTeX
    if not Path(bib_path).exists():
        print(f"Error: BibTeX file not found: {bib_path}")
        return
    
    bibtex_entries = load_bibtex_file(bib_path)
    if citekey not in bibtex_entries:
        print(f"Error: Citekey '{citekey}' not found in BibTeX")
        return
    
    entry = bibtex_entries[citekey]
    
    # Find PDF in inbox
    pdf_source = Path(inbox_path).expanduser() / f"{citekey}.pdf"
    if not pdf_source.exists():
        # Try to find by Attanger pattern
        fields = entry.get("fields", {})
        title = fields.get("title", "")
        year = fields.get("year", "")
        author = fields.get("author", "Unknown").split(" and ")[0].split(",")[0].strip()
        
        pattern_config = config.get("attanger_pattern", {})
        suffix1 = pattern_config.get("first_creator_suffix", " - ")
        suffix2 = pattern_config.get("year_suffix", " - ")
        truncate_len = pattern_config.get("title_truncate", 100)
        
        truncated_title = title[:truncate_len] if len(title) > truncate_len else title
        sanitized_title = re.sub(r'[^\w\s\-]', '', truncated_title)
        sanitized_title = re.sub(r'\s+', '_', sanitized_title)
        
        expected_name = f"{author}{suffix1}{year}{suffix2}{sanitized_title}.pdf"
        pdf_source = Path(inbox_path).expanduser() / expected_name
    
    if not pdf_source.exists():
        print(f"Error: PDF not found in inbox: {pdf_source}")
        return
    
    # Copy PDF to papers directory
    pdf_dest = papers_dir / f"{citekey}.pdf"
    print(f"Copying PDF: {pdf_source.name} -> {pdf_dest}")
    shutil.copy2(pdf_source, pdf_dest)
    
    # Extract text from PDF
    print("Extracting text from PDF...")
    extracted_text = extract_text_from_pdf(str(pdf_dest))
    if extracted_text:
        print(f"  Extracted {len(extracted_text)} characters")
    else:
        print("  No text extracted")
    
    # Create note markdown
    print(f"Creating note: {citekey}.md")
    note_content = create_note_md(topic, citekey, entry, extracted_text, config)
    note_path = notes_dir / f"{citekey}.md"
    
    with open(note_path, 'w') as f:
        f.write(note_content)
    
    # Update ingested keys
    print("Updating ingested-keys.json")
    update_ingested_keys(topic, citekey, config)
    
    # Add to embeddings index
    print("Adding to embeddings index...")
    import subprocess
    cmd = [
        sys.executable,
        str(Path(__file__).parent / "embed_index.py"),
        "--topic", topic,
        "add-paper", citekey
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Warning: embed_index failed: {result.stderr}")
    else:
        print("  Added to embeddings")
    
    print(f"\n{'='*60}")
    print(f"Ingestion complete!")
    print(f"PDF: {pdf_dest}")
    print(f"Note: {note_path}")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Ingest Paper into Wiki")
    parser.add_argument("topic", help="Topic name")
    parser.add_argument("citekey", help="Citekey of paper to ingest")
    
    args = parser.parse_args()
    
    # Load configuration
    try:
        config = load_config()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    # Run ingestion
    ingest_paper(args.topic, args.citekey, config)


if __name__ == "__main__":
    main()
