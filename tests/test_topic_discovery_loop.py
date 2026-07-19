"""Tests for opt-in trending topic discovery loop."""

import os
import sys
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from topic_discovery_loop import (
    build_trend_seed_block,
    fetch_trend_seeds_for_niche,
    select_topic_from_pools,
    trending_topics_enabled,
)
from topic_scoring import score_title


class TopicDiscoveryLoopTests(unittest.TestCase):
    def test_enabled_via_brand_or_env(self):
        self.assertFalse(trending_topics_enabled({}, env={}))
        self.assertTrue(
            trending_topics_enabled({"use_trending_topics": True}, env={})
        )
        self.assertTrue(
            trending_topics_enabled({}, env={"MPV2_USE_TRENDING_TOPICS": "1"})
        )

    def test_seed_block_empty_when_no_topics(self):
        self.assertEqual(build_trend_seed_block([]), "")
        block = build_trend_seed_block(["emu war", "dancing plague"])
        self.assertIn("emu war", block)
        self.assertIn("dancing plague", block)

    def test_select_prefers_strong_llm_over_generic_trend(self):
        llm = ["In 1932 Australia Declared War on Emus"]
        trends = ["funny animals"]
        chosen = select_topic_from_pools(llm, trends)
        self.assertEqual(chosen, llm[0])
        self.assertGreater(score_title(llm[0]), score_title(trends[0]))

    def test_fetch_degrades_on_fetcher_error(self):
        def boom(_niche: str):
            raise RuntimeError("pytrends down")

        self.assertEqual(fetch_trend_seeds_for_niche("niche", fetcher=boom), [])

    def test_fetch_uses_fetcher(self):
        self.assertEqual(
            fetch_trend_seeds_for_niche("niche", fetcher=lambda n: ["a", "b"]),
            ["a", "b"],
        )


if __name__ == "__main__":
    unittest.main()
