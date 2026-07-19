import os
import sys
import unittest
from unittest.mock import patch

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import trend_discovery  # noqa: E402


class TrendDiscoveryTests(unittest.TestCase):
    def test_happy_path_ranks_and_filters_candidates(self):
        responses = iter(
            [
                "weird history\nstrange facts",  # seed queries from niche
                "the dancing plague\nhaunted lighthouse",  # ranked candidates
            ]
        )
        with patch.object(trend_discovery, "generate_text", side_effect=lambda *a, **k: next(responses)), \
            patch.object(
                trend_discovery,
                "_fetch_google_trends_raw",
                return_value={
                    "weird history": ["the dancing plague", "unrelated sports trend"],
                    "strange facts": ["haunted lighthouse"],
                },
            ):
            result = trend_discovery.fetch_trending_topics("weird but true history")
        self.assertEqual(result, ["the dancing plague", "haunted lighthouse"])

    def test_empty_niche_returns_empty_without_calling_anything(self):
        with patch.object(trend_discovery, "generate_text") as mock_llm, patch.object(
            trend_discovery, "_fetch_google_trends_raw"
        ) as mock_fetch:
            result = trend_discovery.fetch_trending_topics("")
        self.assertEqual(result, [])
        mock_llm.assert_not_called()
        mock_fetch.assert_not_called()

    def test_no_seed_queries_returns_empty(self):
        with patch.object(trend_discovery, "generate_text", return_value=""), patch.object(
            trend_discovery, "_fetch_google_trends_raw"
        ) as mock_fetch:
            result = trend_discovery.fetch_trending_topics("some niche")
        self.assertEqual(result, [])
        mock_fetch.assert_not_called()

    def test_trend_fetch_failure_degrades_to_empty_list(self):
        with patch.object(trend_discovery, "generate_text", return_value="a seed query"), patch.object(
            trend_discovery, "_fetch_google_trends_raw", side_effect=RuntimeError("pytrends is unhappy")
        ):
            result = trend_discovery.fetch_trending_topics("some niche")
        self.assertEqual(result, [])

    def test_pytrends_missing_import_degrades_to_empty_list(self):
        with patch.object(trend_discovery, "generate_text", return_value="a seed query"), patch.object(
            trend_discovery, "_fetch_google_trends_raw", side_effect=ImportError("no pytrends")
        ):
            result = trend_discovery.fetch_trending_topics("some niche")
        self.assertEqual(result, [])

    def test_ranking_never_invents_topics_not_in_raw_candidates(self):
        with patch.object(
            trend_discovery, "generate_text", side_effect=["a seed", "a totally made up topic"]
        ), patch.object(
            trend_discovery, "_fetch_google_trends_raw", return_value={"a seed": ["a real trend"]}
        ):
            result = trend_discovery.fetch_trending_topics("some niche")
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
