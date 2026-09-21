#!/usr/bin/env python3
"""
coverage_audit.py - Audit embedding coverage of wiki pages.

Usage:
    python coverage_audit.py --topic <t>

Logic:
1. For each ACTIVE paper chunk, compute max cosine vs wiki-source vectors
2. Wiki pages embedded as documents (citekey="wiki:<pagename>", source="wiki")
3. Cache wiki embeddings in same npz file
4. Chunks below 0.60 = uncovered
5. Report to wikis/<topic>/_meta/coverage-report.md
6. Create kanban card "coverage-audit: <topic>" with top-10 gaps
"""

import sys
import os
import json
import argparse
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from wf_common import load_config, get_wiki_path
from embed_index import load_embeddings, save_embeddings, embed_documents, normalize_vectors
import numpy as np

# Threshold for coverage
COVERAGE_THRESHOLD = 0.60


def get_wiki_pages(topic: str, config: dict) -> List[Path]:
    """Get all wiki pages (excluding _meta, raw, _archive)."""
    wiki_path = Path(get_wiki_path(topic, config))
    
    # Directories to scan
    dirs_to_scan = ["concepts", "comparisons", "queries", "entities"]
    
    pages = []
    for dir_name in dirs_to_scan:
        dir_path = wiki_path / dir_name
        if dir_path.exists():
            pages.extend(dir_path.glob("*.md"))
    
    return pages


def extract_page_content(page_path: Path) -> List[str]:
    """Extract paragraphs from a wiki page for embedding."""
    with open(page_path, 'r') as f:
        content = f.read()
    
    # Remove frontmatter
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            content = parts[2]
    
    # Remove verify-report sections
    import re
    content = re.sub(r'<!-- verify-report -->.*?<!-- /verify-report -->', '', content, flags=re.DOTALL)
    
    # Split into paragraphs
    paragraphs = content.split('\n\n')
    
    # Filter to meaningful paragraphs
    chunks = []
    for para in paragraphs:
        para = para.strip()
        if para and not para.startswith('#'):
            chunks.append(para)
    
    return chunks


def embed_wiki_pages(topic: str, config: dict) -> Tuple[np.ndarray, List[Dict]]:
    """Embed all wiki pages and return vectors + metadata."""
    pages = get_wiki_pages(topic, config)
    
    all_chunks = []
    all_meta = []
    
    for page_path in pages:
        chunks = extract_page_content(page_path)
        page_name = page_path.stem
        
        for i, chunk in enumerate(chunks):
            all_chunks.append(chunk)
            all_meta.append({
                "citekey": f"wiki:{page_name}",
                "chunk_id": i,
                "text": chunk[:200] + "..." if len(chunk) > 200 else chunk,
                "source": "wiki",
                "page": page_name,
                "withdrawn": False
            })
    
    if not all_chunks:
        return np.array([]).reshape(0, 4096), []
    
    # Embed chunks
    print(f"Embedding {len(all_chunks)} wiki page chunks...")
    embeddings = embed_documents(all_chunks, config)
    embeddings = normalize_vectors(embeddings)
    
    return embeddings, all_meta


def compute_coverage(
    paper_vectors: np.ndarray,
    paper_meta: List[Dict],
    wiki_vectors: np.ndarray,
    wiki_meta: List[Dict]
) -> List[Dict]:
    """
    Compute coverage for each paper chunk.
    
    Returns:
        List of coverage results (citekey, similarity, uncovered flag, snippet)
    """
    results = []
    
    if len(wiki_vectors) == 0:
        # No wiki content - all chunks are uncovered
        for i, meta in enumerate(paper_meta):
            if not meta.get("withdrawn", False):
                results.append({
                    "citekey": meta["citekey"],
                    "chunk_id": meta["chunk_id"],
                    "similarity": 0.0,
                    "uncovered": True,
                    "snippet": meta["text"]
                })
        return results
    
    # Compute max similarity for each paper chunk
    for i, meta in enumerate(paper_meta):
        if meta.get("withdrawn", False):
            continue
        
        vector = paper_vectors[i:i+1]  # Keep dimension
        similarities = wiki_vectors @ vector.T
        max_sim = float(similarities.max())
        
        results.append({
            "citekey": meta["citekey"],
            "chunk_id": meta["chunk_id"],
            "similarity": max_sim,
            "uncovered": max_sim < COVERAGE_THRESHOLD,
            "snippet": meta["text"]
        })
    
    return results


def write_coverage_report(topic: str, results: List[Dict], config: dict) -> str:
    """Write coverage report to _meta/coverage-report.md."""
    wiki_path = Path(get_wiki_path(topic, config))
    report_path = wiki_path / "_meta" / "coverage-report.md"
    
    # Count uncovered
    uncovered_count = sum(1 for r in results if r["uncovered"])
    total_count = len(results)
    
    # Build report
    report_lines = [
        "# Coverage Audit Report",
        "",
        f"*Generated: {datetime.now().isoformat()}*",
        "",
        f"## Summary",
        "",
        f"- Total paper chunks: {total_count}",
        f"- Covered chunks: {total_count - uncovered_count}",
        f"- Uncovered chunks: {uncovered_count}",
        f"- Coverage rate: {(total_count - uncovered_count) / total_count * 100:.1f}%" if total_count > 0 else "- Coverage rate: N/A",
        "",
        "## Uncovered Chunks",
        ""
    ]
    
    # Group by citekey
    uncovered_by_citekey: Dict[str, List[Dict]] = {}
    for r in results:
        if r["uncovered"]:
            ck = r["citekey"]
            if ck not in uncovered_by_citekey:
                uncovered_by_citekey[ck] = []
            uncovered_by_citekey[ck].append(r)
    
    if not uncovered_by_citekey:
        report_lines.append("*All chunks are covered by wiki content.*")
    else:
        for citekey, chunks in sorted(uncovered_by_citekey.items()):
            uncovered_pct = len(chunks) / sum(1 for r in results if r["citekey"] == citekey) * 100
            report_lines.append(f"### {citekey}")
            report_lines.append(f"Uncovered: {uncovered_pct:.1f}%")
            report_lines.append("")
            
            for chunk in chunks[:3]:  # Show first 3 uncovered chunks
                report_lines.append(f"**Chunk {chunk['chunk_id']}** (sim: {chunk['similarity']:.4f})")
                report_lines.append(f"> {chunk['snippet'][:200]}")
                report_lines.append("")
    
    report_content = "\n".join(report_lines)
    
    # Write report
    with open(report_path, 'w') as f:
        f.write(report_content)
    
    return report_content


def create_coverage_card(topic: str, results: List[Dict], config: dict) -> None:
    """Create kanban card for coverage audit."""
    import subprocess
    
    # Get top 10 gaps
    uncovered = [r for r in results if r["uncovered"]]
    uncovered.sort(key=lambda x: x["similarity"])
    top_10 = uncovered[:10]
    
    # Build card body
    card_body = f"""Coverage Audit: {topic}
Generated: {datetime.now().isoformat()}

## Summary
- Total chunks: {len(results)}
- Uncovered: {len(uncovered)}
- Coverage: {(len(results) - len(uncovered)) / len(results) * 100:.1f}%

## Top Gaps
"""
    
    for r in top_10:
        card_body += f"- **{r['citekey']}** (chunk {r['chunk_id']}, sim: {r['similarity']:.4f})\n"
        card_body += f"  > {r['snippet'][:100]}...\n"
    
    # Idempotency key with date
    today = datetime.now().strftime("%Y-%m-%d")
    idempotency_key = f"coverage:{topic}:{today}"
    
    cmd = [
        "hermes", "kanban", "--board", f"wiki-{topic}",
        "create", f"coverage-audit: {topic}",
        "--body", card_body,
        "--idempotency-key", idempotency_key
    ]
    
    print(f"Creating kanban card: coverage-audit: {topic}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Warning: Command failed: {result.stderr}")
    else:
        print(f"  Card created successfully")


def coverage_audit(topic: str, config: dict) -> None:
    """
    Perform coverage audit for a topic.
    
    Args:
        topic: Topic name
        config: Configuration dictionary
    """
    print(f"\n{'='*60}")
    print(f"Coverage Audit: {topic}")
    print(f"{'='*60}\n")
    
    wiki_path = Path(get_wiki_path(topic, config))
    embeddings_path = str(wiki_path / "_meta" / "embeddings.npz")
    meta_path = str(wiki_path / "_meta" / "embeddings_meta.json")
    
    # Load existing embeddings
    if not Path(embeddings_path).exists():
        print("No embeddings found. Run embed_index.py first.")
        return
    
    vectors, meta = load_embeddings(embeddings_path)
    
    if vectors is None or len(vectors) == 0:
        print("No vectors in embeddings. Cannot perform audit.")
        return
    
    # Separate paper vectors from wiki vectors
    paper_indices = [i for i, m in enumerate(meta) if m.get("source") == "paper" and not m.get("withdrawn", False)]
    
    if not paper_indices:
        print("No active paper chunks. Nothing to audit.")
        return
    
    paper_vectors = vectors[paper_indices]
    paper_meta = [meta[i] for i in paper_indices]
    
    print(f"Found {len(paper_vectors)} active paper chunks")
    
    # Embed wiki pages
    wiki_vectors, wiki_meta = embed_wiki_pages(topic, config)
    print(f"Embedding {len(wiki_vectors)} wiki page chunks...")
    print(f"Embedded {len(wiki_vectors)} wiki page chunks")
    
    # Save wiki embeddings to the same npz file
    if len(wiki_vectors) > 0:
        print("Saving wiki embeddings to index...")
        # Combine with existing paper vectors
        combined_vectors = np.vstack([vectors, wiki_vectors])
        combined_meta = meta + wiki_meta
        save_embeddings(embeddings_path, combined_vectors, combined_meta)
        print(f"Total vectors after save: {len(combined_vectors)}")
    
    # Compute coverage
    print("\nComputing coverage...")
    results = compute_coverage(paper_vectors, paper_meta, wiki_vectors, wiki_meta)
    
    uncovered_count = sum(1 for r in results if r["uncovered"])
    print(f"Uncovered chunks: {uncovered_count} / {len(results)}")
    
    # Write report
    report_content = write_coverage_report(topic, results, config)
    print(f"\nCoverage report written to: {wiki_path / '_meta' / 'coverage-report.md'}")
    
    # Create kanban card if there are uncovered chunks
    if uncovered_count > 0:
        create_coverage_card(topic, results, config)
    
    print(f"\n{'='*60}")
    print("Coverage audit complete!")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Coverage Audit for Research Wiki")
    parser.add_argument("--topic", required=True, help="Topic name")
    
    args = parser.parse_args()
    
    # Load configuration
    try:
        config = load_config()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    # Run audit
    coverage_audit(args.topic, config)


if __name__ == "__main__":
    main()
