#!/usr/bin/env python3
"""
verify_page.py - Verify wiki page claims against embedding index.

Usage:
    python verify_page.py --topic <t> --page <path>

Logic:
1. Split wiki page body into claim units (paragraphs/list items)
2. Skip frontmatter, headings, and verify-report sections
3. Embed each claim as QUERY with instruction prefix
4. Cosine similarity vs ACTIVE paper chunks (withdrawn=false)
5. Claims below 0.65 → "unsupported"
6. Write/refresh report between <!-- verify-report --> markers
7. If unsupported: set frontmatter confidence: low
8. Create kanban card "verify: <pagename>" with idempotency key
9. Exit 0 all supported / 1 unsupported found
"""

import sys
import os
import json
import argparse
import hashlib
import re
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
import numpy as np

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from wf_common import load_config, get_wiki_path
from embed_index import load_embeddings, embed_query, normalize_vectors

# Threshold for supported claims
SUPPORT_THRESHOLD = 0.65


def extract_claims(content: str) -> List[str]:
    """
    Extract claim units from wiki page body.
    
    Skips:
    - Frontmatter (between --- markers)
    - Headings (lines starting with #)
    - verify-report sections (between <!-- verify-report --> and <!-- /verify-report -->)
    
    Returns:
        List of claim paragraphs/list items
    """
    # Remove frontmatter
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            content = parts[2]
    
    # Remove verify-report sections
    content = re.sub(r'<!-- verify-report -->.*?<!-- /verify-report -->', '', content, flags=re.DOTALL)
    
    # Split into paragraphs
    paragraphs = content.split('\n\n')
    
    claims = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
        # Skip headings
        if para.startswith('#'):
            continue
        
        # Skip empty lines or pure whitespace
        if not para:
            continue
        
        # Split list items
        if '\n' in para:
            # Multi-line paragraph - treat each line as potential claim
            lines = para.split('\n')
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#'):
                    claims.append(line)
        else:
            claims.append(para)
    
    return claims


def compute_similarity(query_embedding: np.ndarray, document_vectors: np.ndarray) -> float:
    """Compute max cosine similarity between query and documents."""
    import numpy as np
    
    # document_vectors should already be normalized
    # query_embedding should already be normalized
    similarities = document_vectors @ query_embedding.T
    return float(similarities.max())


def get_active_vectors(embeddings_path: str, meta: List[Dict]) -> Optional[np.ndarray]:
    """Get only active (non-withdrawn) vectors."""
    import numpy as np
    
    if not Path(embeddings_path).exists():
        return None
    
    data = np.load(embeddings_path)
    all_vectors = data["vectors"]
    
    # Filter to active only
    active_indices = [i for i, m in enumerate(meta) if not m.get("withdrawn", False)]
    
    if not active_indices:
        return None
    
    active_vectors = all_vectors[active_indices]
    return normalize_vectors(active_vectors)


def write_verify_report(page_path: str, claims: List[str], results: List[Dict], config: dict) -> Tuple[bool, str]:
    """
    Write verify report to page and update frontmatter.
    
    Returns:
        (all_supported, report_content)
    """
    # Check if all claims are supported
    all_supported = all(r["supported"] for r in results)
    
    # Build report
    report_lines = ["<!-- verify-report -->", "## Verification Report", ""]
    report_lines.append(f"*Verified: {datetime.now().isoformat()}*")
    report_lines.append("")
    
    for i, result in enumerate(results):
        status = "✓ Supported" if result["supported"] else "✗ Unsupported"
        report_lines.append(f"### Claim {i+1}: {status}")
        report_lines.append(f"Similarity: {result['similarity']:.4f}")
        report_lines.append(f"Text: {result['text'][:200]}")
        report_lines.append("")
    
    report_lines.append("<!-- /verify-report -->")
    report_content = "\n".join(report_lines)
    
    # Read current page
    with open(page_path, 'r') as f:
        content = f.read()
    
    # Update or insert report
    if "<!-- verify-report -->" in content:
        # Replace existing report
        content = re.sub(
            r'<!-- verify-report -->.*?<!-- /verify-report -->',
            report_content,
            content,
            flags=re.DOTALL
        )
    else:
        # Insert before end of file
        content = content.rstrip() + "\n\n" + report_content + "\n"
    
    # Update frontmatter confidence if needed
    if not all_supported:
        # Set confidence: low in frontmatter
        if "confidence:" not in content:
            # Add after first --- line
            lines = content.split('\n')
            new_lines = [lines[0]]
            new_lines.append("confidence: low")
            new_lines.extend(lines[1:])
            content = '\n'.join(new_lines)
        else:
            # Replace existing confidence
            content = re.sub(r'^confidence: \w+$', 'confidence: low', content, flags=re.MULTILINE)
    
    # Write updated page
    with open(page_path, 'w') as f:
        f.write(content)
    
    return all_supported, report_content


def compute_page_sha(page_path: str) -> str:
    """Compute SHA1 hash of page body (for idempotency key)."""
    with open(page_path, 'r') as f:
        content = f.read()
    
    # Remove verify-report section for hash computation
    content = re.sub(r'<!-- verify-report -->.*?<!-- /verify-report -->', '', content, flags=re.DOTALL)
    
    return hashlib.sha1(content.encode()).hexdigest()[:12]


def create_verify_card(topic: str, page_name: str, page_path: str, config: dict) -> None:
    """Create kanban card for verification."""
    page_sha = compute_page_sha(page_path)
    idempotency_key = f"verify:{topic}:{page_name}:{page_sha}"
    
    card_title = f"verify: {page_name}"
    card_body = f"""Page: {page_name}
Topic: {topic}
Verified: {datetime.now().isoformat()}

Unsupported claims found. Review and update page.
"""
    
    cmd = [
        "hermes", "kanban", "--board", f"wiki-{topic}",
        "create", card_title,
        "--body", card_body,
        "--idempotency-key", idempotency_key
    ]
    
    print(f"Creating kanban card: {card_title}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Warning: Command failed: {result.stderr}")
    else:
        print(f"  Card created successfully")


def verify_page(topic: str, page_path: str, config: dict) -> int:
    """
    Verify a wiki page against the embedding index.
    
    Args:
        topic: Topic name
        page_path: Path to the wiki page
        config: Configuration dictionary
    
    Returns:
        0 if all claims supported, 1 if unsupported found
    """
    import numpy as np
    
    print(f"\n{'='*60}")
    print(f"Verifying page: {page_path}")
    print(f"Topic: {topic}")
    print(f"{'='*60}\n")
    
    # Read page
    if not Path(page_path).exists():
        print(f"Error: Page not found: {page_path}")
        return 1
    
    with open(page_path, 'r') as f:
        content = f.read()
    
    # Extract claims
    claims = extract_claims(content)
    print(f"Extracted {len(claims)} claims")
    
    if not claims:
        print("No claims to verify. Exiting with success.")
        return 0
    
    # Load embeddings
    wiki_path = get_wiki_path(topic, config)
    embeddings_path = str(Path(wiki_path) / "_meta" / "embeddings.npz")
    meta_path = str(Path(wiki_path) / "_meta" / "embeddings_meta.json")
    
    if not Path(embeddings_path).exists():
        print("Warning: No embeddings found. Cannot verify claims.")
        return 1
    
    vectors, meta = load_embeddings(embeddings_path)
    
    if vectors is None or len(vectors) == 0:
        print("Warning: No vectors in embeddings. Cannot verify claims.")
        return 1
    
    # Get active vectors only
    active_vectors = get_active_vectors(embeddings_path, meta)
    
    if active_vectors is None or len(active_vectors) == 0:
        print("Warning: No active vectors (all withdrawn). Cannot verify claims.")
        return 1
    
    # Embed and verify each claim
    results = []
    
    for claim in claims:
        # Embed claim as query
        query_emb = embed_query(claim, config)
        query_emb = normalize_vectors(query_emb)
        
        # Compute max similarity
        similarity = compute_similarity(query_emb, active_vectors)
        supported = similarity >= SUPPORT_THRESHOLD
        
        results.append({
            "text": claim,
            "similarity": similarity,
            "supported": supported
        })
        
        status = "✓" if supported else "✗"
        print(f"  {status} Claim: {claim[:60]}... (sim: {similarity:.4f})")
    
    # Write report and update frontmatter
    all_supported, report_content = write_verify_report(page_path, claims, results, config)
    
    print(f"\nVerification complete:")
    print(f"  Total claims: {len(claims)}")
    print(f"  Supported: {sum(1 for r in results if r['supported'])}")
    print(f"  Unsupported: {sum(1 for r in results if not r['supported'])}")
    
    if not all_supported:
        # Create kanban card
        page_name = Path(page_path).name
        create_verify_card(topic, page_name, page_path, config)
        
        print(f"\n{'='*60}")
        print("RESULT: Unsupported claims found")
        print(f"{'='*60}\n")
        return 1
    else:
        print(f"\n{'='*60}")
        print("RESULT: All claims supported")
        print(f"{'='*60}\n")
        return 0


def main():
    parser = argparse.ArgumentParser(description="Verify Wiki Page Against Embeddings")
    parser.add_argument("--topic", required=True, help="Topic name")
    parser.add_argument("--page", required=True, help="Path to wiki page")
    
    args = parser.parse_args()
    
    # Load configuration
    try:
        config = load_config()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    # Run verification
    exit_code = verify_page(args.topic, args.page, config)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
