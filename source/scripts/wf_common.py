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


def get_research_root() -> str:
    """Root directory of the deployment (runtime data lives here).

    Resolution order:
    1. WIKI_FACTORY_ROOT environment variable
    2. Default: ~/Prog/research-wiki-factory
    """
    return os.environ.get(
        "WIKI_FACTORY_ROOT",
        str(Path("~/Prog/research-wiki-factory").expanduser())
    )


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load configuration from YAML file.

    Default path: <research_root>/wiki-factory.yaml
    """
    if config_path is None:
        config_path = str(Path(get_research_root()) / "wiki-factory.yaml")
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
        
        # Parse fields (braced values may nest — BBT case protection)
        fields = {}
        field_pattern = (r'(\w+)\s*=\s*(?:"([^"]*)"'
                         r'|{((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)}'
                         r'|(\d+))')
        for field_match in re.finditer(field_pattern, fields_str):
            field_name = field_match.group(1).lower()
            # Get value from capture groups (group 2=quoted, 3=braced, 4=numeric)
            field_value = (field_match.group(2) or field_match.group(3) or 
                          field_match.group(4) or "")
            if field_value:
                # Better BibTeX wraps titles in literal braces for case
                # protection; they are not content
                fields[field_name] = field_value.strip().replace("{", "").replace("}", "")
        
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


DEFAULT_RENAME_TEMPLATE = '{{ firstCreator suffix=" - " }}{{ year suffix=" - " }}{{ title truncate="100" }}'
ILLEGAL_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def _creator_surnames(author_field: str) -> List[str]:
    """BibTeX 'Last, First and Last2, First2' -> ['Last', 'Last2']."""
    return [a.split(",")[0].strip() for a in author_field.split(" and ") if a.strip()]


def _apply_case(value: str, mode: str) -> str:
    if mode == "upper":
        return value.upper()
    if mode == "lower":
        return value.lower()
    if mode == "sentence":
        return value[:1].upper() + value[1:] if value else value
    if mode == "title":
        return value.title()
    if mode == "hyphen":
        return re.sub(r"\s+", "-", value.lower())
    if mode == "snake":
        return re.sub(r"\s+", "_", value.lower())
    if mode == "camel":
        parts = value.split()
        return parts[0].lower() + "".join(p.title() for p in parts[1:]) if parts else value
    if mode == "pascal":
        return "".join(p.title() for p in value.split())
    return value


def render_rename_template(fields: Dict[str, str], template: str, entry_type: str = "") -> str:
    """
    Render a Zotero 7 file-renaming template against a BibTeX entry.
    Supports the documented subset:
      variables: firstCreator, authors, editors, creators, year, title,
                 publicationTitle, itemType, attachmentTitle, plus any
                 BibTeX field by name
      parameters: suffix, prefix, truncate, start, case, max, join,
                  replaceFrom, replaceTo, regexOpts
      conditionals: {{ if var }} ... {{ elseif var }} ... {{ else }} ... {{ endif }}
    Empty variable -> the whole statement (with prefix/suffix) is dropped.
    firstCreator: 1 author -> 'A'; 2 -> 'A and B'; 3+ -> 'A et al.'
    (matches Zotero behaviour; adapted from learn_and_teach zotero_sync.py).
    """
    entry_type = entry_type.lstrip("@").lower()

    def var_value(name: str, params: Dict[str, str]) -> str:
        n = name.strip()
        low = n.lower()
        if low in ("authors", "editors", "creators"):
            names = _creator_surnames(fields.get("author" if low != "editors" else "editor", ""))
            maxn = int(params.get("max", 0) or 0)
            join = params.get("join", ", ")
            if maxn and len(names) > maxn:
                return join.join(names[:maxn])
            return join.join(names)
        if low == "firstcreator":
            names = _creator_surnames(fields.get("author", "") or fields.get("editor", ""))
            if not names:
                return ""
            if len(names) == 1:
                return names[0]
            if len(names) == 2:
                return f"{names[0]} and {names[1]}"
            return f"{names[0]} et al."
        if low == "year":
            return fields.get("year", "") or fields.get("date", "")[:4]
        if low == "title":
            return fields.get("title", "")
        if low == "publicationtitle":
            return fields.get("journal", "") or fields.get("journaltitle", "") or fields.get("booktitle", "")
        if low == "itemtype":
            return entry_type
        if low == "attachmenttitle":
            return ""
        if low.endswith("count"):  # authorsCount etc.: no data from a bare bib
            return "0"
        return fields.get(low, "")

    def render_statement(inner: str) -> str:
        parts = inner.split(None, 1)
        if not parts:
            return ""
        name = parts[0]
        params = dict(re.findall(r'(\w+)="([^"]*)"', parts[1] if len(parts) > 1 else ""))
        value = var_value(name, params)
        if not value:
            return ""  # empty variable: whole statement incl. affixes dropped
        if params.get("replaceFrom"):
            opts = re.I if "i" in params.get("regexOpts", "") else 0
            value = re.sub(params["replaceFrom"], params.get("replaceTo", ""), value, count=1, flags=opts)
        if params.get("start"):
            value = value[int(params["start"]):]
        if params.get("truncate"):
            value = value[:int(params["truncate"])]
        if params.get("case"):
            value = _apply_case(value, params["case"])
        value = value.strip()
        if not value:
            return ""
        return params.get("prefix", "") + value + params.get("suffix", "")

    # Resolve conditionals first (innermost-last simple pass)
    cond_re = re.compile(
        r"\{\{\s*if\s+(\w+)\s*\}\}(.*?)(?:\{\{\s*elseif\s+(\w+)\s*\}\}(.*?))?"
        r"(?:\{\{\s*else\s*\}\}(.*?))?\{\{\s*endif\s*\}\}", re.S)
    def resolve_cond(m):
        for var, body in ((m.group(1), m.group(2)), (m.group(3), m.group(4))):
            if var and var_value(var, {}):
                return body
        return m.group(5) or ""
    prev = None
    while prev != template:
        prev = template
        template = cond_re.sub(resolve_cond, template)

    return re.sub(r"\{\{\s*(.*?)\s*\}\}", lambda m: render_statement(m.group(1)), template)


def get_rename_template(pattern_config: Dict[str, Any]) -> str:
    """Rename template from config; falls back to the Zotero default."""
    return (pattern_config or {}).get("rename_template") or DEFAULT_RENAME_TEMPLATE


def attanger_name(fields: Dict[str, str], template: str, entry_type: str = "") -> str:
    """Render the rename template and sanitize into a legal filename stem."""
    name = render_rename_template(fields, template, entry_type)
    name = ILLEGAL_FILENAME_CHARS.sub("", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def generate_attanger_filename(
    title: str,
    creators: List[Dict[str, Any]],
    year: int,
    pattern_config: Dict[str, Any]
) -> str:
    """
    Generate filename stem by rendering the configured Zotero rename
    template (config key: rename_template). Spaces are preserved.
    `creators` is a list of {'name': ...} dicts (S2-style).
    """
    names = []
    for c in creators or []:
        n = c.get("name", "") if isinstance(c, dict) else str(c)
        if "," in n:
            names.append(n.split(",")[0].strip())
        elif n.strip():
            names.append(n.split()[-1])
    fields = {
        "author": " and ".join(names),
        "year": str(year or ""),
        "title": title or "",
    }
    return attanger_name(fields, get_rename_template(pattern_config))


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
        
        # STRATEGY 2: Fuzzy match via rendered rename template
        pdf_normalized = normalize_text_for_matching(pdf_basename)

        # Expected name = the template Zotero/attanger would have produced
        expected_name = attanger_name(fields, get_rename_template(pattern_config),
                                      entry.get("type", ""))
        expected_normalized = normalize_text_for_matching(expected_name)

        # Calculate similarity
        similarity = difflib.SequenceMatcher(None, pdf_normalized, expected_normalized).ratio()

        # Also check author-year prefix match (firstCreator + year stem)
        year = fields.get("year", "") or fields.get("date", "")[:4]
        fc_names = _creator_surnames(fields.get("author", "") or fields.get("editor", ""))
        if len(fc_names) == 1:
            first_creator = fc_names[0]
        elif len(fc_names) == 2:
            first_creator = f"{fc_names[0]} and {fc_names[1]}"
        elif len(fc_names) > 2:
            first_creator = f"{fc_names[0]} et al."
        else:
            first_creator = ""
        author_year_match = bool(first_creator) and pdf_normalized.startswith(
            normalize_text_for_matching(f"{first_creator} - {year}"))
        
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
    exports_dir = config.get("zotero", {}).get(
        "exports_dir", str(Path(get_research_root()) / "zotero" / "exports"))
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
    base_dir = config.get("inbox", {}).get(
        "base_dir", str(Path(get_research_root()) / "inbox"))
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
    base_dir = config.get("wiki", {}).get(
        "base_dir", str(Path(get_research_root()) / "wikis"))
    return str(Path(base_dir).expanduser() / topic)
