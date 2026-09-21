#!/usr/bin/env python3
"""
wiki_query_fallback.py - Query wiki with fallback to papers.

Usage:
    python wiki_query_fallback.py --topic <t> --question "<text>"

Logic:
1. Embed question as query
2. If max similarity vs wiki-source vectors >= 0.75: print matching page+excerpt, exit 0
3. Else: get top-5 active paper chunks
4. Print citekey+similarity+snippet
5. Write wikis/<topic>/queries/<slug>.md with frontmatter type: query
6. Exit 2 (fallback to papers)
"""

import sys
import os
import json
import argparse
import re
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from wf_common import load_config, get_wiki_path
from embed_index import load_embeddings, embed_query, normalize_vectors
import numpy as np

# Threshold for wiki match
WIKI_MATCH_THRESHOLD = 0.75


def slugify(text: str) -> str:
    """Convert text to a slug for filename."""
    # Lowercase
    text = text.lower()
    # Replace non-alphanumeric with hyphens
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    # Collapse whitespace
    text = re.sub(r'\s+', '-', text.strip())
    # Limit length
    return text[:50]


def get_wiki_vectors_and_meta(topic: str, config: dict) -> Tuple[Optional[np.ndarray], List[Dict]]:
    """Get wiki-source vectors from embeddings."""
    wiki_path = Path(get_wiki_path(topic, config))
    embeddings_path = str(wiki_path / "_meta" / "embeddings.npz")
    
    if not Path(embeddings_path).exists():
        return None, []
    
    vectors, meta = load_embeddings(embeddings_path)
    
    if vectors is None:
        return None, []
    
    # Filter to wiki sources only
    wiki_indices = [i for i, m in enumerate(meta) if m.get("source") == "wiki" and not m.get("withdrawn", False)]
    
    if not wiki_indices:
        return None, []
    
    wiki_vectors = vectors[wiki_indices]
    wiki_meta = [meta[i] for i in wiki_indices]
    
    # Normalize
    wiki_vectors = normalize_vectors(wiki_vectors)
    
    return wiki_vectors, wiki_meta


def get_paper_vectors_and_meta(topic: str, config: dict) -> Tuple[Optional[np.ndarray], List[Dict]]:
    """Get active paper vectors from embeddings."""
    wiki_path = Path(get_wiki_path(topic, config))
    embeddings_path = str(wiki_path / "_meta" / "embeddings.npz")
    
    if not Path(embeddings_path).exists():
        return None, []
    
    vectors, meta = load_embeddings(embeddings_path)
    
    if vectors is None:
        return None, []
    
    # Filter to paper sources only (active)
    paper_indices = [i for i, m in enumerate(meta) if m.get("source") == "paper" and not m.get("withdrawn", False)]
    
    if not paper_indices:
        return None, []
    
    paper_vectors = vectors[paper_indices]
    paper_meta = [meta[i] for i in paper_indices]
    
    # Normalize
    paper_vectors = normalize_vectors(paper_vectors)
    
    return paper_vectors, paper_meta


def compute_similarities(query_embedding: np.ndarray, document_vectors: np.ndarray) -> np.ndarray:
    """Compute cosine similarities between query and documents."""
    # document_vectors should already be normalized
    # query_embedding should already be normalized
    return (document_vectors @ query_embedding.T).flatten()


def write_query_result(topic: str, question: str, sources: List[Dict], config: dict) -> str:
    """Write query result to queries/<slug>.md."""
    wiki_path = Path(get_wiki_path(topic, config))
    queries_dir = wiki_path / "queries"
    queries_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate slug from question
    slug = slugify(question)
    query_path = queries_dir / f"{slug}.md"
    
    # Build frontmatter
    citekeys = [s["citekey"] for s in sources]
    frontmatter = f"""---
title: "{question[:80]}"
type: query
sources:
{chr(10).join(f'  - {ck}' for ck in citekeys)}
created: {datetime.now().isoformat()}
tags:
  - query
  - {topic}
---

# {question}

## Raw Evidence (Unverified)

"""
    
    # Add source excerpts
    body_lines = []
    for i, source in enumerate(sources):
        body_lines.append(f"### Source {i+1}: {source['citekey']}")
        body_lines.append(f"Similarity: {source['similarity']:.4f}")
        body_lines.append("")
        body_lines.append(f"> {source['snippet'][:500]}")
        body_lines.append("")
    
    content = frontmatter + "\n".join(body_lines)
    
    # Write file
    with open(query_path, 'w') as f:
        f.write(content)
    
    return str(query_path)


def wiki_query(topic: str, question: str, config: dict) -> int:
    """
    Query wiki with fallback to papers.
    
    Args:
        topic: Topic name
        question: Question text
        config: Configuration dictionary
    
    Returns:
        0 if wiki match found, 2 if fallback to papers
    """
    print(f"\n{'='*60}")
    print(f"Query: {question}")
    print(f"Topic: {topic}")
    print(f"{'='*60}\n")
    
    # Embed question
    print("Embedding question...")
    query_emb = embed_query(question, config)
    query_emb = normalize_vectors(query_emb)
    
    # Get wiki vectors
    wiki_vectors, wiki_meta = get_wiki_vectors_and_meta(topic, config)
    
    if wiki_vectors is None or len(wiki_vectors) == 0:
        print("No wiki content found. Falling back to papers.")
        # Fall through to paper search
    else:
        # Compute similarities
        similarities = compute_similarities(query_emb, wiki_vectors)
        max_idx = similarities.argmax()
        max_sim = float(similarities[max_idx])
        
        print(f"Max wiki similarity: {max_sim:.4f}")
        
        if max_sim >= WIKI_MATCH_THRESHOLD:
            # Wiki match found
            match = wiki_meta[max_idx]
            print(f"\n✓ Wiki match found!")
            print(f"Page: {match.get('page', 'unknown')}")
            print(f"Similarity: {max_sim:.4f}")
            print(f"Excerpt: {match['text'][:200]}")
            
            # Write query result
            result = {
                "citekey": match["citekey"],
                "similarity": max_sim,
                "snippet": match["text"]
            }
            query_path = write_query_result(topic, question, [result], config)
            print(f"\nQuery result written to: {query_path}")
            
            print(f"\n{'='*60}")
            print("RESULT: Wiki match found")
            print(f"{'='*60}\n")
            return 0
    
    # Fallback to papers
    print("\nFalling back to papers...")
    paper_vectors, paper_meta = get_paper_vectors_and_meta(topic, config)
    
    if paper_vectors is None or len(paper_vectors) == 0:
        print("No paper content found. Cannot answer question.")
        return 2
    
    # Compute similarities
    similarities = compute_similarities(query_emb, paper_vectors)
    
    # Get top 5
    top_indices = similarities.argsort()[::-1][:5]
    
    top_sources = []
    for idx in top_indices:
        top_sources.append({
            "citekey": paper_meta[idx]["citekey"],
            "similarity": float(similarities[idx]),
            "snippet": paper_meta[idx]["text"]
        })
    
    # Print results
    print("\nTop paper matches:")
    for i, source in enumerate(top_sources):
        print(f"  {i+1}. {source['citekey']} (sim: {source['similarity']:.4f})")
        print(f"     {source['snippet'][:100]}...")
    
    # Write query result
    query_path = write_query_result(topic, question, top_sources, config)
    print(f"\nQuery result written to: {query_path}")
    
    print(f"\n{'='*60}")
    print("RESULT: Fallback to papers (exit 2)")
    print(f"{'='*60}\n")
    return 2


def main():
    parser = argparse.ArgumentParser(description="Wiki Query with Fallback")
    parser.add_argument("--topic", required=True, help="Topic name")
    parser.add_argument("--question", required=True, help="Question text")
    
    args = parser.parse_args()
    
    # Load configuration
    try:
        config = load_config()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    # Run query
    exit_code = wiki_query(args.topic, args.question, config)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
