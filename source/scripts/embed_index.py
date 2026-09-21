#!/usr/bin/env python3
"""
embed_index.py - Per-topic embedding cache for research wiki.

Usage:
    python embed_index.py --topic <t> add-paper <citekey>
    python embed_index.py --topic <t> remove-paper <citekey>
    python embed_index.py --topic <t> restore-paper <citekey>
    python embed_index.py --topic <t> status

Features:
- Client: POST to LiteLLM embeddings endpoint with batch size 32
- Storage: _meta/embeddings.npz + _meta/embeddings_meta.json
- Qwen3 retrieval asymmetry: documents raw, queries with prefix
- Commands: add-paper, remove-paper, restore-paper, status
"""

import sys
import os
import json
import argparse
import time
import numpy as np
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from wf_common import load_config, get_wiki_path


# Qwen3 query prefix for retrieval asymmetry
QUERY_PREFIX = "Instruct: Given a research question, retrieve relevant passages that answer the question\nQuery: "


def get_embeddings_path(topic: str, config: dict) -> Tuple[str, str]:
    """Get paths to embeddings.npz and embeddings_meta.json."""
    wiki_path = get_wiki_path(topic, config)
    meta_dir = Path(wiki_path) / "_meta"
    return str(meta_dir / "embeddings.npz"), str(meta_dir / "embeddings_meta.json")


def load_embeddings(embeddings_path: str) -> Tuple[Optional[np.ndarray], List[Dict[str, Any]]]:
    """Load embeddings from disk."""
    npz_path = embeddings_path
    meta_path = embeddings_path.replace(".npz", "_meta.json")
    
    if not Path(npz_path).exists():
        return None, []
    
    # Load vectors
    data = np.load(npz_path)
    vectors = data["vectors"] if "vectors" in data else None
    
    # Load metadata
    if Path(meta_path).exists():
        with open(meta_path, 'r') as f:
            meta = json.load(f)
    else:
        meta = []
    
    return vectors, meta


def save_embeddings(embeddings_path: str, vectors: np.ndarray, meta: List[Dict[str, Any]]) -> None:
    """Save embeddings to disk."""
    npz_path = embeddings_path
    meta_path = embeddings_path.replace(".npz", "_meta.json")
    
    # Save vectors
    np.savez(npz_path, vectors=vectors)
    
    # Save metadata
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """Split text into overlapping chunks."""
    words = text.split()
    chunks = []
    
    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk:
            chunks.append(chunk)
    
    return chunks if chunks else [text]


def embed_batch(
    texts: List[str],
    config: dict,
    is_query: bool = False
) -> np.ndarray:
    """
    Embed a batch of texts using LiteLLM endpoint.
    
    Args:
        texts: List of texts to embed
        config: Configuration dictionary
        is_query: If True, prepend query prefix to each text
    
    Returns:
        numpy array of embeddings (N x D)
    """
    base_url = config.get("litellm", {}).get("base_url", "http://localhost:4000/v1/")
    model = config.get("litellm", {}).get("embedding_model", "qwen3-embedding-8b")
    # Optional auth: config litellm.api_key, else env LITELLM_API_KEY, else none.
    api_key = config.get("litellm", {}).get("api_key") or os.environ.get("LITELLM_API_KEY")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    # Prepare texts
    if is_query:
        texts = [QUERY_PREFIX + text for text in texts]

    # Batch embedding
    batch_size = 32
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]

        # Retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                import requests

                payload = {
                    "model": model,
                    "input": batch
                }

                response = requests.post(
                    f"{base_url}embeddings",
                    json=payload,
                    headers=headers,
                    timeout=60
                )
                response.raise_for_status()
                
                data = response.json()
                embeddings = [item["embedding"] for item in data["data"]]
                all_embeddings.extend(embeddings)
                break
                
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                print(f"  Embedding batch failed (attempt {attempt+1}/{max_retries}): {e}")
                time.sleep(2 ** attempt)  # Exponential backoff
    
    return np.array(all_embeddings, dtype=np.float32)


def normalize_vectors(vectors: np.ndarray) -> np.ndarray:
    """L2-normalize vectors for cosine similarity."""
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1  # Avoid division by zero
    return vectors / norms


def embed_documents(
    texts: List[str],
    config: dict
) -> np.ndarray:
    """Embed documents (raw text, no prefix)."""
    return embed_batch(texts, config, is_query=False)


def embed_query(
    text: str,
    config: dict
) -> np.ndarray:
    """Embed a query (with instruction prefix)."""
    return embed_batch([text], config, is_query=True)


def add_paper(topic: str, citekey: str, config: dict) -> None:
    """
    Add a paper's chunks to the embedding index.
    
    Args:
        topic: Topic name
        citekey: Citekey of the paper
        config: Configuration dictionary
    """
    print(f"\n{'='*60}")
    print(f"Adding paper to embeddings: {citekey}")
    print(f"Topic: {topic}")
    print(f"{'='*60}\n")
    
    # Get paths
    wiki_path = get_wiki_path(topic, config)
    paper_path = Path(wiki_path) / "raw" / "papers" / f"{citekey}.md"
    embeddings_path, meta_path = get_embeddings_path(topic, config)
    
    # Check if paper exists
    if not paper_path.exists():
        print(f"Error: Paper not found: {paper_path}")
        return
    
    # Load paper text
    with open(paper_path, 'r') as f:
        content = f.read()
    
    # Extract text (skip frontmatter)
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            text = parts[2].strip()
        else:
            text = content
    else:
        text = content
    
    # Chunk the text
    chunks = chunk_text(text, chunk_size=500, overlap=50)
    print(f"Split into {len(chunks)} chunks")
    
    # Embed chunks
    print("Embedding chunks...")
    chunk_embeddings = embed_documents(chunks, config)
    print(f"Generated {len(chunk_embeddings)} embeddings")
    
    # L2-normalize
    chunk_embeddings = normalize_vectors(chunk_embeddings)
    
    # Load existing embeddings
    existing_vectors, existing_meta = load_embeddings(embeddings_path)
    
    # Prepare new metadata
    new_meta = []
    for i, chunk in enumerate(chunks):
        new_meta.append({
            "citekey": citekey,
            "chunk_id": i,
            "text": chunk[:200] + "..." if len(chunk) > 200 else chunk,
            "source": "paper",
            "withdrawn": False
        })
    
    # Combine with existing
    if existing_vectors is not None:
        combined_vectors = np.vstack([existing_vectors, chunk_embeddings])
        existing_meta.extend(new_meta)
    else:
        combined_vectors = chunk_embeddings
        existing_meta = new_meta
    
    # Save
    save_embeddings(embeddings_path, combined_vectors, existing_meta)
    
    print(f"Total embeddings: {len(combined_vectors)}")
    print(f"Embeddings saved to: {embeddings_path}")
    print(f"{'='*60}\n")


def remove_paper(topic: str, citekey: str, config: dict) -> None:
    """
    Soft-remove a paper from the embedding index (set withdrawn=True).
    
    Args:
        topic: Topic name
        citekey: Citekey of the paper
        config: Configuration dictionary
    """
    print(f"\n{'='*60}")
    print(f"Removing paper from embeddings: {citekey}")
    print(f"Topic: {topic}")
    print(f"{'='*60}\n")
    
    embeddings_path, meta_path = get_embeddings_path(topic, config)
    
    if not Path(meta_path).exists():
        print("No embeddings found. Nothing to remove.")
        return
    
    vectors, meta = load_embeddings(embeddings_path)
    
    # Mark chunks as withdrawn
    removed_count = 0
    for item in meta:
        if item.get("citekey") == citekey:
            item["withdrawn"] = True
            removed_count += 1
    
    # Save
    save_embeddings(embeddings_path, vectors, meta)
    
    print(f"Marked {removed_count} chunks as withdrawn")
    print(f"{'='*60}\n")


def restore_paper(topic: str, citekey: str, config: dict) -> None:
    """
    Restore a withdrawn paper in the embedding index.
    
    Args:
        topic: Topic name
        citekey: Citekey of the paper
        config: Configuration dictionary
    """
    print(f"\n{'='*60}")
    print(f"Restoring paper in embeddings: {citekey}")
    print(f"Topic: {topic}")
    print(f"{'='*60}\n")
    
    embeddings_path, meta_path = get_embeddings_path(topic, config)
    
    if not Path(meta_path).exists():
        print("No embeddings found. Nothing to restore.")
        return
    
    vectors, meta = load_embeddings(embeddings_path)
    
    # Mark chunks as not withdrawn
    restored_count = 0
    for item in meta:
        if item.get("citekey") == citekey:
            item["withdrawn"] = False
            restored_count += 1
    
    # Save
    save_embeddings(embeddings_path, vectors, meta)
    
    print(f"Restored {restored_count} chunks")
    print(f"{'='*60}\n")


def status(topic: str, config: dict) -> None:
    """
    Print embedding index status.
    
    Args:
        topic: Topic name
        config: Configuration dictionary
    """
    print(f"\n{'='*60}")
    print(f"Embedding Index Status: {topic}")
    print(f"{'='*60}\n")
    
    embeddings_path, meta_path = get_embeddings_path(topic, config)
    
    if not Path(meta_path).exists():
        print("No embeddings found.")
        return
    
    vectors, meta = load_embeddings(embeddings_path)
    
    # Count statistics
    total = len(meta)
    withdrawn = sum(1 for item in meta if item.get("withdrawn", False))
    active = total - withdrawn
    
    # Group by citekey
    citekey_counts: Dict[str, Dict[str, int]] = {}
    for item in meta:
        ck = item.get("citekey", "unknown")
        if ck not in citekey_counts:
            citekey_counts[ck] = {"total": 0, "active": 0, "withdrawn": 0}
        citekey_counts[ck]["total"] += 1
        if item.get("withdrawn", False):
            citekey_counts[ck]["withdrawn"] += 1
        else:
            citekey_counts[ck]["active"] += 1
    
    print(f"Total vectors: {total}")
    print(f"Active vectors: {active}")
    print(f"Withdrawn vectors: {withdrawn}")
    print(f"\nPer-citekey breakdown:")
    
    for ck, counts in sorted(citekey_counts.items()):
        print(f"  {ck}: {counts['total']} chunks ({counts['active']} active, {counts['withdrawn']} withdrawn)")
    
    if vectors is not None:
        print(f"\nVector shape: {vectors.shape}")
        print(f"Vector dtype: {vectors.dtype}")
    
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Embedding Index for Research Wiki")
    parser.add_argument("--topic", required=True, help="Topic name")
    parser.add_argument("command", choices=["add-paper", "remove-paper", "restore-paper", "status"],
                       help="Command to run")
    parser.add_argument("citekey", nargs="?", help="Citekey (for add/remove/restore commands)")
    
    args = parser.parse_args()
    
    # Load configuration
    try:
        config = load_config()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    # Run command
    if args.command == "add-paper":
        if not args.citekey:
            print("Error: citekey required for add-paper command")
            sys.exit(1)
        add_paper(args.topic, args.citekey, config)
    
    elif args.command == "remove-paper":
        if not args.citekey:
            print("Error: citekey required for remove-paper command")
            sys.exit(1)
        remove_paper(args.topic, args.citekey, config)
    
    elif args.command == "restore-paper":
        if not args.citekey:
            print("Error: citekey required for restore-paper command")
            sys.exit(1)
        restore_paper(args.topic, args.citekey, config)
    
    elif args.command == "status":
        status(args.topic, config)


if __name__ == "__main__":
    main()
