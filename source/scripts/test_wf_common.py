#!/usr/bin/env python3
"""
Unit tests for PDF-to-Citekey matcher in wf_common.py
"""

import unittest
import tempfile
import os
from pathlib import Path

# Add parent directory to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent))

from wf_common import (
    match_pdf_to_citekey,
    parse_bibtex,
    PDFMatch,
    generate_attanger_filename,
    strip_pdf_filename,
    normalize_text_for_matching
)


class TestPDFToCitekeyMatcher(unittest.TestCase):
    """Test cases for PDF-to-Citekey matching with file field and fuzzy matching."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.pattern_config = {
            "first_creator_suffix": " - ",
            "year_suffix": " - ",
            "title_truncate": 100
        }
    
    def test_exact_match_with_file_field(self):
        """Test exact match using BibTeX file field (Zotero format)."""
        bibtex_entries = {
            "vaswani2017attention": {
                "type": "article",
                "fields": {
                    "title": "Attention Is All You Need",
                    "author": "Vaswani, Ashish and Shazeer, Noam",
                    "year": "2017",
                    "file": "/home/obm/Zotero/storage/ABC/Vaswani - 2017 - Attention Is All You Need.pdf:application/pdf"
                }
            }
        }
        
        pdf_name = "Vaswani - 2017 - Attention Is All You Need.pdf"
        
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, pdf_name)
            Path(pdf_path).touch()
            
            result = match_pdf_to_citekey(
                pdf_path,
                bibtex_entries,
                self.pattern_config
            )
            
            self.assertTrue(result.matched)
            self.assertEqual(result.citekey, "vaswani2017attention")
            self.assertIn("Exact match with file field", result.reason)
    
    def test_fuzzy_match_without_file_field(self):
        """Test fuzzy match when no file field exists (Vaswani 2017)."""
        bibtex_entries = {
            "vaswani2017attention": {
                "type": "article",
                "fields": {
                    "title": "Attention Is All You Need",
                    "author": "Vaswani, Ashish and Shazeer, Noam",
                    "year": "2017"
                }
            }
        }
        
        # PDF with spaces (attanger pattern preserves spaces)
        pdf_name = "Vaswani - 2017 - Attention Is All You Need.pdf"
        
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, pdf_name)
            Path(pdf_path).touch()
            
            result = match_pdf_to_citekey(
                pdf_path,
                bibtex_entries,
                self.pattern_config
            )
            
            self.assertTrue(result.matched)
            self.assertEqual(result.citekey, "vaswani2017attention")
            self.assertIn("Fuzzy match", result.reason)
    
    def test_ambiguous_match(self):
        """Test that ambiguous matches are detected."""
        bibtex_entries = {
            "smith2020paper": {
                "type": "article",
                "fields": {
                    "title": "A Very Similar Title Here",
                    "author": "Smith, John",
                    "year": "2020"
                }
            },
            "smith2020other": {
                "type": "article",
                "fields": {
                    "title": "A Very Similar Title There",
                    "author": "Smith, John",
                    "year": "2020"
                }
            }
        }
        
        pdf_name = "Smith - 2020 - A Very Similar Title.pdf"
        
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, pdf_name)
            Path(pdf_path).touch()
            
            result = match_pdf_to_citekey(
                pdf_path,
                bibtex_entries,
                self.pattern_config
            )
            
            # Should detect ambiguity
            self.assertFalse(result.matched)
            self.assertIsNone(result.citekey)
            self.assertIn("Ambiguous", result.reason)
    
    def test_no_match(self):
        """Test when no matching citekey exists."""
        bibtex_entries = {
            "known2024paper": {
                "type": "article",
                "fields": {
                    "title": "Known Paper Title",
                    "author": "Known, Author",
                    "year": "2024"
                }
            }
        }
        
        pdf_name = "Unknown - 2024 - Different Paper.pdf"
        
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, pdf_name)
            Path(pdf_path).touch()
            
            result = match_pdf_to_citekey(
                pdf_path,
                bibtex_entries,
                self.pattern_config
            )
            
            self.assertFalse(result.matched)
            self.assertIsNone(result.citekey)
            self.assertIn("No matching citekey", result.reason)


class TestNormalizeTextForMatching(unittest.TestCase):
    """Test cases for text normalization."""
    
    def test_lowercase(self):
        """Test lowercase conversion."""
        result = normalize_text_for_matching("Hello World")
        self.assertEqual(result, "hello world")
    
    def test_strip_diacritics(self):
        """Test diacritic stripping."""
        result = normalize_text_for_matching("Café Résumé")
        self.assertEqual(result, "cafe resume")
    
    def test_collapse_non_alphanumeric(self):
        """Test non-alphanumeric collapse."""
        result = normalize_text_for_matching("Hello-World_123!")
        self.assertEqual(result, "helloworld123")
    
    def test_collapse_whitespace(self):
        """Test whitespace collapse."""
        result = normalize_text_for_matching("Hello    World")
        self.assertEqual(result, "hello world")


class TestGenerateAttangerFilename(unittest.TestCase):
    """Test cases for Attanger filename generation."""
    
    def test_basic_generation_with_spaces(self):
        """Test that spaces are preserved (not converted to underscores)."""
        pattern_config = {
            "first_creator_suffix": " - ",
            "year_suffix": " - ",
            "title_truncate": 100
        }
        
        creators = [{"name": "Ashish Vaswani"}]
        title = "Attention Is All You Need"
        year = 2017
        
        result = generate_attanger_filename(
            title, creators, year, pattern_config
        )
        
        # Should have spaces, not underscores
        self.assertEqual(result, "Vaswani - 2017 - Attention Is All You Need")
    
    def test_title_truncation(self):
        """Test that long titles are truncated."""
        pattern_config = {
            "first_creator_suffix": " - ",
            "year_suffix": " - ",
            "title_truncate": 20
        }
        
        creators = [{"name": "Author, Name"}]
        title = "This Is A Very Long Title That Should Be Truncated"
        year = 2024
        
        result = generate_attanger_filename(
            title, creators, year, pattern_config
        )
        
        # Title should be truncated to 20 chars
        self.assertLessEqual(len(result.split(" - ")[-1]), 20)


class TestStripPDFFilename(unittest.TestCase):
    """Test cases for PDF filename stripping."""
    
    def test_remove_path(self):
        """Test path removal."""
        path = "/some/deep/path/to/file.pdf"
        result = strip_pdf_filename(path)
        self.assertEqual(result, "file")
    
    def test_remove_extension(self):
        """Test PDF extension removal."""
        filename = "document.pdf"
        result = strip_pdf_filename(filename)
        self.assertEqual(result, "document")
    
    def test_remove_suffixes(self):
        """Test removal of common suffixes."""
        filename = "Author_-_Title_-.pdf"
        result = strip_pdf_filename(filename)
        self.assertEqual(result, "Author_-_Title")


class TestBibtexParser(unittest.TestCase):
    """Test cases for BibTeX parsing."""
    
    def test_parse_simple_entry(self):
        """Test parsing a simple BibTeX entry."""
        bibtex = """
@article{vaswani2017attention,
  title={Attention Is All You Need},
  author={Vaswani, Ashish and Shazeer, Noam},
  year={2017}
}
"""
        result = parse_bibtex(bibtex)
        
        self.assertIn("vaswani2017attention", result)
        self.assertEqual(result["vaswani2017attention"]["type"], "article")
        self.assertEqual(
            result["vaswani2017attention"]["fields"]["title"],
            "Attention Is All You Need"
        )
    
    def test_parse_multiple_entries(self):
        """Test parsing multiple BibTeX entries."""
        bibtex = """
@article{paper1,
  title={First Paper},
  year={2020}
}
@inproceedings{paper2,
  title={Second Paper},
  year={2021}
}
"""
        result = parse_bibtex(bibtex)
        
        self.assertEqual(len(result), 2)
        self.assertIn("paper1", result)
        self.assertIn("paper2", result)
        self.assertEqual(result["paper1"]["fields"]["year"], "2020")
        self.assertEqual(result["paper2"]["fields"]["year"], "2021")


if __name__ == "__main__":
    unittest.main()
