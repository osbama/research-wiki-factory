"""
wf_common.py - Shared utilities for Research Wiki Factory

Provides:
- Config loader
- Semantic Scholar client with exponential backoff
- BibTeX parser
- PDF-to-Citekey matcher using Attanger pattern
"""

import os
import re
import time
import unicodedata
import difflib
import yaml
import requests
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass


@dataclass
class PDFMatch:
    """Result of matching a PDF to a citekey."""
    pdf_path: str
    citekey: Optional[str]
    matched: bool
    reason: str = ""


def load_config(config_path: str = "~/research/wiki-factory.yaml") -> Dict[str, Any]:
    """Load configuration from YAML file."""
    path = Path(config_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    
    with open(path, 'r') as f:
        return yaml.safe_load(f)


class SemanticScholarClient:
    """Semantic Scholar API client with exponential backoff."""
    
    BASE_URL = "https://api.semanticscholar.org/graph/v1"
    MAX_RETRIES = 3
    INITIAL_DELAY = 1.0
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.session = requests.Session()
        if api_key:
            self.session.headers.update({"x-api-key": api_key})
    
    def _request_with_backoff(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make API request with exponential backoff."""
        url = f"{self.BASE_URL}{endpoint}"
        delay = self.INITIAL_DELAY
        
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.session.get(url, params=params)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                if attempt == self.MAX_RETRIES - 1:
                    raise
                time.sleep(delay)
                delay *= 2
        
        return {}
    
    def search_papers(self, query: str, limit: int = 25) -> List[Dict[str, Any]]:
        """Search for papers by query."""
        params = {
            "query": query,
            "limit": limit,
            "fields": "title,authors,year,abstract,citationCount,externalIds"
        }
        result = self._request_with_backoff("/paper/search", params)
        return result.get("data", [])
    
    def get_paper(self, paper_id: str) -> Dict[str, Any]:
        """Get paper details by ID."""
        params = {"fields": "title,authors,year,abstract,citationCount,externalIds,references"}
        return self._request_with_backoff(f"/paper/{paper_id}", params)


def parse_bibtex(bibtex_content: str) -> Dict[str, Dict[str, str]]:
    """
    Parse BibTeX content into a dictionary.
    
    Returns:
        Dict mapping citekeys to entry dictionaries
    """
    entries = {}
    # Simple BibTeX parser - handles common cases
    # Match entry start and find balanced braces
    pattern = r'@(\w+)\{([^,]+),\s*'
    
    for match in re.finditer(pattern, bibtex_content):
        entry_type = match.group(1).lower()
        citekey = match.group(2).strip()
        
        # Find the matching closing brace
        start_pos = match.end()
        brace_count = 1
        end_pos = start_pos
        
        for i in range(start_pos, len(bibtex_content)):
            char = bibtex_content[i]
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_pos = i
                    break
        
        fields_str = bibtex_content[start_pos:end_pos]
        
        # Parse fields
        fields = {}
        field_pattern = r'(\w+)\s*=\s*(?:"([^"]*)"|{([^}]*)}|(\d+))'
        for field_match in re.finditer(field_pattern, fields_str):
            field_name = field_match.group(1).lower()
            # Get value from capture groups (group 2=quoted, 3=braced, 4=numeric)
            field_value = (field_match.group(2) or field_match.group(3) or 
                          field_match.group(4) or "")
            if field_value:
                fields[field_name] = field_value.strip()
        
        entries[citekey] = {
            "type": entry_type,
            "fields": fields
        }
    
    return entries


def load_bibtex_file(bibtex_path: str) -> Dict[str, Dict[str, str]]:
    """Load and parse a BibTeX file."""
    path = Path(bibtex_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"BibTeX file not found: {path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        return parse_bibtex(f.read())


def normalize_text_for_matching(text: str) -> str:
    """
    Normalize text for fuzzy matching.
    
    Steps:
    1. Convert to lowercase
    2. Strip diacritics using NFKD normalization
    3. Collapse non-alphanumeric characters
    """
    # Lowercase
    text = text.lower()
    # Strip diacritics
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    # Collapse non-alphanumeric
    text = re.sub(r'[^a-z0-9\s]', '', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_first_creator(authors: List[Dict[str, Any]]) -> str:
    """Extract first author's last name from authors list."""
    if not authors:
        return "Unknown"
    
    first_author = authors[0]
    # Handle both dict and string author formats
    if isinstance(first_author, dict):
        name = first_author.get("name", "Unknown")
        # Handle "Last, First" format
        if "," in name:
            return name.split(",")[0].strip()
        return name.split()[-1]
    return str(first_author).split()[-1]


def generate_attanger_filename(
    title: str,
    creators: List[Dict[str, Any]],
    year: int,
    pattern_config: Dict[str, Any]
) -> str:
    """
    Generate filename using Attanger pattern.
    
    Pattern: {{ firstCreator suffix=' - ' }}{{ year suffix=' - ' }}{{ title truncate='100' }}
    Note: Spaces are preserved (not converted to underscores).
    """
    first_creator = extract_first_creator(creators)
    suffix1 = pattern_config.get("first_creator_suffix", " - ")
    suffix2 = pattern_config.get("year_suffix", " - ")
    truncate_len = pattern_config.get("title_truncate", 100)
    
    # Truncate title
    truncated_title = title[:truncate_len] if len(title) > truncate_len else title
    
    # Sanitize for filename (remove special chars but preserve spaces)
    sanitized_title = re.sub(r'[^\w\s\-]', '', truncated_title)
    # Do NOT convert spaces to underscores - attanger preserves spaces
    # sanitized_title = re.sub(r'\s+', '_', sanitized_title)  # REMOVED
    
    return f"{first_creator}{suffix1}{year}{suffix2}{sanitized_title}"


def strip_pdf_filename(filename: str) -> str:
    """
    Strip PDF filename to extract citekey-like pattern.
    
    Handles Zotero 'file' field format which may include:
    - Full path
    - PDF extension
    - Multiple underscores/dashes
    """
    # Remove path
    basename = os.path.basename(filename)
    
    # Remove .pdf extension
    if basename.endswith('.pdf'):
        basename = basename[:-4]
    
    # Remove common suffixes
    basename = re.sub(r'_-\s*$', '', basename)
    basename = re.sub(r'^\d+[-_]', '', basename)
    
    return basename


def match_pdf_to_citekey(
    pdf_path: str,
    bibtex_entries: Dict[str, Dict[str, str]],
    pattern_config: Dict[str, Any]
) -> PDFMatch:
    """
    Match a PDF file to a BibTeX citekey.
    
    Matching precedence:
    1. If bib entry has a "file" field, strip to basename and compare exactly
    2. Fuzzy match: normalize and compare first-author surname + year, then title
    3. Ambiguity detection: if two candidates score within 0.05, return matched=False
    
    Args:
        pdf_path: Path to the PDF file
        bibtex_entries: Dictionary of citekeys to entry data
        pattern_config: Attanger pattern configuration
    
    Returns:
        PDFMatch result
    """
    pdf_basename = os.path.basename(pdf_path)
    if pdf_basename.endswith('.pdf'):
        pdf_basename = pdf_basename[:-4]
    
    candidates = []  # List of (citekey, score, reason) tuples
    
    for citekey, entry in bibtex_entries.items():
        fields = entry.get("fields", {})
        
        # STRATEGY 1: Check "file" field first (highest priority)
        file_field = fields.get("file", "")
        if file_field:
            # Handle Zotero format: "path.pdf:application/pdf" or multiple files separated by ;
            file_entries = file_field.split(";")
            for file_entry in file_entries:
                # Extract path from "path.pdf:application/pdf" format
                file_path = file_entry.split(":")[0] if ":" in file_entry else file_entry
                file_basename = os.path.basename(file_path)
                if file_basename.endswith('.pdf'):
                    file_basename = file_basename[:-4]
                
                # Exact basename comparison (case-sensitive)
                if pdf_basename == file_basename:
                    return PDFMatch(
                        pdf_path=pdf_path,
                        citekey=citekey,
                        matched=True,
                        reason=f"Exact match with file field: {file_basename}"
                    )
        
        # STRATEGY 2: Fuzzy match on author + title
        title = fields.get("title", "")
        year = fields.get("year", "")
        author = fields.get("author", "Unknown").split(" and ")[0].split(",")[0].strip()
        
        # Normalize both for comparison
        pdf_normalized = normalize_text_for_matching(pdf_basename)
        
        # Build expected pattern (with SPACES preserved, not underscores)
        first_creator = author
        suffix1 = pattern_config.get("first_creator_suffix", " - ")
        suffix2 = pattern_config.get("year_suffix", " - ")
        truncate_len = pattern_config.get("title_truncate", 100)
        
        truncated_title = title[:truncate_len] if len(title) > truncate_len else title
        # Preserve spaces in attanger pattern
        expected_name = f"{first_creator}{suffix1}{year}{suffix2}{truncated_title}"
        expected_normalized = normalize_text_for_matching(expected_name)
        
        # Calculate similarity
        similarity = difflib.SequenceMatcher(None, pdf_normalized, expected_normalized).ratio()
        
        # Also check author-year prefix match
        author_year_match = pdf_normalized.startswith(normalize_text_for_matching(f"{first_creator}{suffix1}{year}"))
        
        if similarity >= 0.85 or author_year_match:
            candidates.append((citekey, similarity, f"Fuzzy match (similarity: {similarity:.2f})"))
    
    # Handle results
    if not candidates:
        return PDFMatch(
            pdf_path=pdf_path,
            citekey=None,
            matched=False,
            reason="No matching citekey found"
        )
    
    # Sort by score descending
    candidates.sort(key=lambda x: x[1], reverse=True)
    
    # Check for ambiguity (top two within 0.05)
    if len(candidates) >= 2 and (candidates[0][1] - candidates[1][1]) < 0.05:
        return PDFMatch(
            pdf_path=pdf_path,
            citekey=None,
            matched=False,
            reason=f"Ambiguous match: multiple candidates with similar scores: {candidates[0][0]} ({candidates[0][1]:.2f}), {candidates[1][0]} ({candidates[1][1]:.2f})"
        )
    
    # Return best match
    best_citekey, score, reason = candidates[0]
    return PDFMatch(
        pdf_path=pdf_path,
        citekey=best_citekey,
        matched=True,
        reason=reason
    )


def get_zotero_export_path(topic: str, config: Dict[str, Any]) -> str:
    """Get the path to Zotero export file for a topic."""
    exports_dir = config.get("zotero", {}).get("exports_dir", "~/research/zotero/exports")
    return str(Path(exports_dir).expanduser() / f"wiki-{topic}.bib")


def get_inbox_path(topic: str, config: Dict[str, Any]) -> str:
    """Get the inbox directory path for a topic.

    Per-topic override wins: topics as a mapping can set `inbox:` per topic
    (e.g. one shared big-PDF-library dir for every topic). Falls back to
    inbox.base_dir/<topic>.
    """
    topics_cfg = config.get("topics", [])
    if isinstance(topics_cfg, dict):
        topic_entry = topics_cfg.get(topic, {}) or {}
        if isinstance(topic_entry, dict) and topic_entry.get("inbox"):
            return str(Path(topic_entry["inbox"]).expanduser())
    elif isinstance(topics_cfg, list):
        for item in topics_cfg:
            if isinstance(item, dict) and item.get("name") == topic and item.get("inbox"):
                return str(Path(item["inbox"]).expanduser())
    base_dir = config.get("inbox", {}).get("base_dir", "~/research/inbox")
    return str(Path(base_dir).expanduser() / topic)


def get_topics(config: Dict[str, Any]) -> List[str]:
    """Return the list of topic names from config (list or mapping form)."""
    topics_cfg = config.get("topics", [])
    if isinstance(topics_cfg, dict):
        return list(topics_cfg.keys())
    names = []
    for item in topics_cfg:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict) and "name" in item:
            names.append(item["name"])
    return names


def get_wiki_path(topic: str, config: Dict[str, Any]) -> str:
    """Get the wiki directory path for a topic."""
    base_dir = config.get("wiki", {}).get("base_dir", "~/research/wikis")
    return str(Path(base_dir).expanduser() / topic)
