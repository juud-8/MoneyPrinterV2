import os
import sys
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from research_brief import (
    MIN_CITED_SOURCES,
    MIN_CLAIMS,
    build_grounded_research_prompt,
    collect_sources,
    parse_research_brief,
    render_research_notes,
    research_quality_issues,
    search_library_of_congress,
    search_queries_for_topic,
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

    def test_prompt_states_the_thresholds_the_gate_enforces(self):
        prompt = build_grounded_research_prompt("Topic", "niche", self.sources)
        self.assertIn(f"At least {MIN_CLAIMS} distinct claims", prompt)
        self.assertIn(f"at least {MIN_CITED_SOURCES} different source IDs", prompt)

    def test_prompt_never_demands_more_sources_than_were_supplied(self):
        prompt = build_grounded_research_prompt("Topic", "niche", self.sources[:1])
        self.assertIn("at least 1 different source IDs", prompt)

    def test_retry_prompt_reports_the_previous_shortfall(self):
        prompt = build_grounded_research_prompt(
            "Topic",
            "niche",
            self.sources,
            prior_issues=["fewer than 4 source-mapped claims"],
        )
        self.assertIn("previous attempt was rejected", prompt)
        self.assertIn("fewer than 4 source-mapped claims", prompt)

    def test_first_prompt_has_no_retry_feedback(self):
        prompt = build_grounded_research_prompt("Topic", "niche", self.sources)
        self.assertNotIn("previous attempt was rejected", prompt)

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

    def test_collect_sources_prefers_two_domains_over_two_wikipedia_links(self):
        # Downstream gates require two independent domains, so returning early
        # on a pair of Wikipedia links silently blocked every trend opportunity
        # while usable Library of Congress results sat in the same batch.
        wiki = [
            {"provider": "wikipedia", "title": "Steamboat Arabia", "url": "https://en.wikipedia.org/wiki/Arabia", "excerpt": "Steamboat Arabia sank in 1856"},
            {"provider": "wikipedia", "title": "Steamboat Arabia cargo", "url": "https://en.wikipedia.org/wiki/Arabia_cargo", "excerpt": "Steamboat Arabia cargo preserved"},
        ]
        loc = [
            {"provider": "loc", "title": "Steamboat Arabia salvage", "url": "https://www.loc.gov/item/arabia", "excerpt": "Steamboat Arabia salvage record"},
        ]
        with patch("research_brief.search_wikipedia", return_value=wiki), patch(
            "research_brief.search_library_of_congress", return_value=loc
        ):
            result = collect_sources("Steamboat Arabia")

        domains = {urlparse(source["url"]).netloc for source in result}
        self.assertIn("www.loc.gov", domains)
        self.assertGreaterEqual(len(domains), 2)

    def test_collect_sources_still_returns_a_single_domain_topic(self):
        # A topic that genuinely only has one source domain must not come back
        # empty just because breadth is preferred.
        wiki = [
            {"provider": "wikipedia", "title": "Vasa warship", "url": "https://en.wikipedia.org/wiki/Vasa", "excerpt": "The Vasa warship sank in 1628"},
            {"provider": "wikipedia", "title": "Vasa warship museum", "url": "https://en.wikipedia.org/wiki/Vasa_museum", "excerpt": "The Vasa warship was raised in 1961"},
        ]
        with patch("research_brief.search_wikipedia", return_value=wiki), patch(
            "research_brief.search_library_of_congress", return_value=[]
        ):
            result = collect_sources("The Vasa warship sank in 1628")

        self.assertTrue(result)
        self.assertEqual(
            {urlparse(source["url"]).netloc for source in result}, {"en.wikipedia.org"}
        )

    def test_search_queries_add_compact_entity_year_fallback(self):
        topic = (
            "How a single runaway dog sparked a full-scale military invasion "
            "and border war between Greece and Bulgaria in 1925."
        )
        queries = search_queries_for_topic(topic)
        self.assertEqual(queries[0], topic)
        self.assertTrue(any("Greece" in q and "Bulgaria" in q and "1925" in q for q in queries[1:]))

    def test_search_queries_handle_title_case_hooks(self):
        topic = (
            "How 1 Crate of Exploding Vinyl Forced a Major League Baseball "
            "Forfeit on July 12, 1979."
        )
        queries = search_queries_for_topic(topic)
        self.assertEqual(queries[0], topic)
        # Title-case hooks must not dump every capitalized word into the query.
        self.assertFalse(any(q.startswith("Crate Exploding") for q in queries))
        self.assertTrue(
            any(
                "1979" in q
                and ("Baseball" in q or "baseball" in q.lower())
                and ("Forfeit" in q or "forfeit" in q.lower() or "Vinyl" in q or "vinyl" in q.lower())
                for q in queries[1:]
            )
        )

    def test_collect_sources_retries_compact_query_when_full_topic_misses(self):
        topic = (
            "How a single runaway dog sparked a full-scale military invasion "
            "and border war between Greece and Bulgaria in 1925."
        )
        miss = [
            {
                "provider": "wikipedia",
                "title": "List of stories set in a future now in the past",
                "url": "https://wiki/future",
                "excerpt": "Science fiction chronology.",
            }
        ]
        hit = [
            {
                "provider": "wikipedia",
                "title": "Incident at Petrich",
                "url": "https://wiki/petrich",
                "excerpt": (
                    "The Incident at Petrich was a Greek-Bulgarian crisis in 1925 "
                    "after a Greek soldier chased his dog across the border."
                ),
            },
            {
                "provider": "wikipedia",
                "title": "Bulgaria–Greece relations",
                "url": "https://wiki/relations",
                "excerpt": "Relations include the 1925 border war near Petrich.",
            },
        ]

        def fake_wiki(query, limit=3, fetch_json=None):
            return miss if query == topic else hit

        with patch("research_brief.search_wikipedia", side_effect=fake_wiki), patch(
            "research_brief.search_library_of_congress", return_value=[]
        ):
            result = collect_sources(topic)
        self.assertGreaterEqual(len(result), 2)
        self.assertEqual(result[0]["url"], "https://wiki/petrich")

    def test_collect_sources_finds_title_case_baseball_incident(self):
        topic = (
            "How 1 Crate of Exploding Vinyl Forced a Major League Baseball "
            "Forfeit on July 12, 1979."
        )
        miss = []
        hit = [
            {
                "provider": "wikipedia",
                "title": "Disco Demolition Night",
                "url": "https://wiki/disco",
                "excerpt": (
                    "Disco Demolition Night was a Major League Baseball promotion "
                    "on July 12, 1979 that ended in a forfeit after vinyl records exploded."
                ),
            },
            {
                "provider": "wikipedia",
                "title": "Forfeit (baseball)",
                "url": "https://wiki/forfeit",
                "excerpt": "A baseball forfeit in 1979 followed the disco demolition.",
            },
        ]

        def fake_wiki(query, limit=3, fetch_json=None):
            return miss if query == topic else hit

        with patch("research_brief.search_wikipedia", side_effect=fake_wiki), patch(
            "research_brief.search_library_of_congress", return_value=[]
        ):
            result = collect_sources(topic)
        self.assertGreaterEqual(len(result), 2)
        self.assertEqual(result[0]["title"], "Disco Demolition Night")


if __name__ == "__main__":
    unittest.main()
