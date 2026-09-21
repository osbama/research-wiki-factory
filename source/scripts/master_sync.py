#!/usr/bin/env python3
"""
master_sync.py - Build cross-topic research overview.

Usage:
    python master_sync.py

Logic:
1. Build wikis/_master/ directory structure
2. Create SCHEMA.md (domain: "cross-topic research overview")
3. Create index.md (list of topics with stats)
4. Create log.md (activity log)
5. For each topic in wiki-factory.yaml:
   - Read index.md + last 30 lines of log.md
   - Write concepts/<topic>.md with page counts, recent activity, wikilinks
6. Update _master/index.md and log.md
7. No LLM prose - structure/stats only
"""

import sys
import os
import json
import argparse
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from wf_common import get_research_root, load_config, get_wiki_path


def parse_index_sections(index_path: Path) -> Dict[str, int]:
    """Parse index.md and count pages by type."""
    if not index_path.exists():
        return {}
    
    with open(index_path, 'r') as f:
        content = f.read()
    
    # Count pages by section
    sections = {
        "papers": 0,
        "concepts": 0,
        "comparisons": 0,
        "queries": 0,
        "entities": 0
    }
    
    # Parse markdown table for papers
    in_papers_table = False
    for line in content.split('\n'):
        line = line.strip()
        
        if line.startswith("## Papers"):
            in_papers_table = True
            continue
        elif line.startswith("## "):
            in_papers_table = False
            
            # Count links in other sections
            for section_name in sections.keys():
                if line.lower() == f"## {section_name.title()}":
                    sections[section_name] = 0  # Reset for this section
        
        if in_papers_table and line.startswith("| ["):
            sections["papers"] += 1
        elif not in_papers_table and line.startswith("- ["):
            # List item with link
            for section_name in sections.keys():
                if f"## {section_name.title()}" in content:
                    # Check if this link is under the section
                    section_idx = content.find(f"## {section_name.title()}")
                    if section_idx != -1 and content.find(line) > section_idx:
                        sections[section_name] += 1
                        break
    
    return sections


def get_recent_log_entries(log_path: Path, limit: int = 30) -> List[str]:
    """Get last N lines from log.md."""
    if not log_path.exists():
        return []
    
    with open(log_path, 'r') as f:
        lines = f.readlines()
    
    # Get last N non-empty lines
    recent = [line.strip() for line in lines[-limit:] if line.strip()]
    return recent


def count_wikilinks(content: str) -> int:
    """Count wikilinks ([[...]]) in content."""
    return len(re.findall(r'\[\[.*?\]\]', content))


def build_master_schema(master_path: Path) -> str:
    """Create SCHEMA.md for _master directory."""
    content = """---
title: "Cross-Topic Research Overview"
domain: "cross-topic research overview"
version: "1.0"
---

# Cross-Topic Research Overview Schema

## Overview

This directory provides a unified view across all research topics.

## Structure

```
_master/
├── SCHEMA.md
├── index.md
├── log.md
└── concepts/
    └── <topic>.md
```

## Purpose

- Track activity across topics
- Identify cross-topic patterns
- Provide navigation entry point

## Update Frequency

Updated automatically by master_sync.py when run.
"""
    
    schema_path = master_path / "SCHEMA.md"
    with open(schema_path, 'w') as f:
        f.write(content)
    
    return str(schema_path)


def build_master_index(topics: List[str], configs: Dict[str, Any], master_path: Path) -> str:
    """Build index.md for _master directory."""
    lines = [
        "---",
        "title: \"Cross-Topic Research Index\"",
        "---",
        "",
        "# Cross-Topic Research Index",
        "",
        "## Topics",
        ""
    ]
    
    for topic in topics:
        wiki_path = Path(get_wiki_path(topic, configs))
        index_path = wiki_path / "index.md"
        
        # Get page counts
        sections = parse_index_sections(index_path)
        total_pages = sum(sections.values())
        
        # Add to index
        lines.append(f"### [{topic}](concepts/{topic}.md)")
        lines.append("")
        lines.append(f"- Total pages: {total_pages}")
        lines.append(f"- Papers: {sections.get('papers', 0)}")
        lines.append(f"- Concepts: {sections.get('concepts', 0)}")
        lines.append(f"- Comparisons: {sections.get('comparisons', 0)}")
        lines.append(f"- Queries: {sections.get('queries', 0)}")
        lines.append("")
    
    index_path = master_path / "index.md"
    with open(index_path, 'w') as f:
        f.write("\n".join(lines))
    
    return str(index_path)


def build_topic_concept(topic: str, config: dict, master_path: Path) -> str:
    """Build concepts/<topic>.md with stats and recent activity."""
    wiki_path = Path(get_wiki_path(topic, config))
    index_path = wiki_path / "index.md"
    log_path = wiki_path / "log.md"
    
    # Get page counts
    sections = parse_index_sections(index_path)
    
    # Get recent log entries
    recent_logs = get_recent_log_entries(log_path, limit=30)
    
    # Build content
    lines = [
        "---",
        f"title: \"{topic} - Overview\"",
        f"topic: {topic}",
        f"generated: {datetime.now().isoformat()}",
        "---",
        "",
        f"# {topic}",
        "",
        "## Page Statistics",
        ""
    ]
    
    for section_name, count in sections.items():
        lines.append(f"- {section_name.title()}: {count}")
    
    lines.append("")
    lines.append("## Recent Activity")
    lines.append("")
    
    if recent_logs:
        for log_entry in recent_logs:
            lines.append(f"- {log_entry}")
    else:
        lines.append("*No recent activity*")
    
    lines.append("")
    lines.append("## Quick Links")
    lines.append("")
    lines.append(f"- [[{topic}/index|Index]]")
    lines.append(f"- [[{topic}/log|Activity Log]]")
    
    # Write file
    concept_path = master_path / "concepts" / f"{topic}.md"
    concept_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(concept_path, 'w') as f:
        f.write("\n".join(lines))
    
    return str(concept_path)


def update_master_log(topics: List[str], configs: Dict[str, Any], master_path: Path) -> str:
    """Update log.md with sync entry."""
    log_path = master_path / "log.md"
    
    # Build log entry
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"## {timestamp}\n\n- Master sync completed for {len(topics)} topics\n"
    
    # Read existing log
    if log_path.exists():
        with open(log_path, 'r') as f:
            existing = f.read()
        content = existing + "\n" + entry
    else:
        content = "# Master Sync Log\n\n" + entry
    
    with open(log_path, 'w') as f:
        f.write(content)
    
    return str(log_path)


def master_sync(config: dict) -> None:
    """
    Build cross-topic research overview.
    
    Args:
        config: Configuration dictionary
    """
    print(f"\n{'='*60}")
    print("Master Sync: Building Cross-Topic Overview")
    print(f"{'='*60}\n")
    
    # Get topics from config
    topics = config.get("topics", [])
    
    if not topics:
        print("No topics configured. Exiting.")
        return
    
    print(f"Topics: {topics}")
    
    # Create _master directory
    wiki_base = Path(config.get("wiki", {}).get("base_dir", str(Path(get_research_root()) / "wikis"))).expanduser()
    master_path = wiki_base / "_master"
    master_path.mkdir(parents=True, exist_ok=True)
    
    # Build SCHEMA.md
    schema_path = build_master_schema(master_path)
    print(f"Created: {schema_path}")
    
    # Build index.md
    index_path = build_master_index(topics, config, master_path)
    print(f"Created: {index_path}")
    
    # Build concept pages for each topic
    concepts_path = master_path / "concepts"
    concepts_path.mkdir(parents=True, exist_ok=True)
    
    for topic in topics:
        concept_path = build_topic_concept(topic, config, master_path)
        print(f"Created: {concept_path}")
    
    # Update log
    log_path = update_master_log(topics, config, master_path)
    print(f"Updated: {log_path}")
    
    print(f"\n{'='*60}")
    print("Master sync complete!")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Master Sync for Research Wiki")
    
    args = parser.parse_args()
    
    # Load configuration
    try:
        config = load_config()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    # Run sync
    master_sync(config)


if __name__ == "__main__":
    main()
