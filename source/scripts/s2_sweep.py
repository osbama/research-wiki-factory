#!/usr/bin/env python3
"""
s2_sweep.py - Semantic Scholar citation sweep for research topics.

Usage:
    python s2_sweep.py <topic> [--seed-citekeys <key1,key2,...>]

Logic:
1. Resolve seed citekeys to S2 paper IDs
2. Call S2 /paper/{id}/citations with pagination (limit 1000 per seed)
3. Call S2 /recommendations/v1/papers/ with positivePaperIds
4. Filter candidates against existing bib and seen-paperids.json
5. Apply re-offer rules (max once per 30 days, citation count must double)
6. Output: candidates/<topic>-new.bib and kanban cards

Idempotency key format: s2:<paperId>
"""

import sys
import os
import json
import argparse
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Set

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from wf_common import load_config, get_wiki_path, get_zotero_export_path, load_bibtex_file
from wf_common import SemanticScholarClient, extract_first_creator


def get_meta_dir(topic: str, config: dict) -> str:
    """Get the _meta directory path for a topic."""
    wiki_path = get_wiki_path(topic, config)
    return str(Path(wiki_path) / "_meta")


def load_seen_paperids(meta_dir: str) -> Dict[str, Any]:
    """Load seen-paperids.json tracking offered papers."""
    path = Path(meta_dir) / "seen-paperids.json"
    if path.exists():
        with open(path, 'r') as f:
            return json.load(f)
    return {}


def save_seen_paperids(meta_dir: str, data: Dict[str, Any]) -> None:
    """Save seen-paperids.json."""
    path = Path(meta_dir) / "seen-paperids.json"
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def resolve_citekey_to_s2_id(citekey: str, bibtex_entries: dict, s2_client: SemanticScholarClient) -> str:
    """
    Resolve a citekey to an S2 paper ID.
    
    Strategy:
    1. Look for DOI in BibTeX entry
    2. Look for title/author/year and search S2
    """
    entry = bibtex_entries.get(citekey, {})
    fields = entry.get("fields", {})
    
    # Try DOI first (most reliable)
    doi = fields.get("doi", "")
    if doi:
        # S2 accepts DOI as paper ID
        paper_id = doi.replace("https://doi.org/", "")
        print(f"  Using DOI: {paper_id}")
        return paper_id
    
    # Fall back to title search
    title = fields.get("title", "")
    if title:
        print(f"  Searching S2 for title: {title[:60]}...")
        results = s2_client.search_papers(title, limit=1)
        if results:
            paper_id = results[0].get("paperId")
            if paper_id:
                print(f"  Found S2 ID: {paper_id}")
                return paper_id
    
    raise ValueError(f"Could not resolve citekey '{citekey}' to S2 ID")


def fetch_citations_paginated(
    paper_id: str, 
    s2_client: SemanticScholarClient, 
    limit: int = 1000
) -> List[Dict[str, Any]]:
    """Fetch citations for a paper with pagination."""
    print(f"  Fetching citations for {paper_id} (limit: {limit})")
    
    all_citations = []
    offset = 0
    batch_size = 100
    
    while offset < limit:
        params = {
            "limit": min(batch_size, limit - offset),
            "offset": offset,
            "fields": "title,authors,year,abstract,externalIds,citationCount,publicationDate,journal,venue"
        }
        
        try:
            # Use the citations endpoint
            url = f"{s2_client.BASE_URL}/paper/{paper_id}/citations"
            response = s2_client.session.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            citations = data.get("data", [])
            if not citations:
                break
            
            all_citations.extend(citations)
            offset += len(citations)
            
            # Check if there are more pages
            if len(citations) < batch_size:
                break
                
        except Exception as e:
            print(f"  Error fetching citations batch at offset {offset}: {e}")
            break
    
    print(f"  Fetched {len(all_citations)} citations for {paper_id}")
    return all_citations


def fetch_recommendations(
    seed_paper_ids: List[str],
    s2_client: SemanticScholarClient
) -> List[Dict[str, Any]]:
    """Fetch paper recommendations from S2."""
    print(f"  Fetching recommendations for {len(seed_paper_ids)} seed papers")
    
    try:
        url = f"{s2_client.BASE_URL}/recommendations/v1/papers/"
        payload = {"positivePaperIds": seed_paper_ids}
        
        response = s2_client.session.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        
        recommendations = data.get("recommendations", [])
        print(f"  Got {len(recommendations)} recommendations")
        return recommendations
        
    except Exception as e:
        print(f"  Error fetching recommendations: {e}")
        return []


def should_re_offer_paper(
    paper_id: str,
    paper_data: Dict[str, Any],
    seen_paperids: Dict[str, Any]
) -> bool:
    """
    Check if a paper should be re-offered based on rules:
    - Never offered before: always offer
    - Offered before: only if 30+ days passed AND citation count doubled
    """
    if paper_id not in seen_paperids:
        return True
    
    seen_data = seen_paperids[paper_id]
    last_offered = seen_data.get("last_offered")
    old_citation_count = seen_data.get("citation_count", 0)
    new_citation_count = paper_data.get("citationCount", 0)
    
    # Check if 30 days have passed
    if last_offered:
        last_offered_date = datetime.fromisoformat(last_offered)
        days_since_offer = (datetime.now() - last_offered_date).days
        if days_since_offer < 30:
            return False
    
    # Check if citation count has doubled
    if old_citation_count > 0 and new_citation_count < (old_citation_count * 2):
        return False
    
    return True


def format_bibtex_entry(paper: Dict[str, Any]) -> str:
    """Format a paper as BibTeX entry with proper escaping."""
    paper_id = paper.get("paperId", "")
    title = paper.get("title", "Untitled")
    authors = paper.get("authors", [])
    year = paper.get("year", "n.d.")
    abstract = paper.get("abstract", "")
    external_ids = paper.get("externalIds", {})
    doi = external_ids.get("DOI", "")
    venue = paper.get("venue", "")
    citation_count = paper.get("citationCount", 0)
    
    # Generate citekey from first author and year
    if authors:
        first_author = extract_first_creator(authors)
        citekey = f"{first_author}{year}"
    else:
        citekey = f"Unknown{year}"
    
    # Clean citekey
    citekey = citekey.replace(" ", "").replace("'", "").replace("-", "")
    
    # Format authors
    author_str = " and ".join([a.get("name", "Unknown") for a in authors])
    
    # Escape braces in title and abstract
    escaped_title = title.replace("{", "\\{").replace("}", "\\}")
    escaped_abstract = abstract.replace("{", "\\{").replace("}", "\\}") if abstract else ""
    
    # Determine entry type
    entry_type = "inproceedings" if venue and "conference" in venue.lower() else "article"
    
    # Build BibTeX
    bibtex = f"@{entry_type}{{{citekey},\n"
    bibtex += f"  title = {{{escaped_title}}},\n"
    bibtex += f"  author = {{{author_str}}},\n"
    bibtex += f"  year = {{{year}}},\n"
    
    if venue:
        bibtex += f"  journal = {{{venue}}},\n"
    if abstract:
        bibtex += f"  abstract = {{{escaped_abstract}}},\n"
    if doi:
        bibtex += f"  doi = {{{doi}}},\n"
    
    # Add arXiv info if available
    arxiv_id = external_ids.get("ArXiv", "")
    if arxiv_id:
        bibtex += f"  eprint = {{{arxiv_id}}},\n"
        bibtex += f"  archivePrefix = {{arXiv}},\n"
    
    # Add S2 paper ID as note
    bibtex += f"  note = {{S2:{paper_id}}},\n"
    bibtex += f"  citationCount = {{{citation_count}}}\n"
    bibtex += "}\n"
    
    return bibtex, citekey


def create_kanban_card(topic: str, paper: dict, idempotency_key: str) -> None:
    """Create a kanban card for a paper."""
    import subprocess
    
    title = paper.get("title", "Untitled")
    authors = paper.get("authors", [])
    year = paper.get("year", "n.d.")
    citation_count = paper.get("citationCount", 0)
    
    author_str = " and ".join([a.get("name", "Unknown") for a in authors]) if authors else "Unknown"
    
    card_title = f"s2: {title[:80]}"
    card_body = f"""Paper: {title}
Authors: {author_str}
Year: {year}
Citations: {citation_count}
S2 ID: {paper.get('paperId', 'N/A')}

Added via S2 sweep for topic: {topic}
"""
    
    cmd = [
        "hermes", "kanban", "--board", f"wiki-{topic}",
        "create", card_title,
        "--body", card_body,
        "--idempotency-key", idempotency_key
    ]
    
    print(f"  Creating kanban card: {card_title[:50]}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Warning: Command failed: {result.stderr}")
    else:
        print(f"  Card created successfully")


def s2_sweep(topic: str, seed_citekeys: list, config: dict) -> None:
    """
    Perform S2 citation sweep for a topic.
    
    Args:
        topic: Topic name
        seed_citekeys: List of seed citekeys to start from
        config: Configuration dictionary
    """
    print(f"\n{'='*60}")
    print(f"S2 Citation Sweep for topic: {topic}")
    print(f"{'='*60}\n")
    
    # Check for API key
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    if not api_key:
        print("WARNING: SEMANTIC_SCHOLAR_API_KEY not set. Continuing without API key (rate limits may apply).")
    
    # Initialize S2 client
    s2_client = SemanticScholarClient(api_key=api_key)
    
    # Get paths
    meta_dir = get_meta_dir(topic, config)
    Path(meta_dir).mkdir(parents=True, exist_ok=True)
    
    bib_path = get_zotero_export_path(topic, config)
    
    # Load existing bib to filter duplicates
    existing_entries = {}
    if Path(bib_path).expanduser().exists():
        existing_entries = load_bibtex_file(bib_path)
        print(f"Loaded existing bib: {len(existing_entries)} entries")
    
    # Load seen paper IDs
    seen_paperids = load_seen_paperids(meta_dir)
    print(f"Tracking {len(seen_paperids)} previously offered papers")
    
    # Create candidates directory
    candidates_dir = Path("~/research/candidates").expanduser()
    candidates_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = candidates_dir / f"{topic}-new.bib"
    
    # Resolve seed citekeys to S2 IDs
    print(f"\nResolving {len(seed_citekeys)} seed citekeys to S2 IDs...")
    seed_paper_ids = []
    for citekey in seed_citekeys:
        try:
            paper_id = resolve_citekey_to_s2_id(citekey, existing_entries, s2_client)
            seed_paper_ids.append(paper_id)
        except ValueError as e:
            print(f"  Warning: {e}")
    
    if not seed_paper_ids:
        print("No valid seed papers found. Exiting.")
        return
    
    # Collect all candidate papers
    all_candidates: Dict[str, Dict[str, Any]] = {}
    
    # STEP 1: Fetch citations for each seed (with pagination)
    print(f"\nFetching citations for {len(seed_paper_ids)} seed papers...")
    citation_cap = config.get("semantic_scholar", {}).get("citation_cap", 25)
    
    for paper_id in seed_paper_ids:
        try:
            citations = fetch_citations_paginated(paper_id, s2_client, limit=1000)
            for citation in citations:
                cid = citation.get("paperId", "")
                if cid and cid not in all_candidates:
                    all_candidates[cid] = citation
        except Exception as e:
            print(f"  Error fetching citations for {paper_id}: {e}")
    
    print(f"Found {len(all_candidates)} unique citations")
    
    # STEP 2: Fetch recommendations
    print("\nFetching recommendations...")
    recommendations = fetch_recommendations(seed_paper_ids, s2_client)
    for rec in recommendations:
        rid = rec.get("paperId", "")
        if rid and rid not in all_candidates:
            all_candidates[rid] = rec
    
    print(f"Total candidates after recommendations: {len(all_candidates)}")
    
    # STEP 3: Filter and apply re-offer rules
    print("\nFiltering candidates...")
    eligible_papers = []
    
    for paper_id, paper in all_candidates.items():
        # Check if already in existing bib
        if paper_id in [e.get("fields", {}).get("doi", "") for e in existing_entries.values()]:
            print(f"  Skipping {paper_id}: already in bib")
            continue
        
        # Check re-offer rules
        if not should_re_offer_paper(paper_id, paper, seen_paperids):
            print(f"  Skipping {paper_id}: re-offer rules not met")
            continue
        
        eligible_papers.append(paper)
    
    print(f"Eligible papers after filtering: {len(eligible_papers)}")
    
    # Apply per-seed citation cap
    per_seed_cap = config.get("semantic_scholar", {}).get("per_seed_citation_cap", 25)
    if len(eligible_papers) > per_seed_cap * len(seed_paper_ids):
        # Sort by citation count and take top N
        eligible_papers.sort(key=lambda x: x.get("citationCount", 0), reverse=True)
        eligible_papers = eligible_papers[:per_seed_cap * len(seed_paper_ids)]
    
    if not eligible_papers:
        print("No eligible papers to offer. Exiting.")
        return
    
    # STEP 4: Output new candidates as BibTeX
    print(f"\nWriting {len(eligible_papers)} candidates to {candidates_path}")
    with open(candidates_path, 'w') as f:
        for paper in eligible_papers:
            bibtex, citekey = format_bibtex_entry(paper)
            f.write(bibtex)
            f.write("\n")
    
    # STEP 5: Update seen-paperids.json
    now_iso = datetime.now().isoformat()
    for paper in eligible_papers:
        paper_id = paper.get("paperId", "")
        citation_count = paper.get("citationCount", 0)
        
        if paper_id in seen_paperids:
            # Update existing record
            seen_paperids[paper_id]["last_offered"] = now_iso
            seen_paperids[paper_id]["offer_count"] = seen_paperids[paper_id].get("offer_count", 1) + 1
            seen_paperids[paper_id]["citation_count"] = citation_count
        else:
            # Create new record
            seen_paperids[paper_id] = {
                "first_seen": now_iso,
                "last_offered": now_iso,
                "offer_count": 1,
                "citation_count": citation_count
            }
    
    save_seen_paperids(meta_dir, seen_paperids)
    print(f"Updated seen-paperids.json with {len(eligible_papers)} entries")
    
    # STEP 6: Create kanban cards
    print(f"\nCreating {len(eligible_papers)} kanban cards...")
    for paper in eligible_papers:
        paper_id = paper.get("paperId", "")
        idempotency_key = f"s2:{paper_id}"
        create_kanban_card(topic, paper, idempotency_key)
    
    print(f"\n{'='*60}")
    print(f"S2 sweep complete!")
    print(f"Output: {candidates_path}")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="S2 Citation Sweep for Research Topics")
    parser.add_argument("topic", help="Topic name")
    parser.add_argument("--seed-citekeys", help="Comma-separated seed citekeys", default="")
    
    args = parser.parse_args()
    
    # Load configuration
    try:
        config = load_config()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    # Parse seed citekeys
    seed_citekeys = []
    if args.seed_citekeys:
        seed_citekeys = [k.strip() for k in args.seed_citekeys.split(",")]
    
    # Run sweep
    s2_sweep(args.topic, seed_citekeys, config)


if __name__ == "__main__":
    main()
