"""Tests for skill_doc_extractor module."""
from __future__ import annotations

import json
import unittest
from netweaver.skill_doc_extractor import (
    extract_skill_doc,
    extract_skill_metadata,
    remove_skill_doc,
    has_skill_doc,
)


class TestSkillDocExtraction(unittest.TestCase):
    """Test skill doc extraction functions."""
    
    def test_extract_skill_doc_with_markers(self):
        prompt = "Before<<<SKILL_DOC_START>>>Content<<<SKILL_DOC_END>>>After"
        result = extract_skill_doc(prompt)
        self.assertEqual(result, "Content")
    
    def test_extract_skill_doc_multiline(self):
        content = "Line 1\nLine 2\nLine 3"
        prompt = f"<<<SKILL_DOC_START>>>{content}<<<SKILL_DOC_END>>>"
        result = extract_skill_doc(prompt)
        self.assertEqual(result, content)
    
    def test_extract_skill_doc_no_markers(self):
        prompt = "No skill doc here"
        result = extract_skill_doc(prompt)
        self.assertIsNone(result)
    
    def test_extract_skill_doc_empty(self):
        prompt = "<<<SKILL_DOC_START>>><<<SKILL_DOC_END>>>"
        with self.assertRaises(ValueError):
            extract_skill_doc(prompt)
    
    def test_extract_skill_metadata_json(self):
        metadata = {"skill": "test", "version": 1}
        prompt = f"<<<SKILL_DOC_START>>>{json.dumps(metadata)}<<<SKILL_DOC_END>>>"
        result = extract_skill_metadata(prompt)
        self.assertEqual(result, metadata)
    
    def test_extract_skill_metadata_raw(self):
        content = "Raw skill doc content"
        prompt = f"<<<SKILL_DOC_START>>>{content}<<<SKILL_DOC_END>>>"
        result = extract_skill_metadata(prompt)
        self.assertEqual(result, {"raw_doc": content})
    
    def test_remove_skill_doc(self):
        prompt = "Before<<<SKILL_DOC_START>>>Remove me<<<SKILL_DOC_END>>>After"
        result = remove_skill_doc(prompt)
        self.assertEqual(result, "Before After")
    
    def test_has_skill_doc_true(self):
        prompt = "<<<SKILL_DOC_START>>>Exists<<<SKILL_DOC_END>>>"
        self.assertTrue(has_skill_doc(prompt))
    
    def test_has_skill_doc_false(self):
        prompt = "No markers here"
        self.assertFalse(has_skill_doc(prompt))


class TestSkillDocEdgeCases(unittest.TestCase):
    """Test edge cases and custom markers."""
    
    def test_custom_markers(self):
        prompt = "Start--CONTENT--End"
        result = extract_skill_doc(prompt, start_tag="Start--", end_tag="--End")
        self.assertEqual(result, "CONTENT")
    
    def test_multiple_skill_docs(self):
        prompt = "First<<<SKILL_DOC_START>>>Doc1<<<SKILL_DOC_END>>>Middle<<<SKILL_DOC_START>>>Doc2<<<SKILL_DOC_END>>>"
        # Should extract first occurrence
        result = extract_skill_doc(prompt)
        self.assertEqual(result, "Doc1")
    
    def test_large_content(self):
        # Test with content similar to 25K tokens (approx 100K chars)
        content = "A" * 100000
        prompt = f"<<<SKILL_DOC_START>>>{content}<<<SKILL_DOC_END>>>"
        result = extract_skill_doc(prompt)
        self.assertEqual(len(result), 100000)


if __name__ == "__main__":
    unittest.main()