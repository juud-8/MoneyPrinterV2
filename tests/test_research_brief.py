import os
import sys
import unittest
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from research_brief import (
    collect_sources,
    parse_research_brief,
    render_research_notes,
    research_quality_issues,
    search_library_of_congress,
    search_wikipedia,
)


class ResearchBriefTests(unittest.TestCase):
    def setUp(self):
        self.sources = [
            {"id": "S1", "title": "Source One", "url": "https://one", "excerpt": "One"},
            {"id": "S2", "title": "Source Two", "url": "https://two", "excerpt": "Two"},
        ]

    def test_parse_discards_claims_with_fabricated_source_ids(self):
        raw = """```json
        {
          "summary": "An angle",
          "claims": [
            {"text": "Supported one", "source_ids": ["S1"]},
            {"text": "Unsupported", "source_ids": ["S99"]},
            {"text": "Supported two", "source_ids": ["S1", "S2"]}
          ],
          "disputed_points": ["The exact number varies"],
          "visual_leads": [{"source_id": "S2", "reason": "A map"}]
        }
        ```"""
        brief = parse_research_brief(raw, "Topic", self.sources)
        self.assertEqual([claim["text"] for claim in brief["claims"]], ["Supported one", "Supported two"])
        self.assertEqual(brief["cited_source_ids"], ["S1", "S2"])
        self.assertIn("[S1,S2]", render_research_notes(brief))

    def test_quality_gate_requires_claim_and_source_depth(self):
        brief = {"claims": [{"text": "x", "source_ids": ["S1"]}], "cited_source_ids": ["S1"]}
        issues = research_quality_issues(brief)
        self.assertEqual(len(issues), 2)

    def test_wikipedia_collector_normalizes_pages(self):
        def fake_fetch(url, params, timeout):
            return {"query": {"pages": [{"index": 1, "title": "Event", "fullurl": "https://wiki/event", "extract": "  Useful   excerpt. "}]}}

        result = search_wikipedia("Event", fetch_json=fake_fetch)
        self.assertEqual(result[0]["provider"], "wikipedia")
        self.assertEqual(result[0]["excerpt"], "Useful excerpt.")

    def test_loc_collector_keeps_rights_review_instruction(self):
        def fake_fetch(url, params, timeout):
            return {"results": [{"title": "A map", "id": "https://loc/item", "date": "1866", "description": ["Catalog description"]}]}

        result = search_library_of_congress("Event", fetch_json=fake_fetch)
        self.assertEqual(result[0]["provider"], "library_of_congress")
        self.assertIn("Rights", result[0]["rights"])

    def test_collection_filters_broad_catalog_false_positives(self):
        candidates = [
            {"provider": "x", "title": "History of Liechtenstein", "url": "https://relevant", "excerpt": "Liechtenstein military history"},
            {"provider": "x", "title": "The European War", "url": "https://broad", "excerpt": "A general record of war"},
        ]
        with patch("research_brief.search_wikipedia", return_value=candidates), patch(
            "research_brief.search_library_of_congress", return_value=[]
        ):
            result = collect_sources("Liechtenstein sent 80 soldiers to war")
        self.assertEqual([source["url"] for source in result], ["https://relevant"])


if __name__ == "__main__":
    unittest.main()
