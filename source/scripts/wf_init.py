#!/usr/bin/env python3
"""
wf_init.py - Initialize directory hierarchy and kanban board for a research topic.

Usage:
    python wf_init.py <topic>

Creates:
- ~/Prog/research-wiki-factory/wikis/<topic>/
- ~/Prog/research-wiki-factory/inbox/<topic>/
- Kanban board via 'hermes kanban boards create wiki-<topic>'
"""

import sys
import os
import subprocess
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from wf_common import load_config, get_inbox_path, get_wiki_path


def create_directory_structure(topic: str, config: dict) -> None:
    """Create the directory hierarchy for a topic."""
    wiki_dir = get_wiki_path(topic, config)
    inbox_dir = get_inbox_path(topic, config)
    
    print(f"Creating directory structure for topic: {topic}")
    
    # Create wiki directory
    wiki_path = Path(wiki_dir).expanduser()
    wiki_path.mkdir(parents=True, exist_ok=True)
    print(f"  ✓ Created: {wiki_path}")
    
    # Create inbox directory
    inbox_path = Path(inbox_dir).expanduser()
    inbox_path.mkdir(parents=True, exist_ok=True)
    print(f"  ✓ Created: {inbox_path}")
    
    # Create subdirectories in wiki
    (wiki_path / "notes").mkdir(exist_ok=True)
    (wiki_path / "papers").mkdir(exist_ok=True)
    (wiki_path / "embeddings").mkdir(exist_ok=True)
    print(f"  ✓ Created subdirectories: notes/, papers/, embeddings/")


def create_kanban_board(topic: str) -> None:
    """Create a kanban board for the topic using hermes CLI."""
    board_name = f"wiki-{topic}"
    
    print(f"Creating kanban board: {board_name}")
    
    try:
        result = subprocess.run(
            ["hermes", "kanban", "boards", "create", board_name],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            print(f"  ✓ Created kanban board: {board_name}")
        else:
            print(f"  ✗ Failed to create board: {result.stderr}")
    except subprocess.TimeoutExpired:
        print(f"  ✗ Timeout creating kanban board")
    except FileNotFoundError:
        print(f"  ✗ hermes CLI not found - skipping board creation")


def initialize_topic(topic: str, config: dict) -> None:
    """Initialize a topic with directories and kanban board."""
    print(f"\n{'='*60}")
    print(f"Initializing Research Wiki Factory topic: {topic}")
    print(f"{'='*60}\n")
    
    create_directory_structure(topic, config)
    create_kanban_board(topic)
    
    print(f"\n{'='*60}")
    print(f"Topic '{topic}' initialized successfully!")
    print(f"{'='*60}\n")


def main():
    if len(sys.argv) < 2:
        print("Usage: python wf_init.py <topic>")
        print("Example: python wf_init.py llm-agents")
        sys.exit(1)
    
    topic = sys.argv[1]
    
    # Load configuration
    try:
        config = load_config()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    # Verify topic is in config
    topics = config.get("topics", [])
    if topic not in topics:
        print(f"Warning: Topic '{topic}' not in config topics list")
        print(f"Available topics: {topics}")
        response = input("Continue anyway? (y/n): ")
        if response.lower() != 'y':
            sys.exit(0)
    
    initialize_topic(topic, config)


if __name__ == "__main__":
    main()
