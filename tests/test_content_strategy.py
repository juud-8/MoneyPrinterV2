import os
import random
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import analytics
from content_strategy import (
    build_topic_strategy_block,
    recent_topic_labels,
    script_engagement_instruction,
)


class ContentStrategyTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {
            "brand_id": "alpha",
            "production": {
                "content_strategy": {
                    "recent_topic_lookback": 2,
                    "topic_mix": [
                        {"name": "Absurd conflicts", "weight": 1, "guidance": "Use concrete stakes."}
                    ],
                    "interaction_intent": "Choose a premise that supports a specific question.",
                    "script_engagement_instruction": "Ask one concise question before the sign-off.",
                }
            },
        }

    def test_builds_lane_novelty_and_interaction_guidance(self):
        recent = [
            {"subject": "A pig trial"},
            {"title": "The Emu War"},
            {"title": "Ignored outside lookback"},
        ]
        block = build_topic_strategy_block(self.manifest, recent, rng=random.Random(1))
        self.assertIn("Selected lane: Absurd conflicts", block)
        self.assertIn("A pig trial", block)
        self.assertIn("The Emu War", block)
        self.assertNotIn("Ignored outside lookback", block)
        self.assertIn("Interaction intent", block)

    def test_missing_strategy_is_noop(self):
        self.assertEqual(build_topic_strategy_block({}), "")
        self.assertEqual(script_engagement_instruction({}), "")

    def test_script_instruction_is_manifest_driven(self):
        self.assertEqual(
            script_engagement_instruction(self.manifest),
            "Ask one concise question before the sign-off.",
        )

    @staticmethod
    def _uploaded(days_ago: int, subject: str, title: str) -> dict:
        return {
            "brand_id": "alpha",
            "status": "uploaded",
            "date": (datetime.now() - timedelta(days=days_ago)).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "subject": subject,
            "title": title,
        }

    def test_recent_topic_labels_cover_30_days_beyond_entry_lookback(self):
        videos = [
            self._uploaded(1, "event one", "Title One"),
            self._uploaded(10, "event ten", "Title Ten"),
            self._uploaded(29, "event twentynine", "Title TwentyNine"),
            self._uploaded(45, "event fortyfive", "Title FortyFive"),
        ]
        with patch.object(analytics, "dedupe_videos", lambda: videos):
            labels = recent_topic_labels(self.manifest)  # lookback = 2

        # Entry lookback alone would stop at "event ten"; the 30-day window
        # keeps day-29 in scope. Day-45 is outside both windows.
        self.assertIn("event twentynine", labels)
        self.assertNotIn("event fortyfive", labels)
        # Titles are checked too, not just subjects.
        self.assertIn("Title Ten", labels)

    def test_recent_topic_labels_default_to_30_day_window_without_strategy(self):
        videos = [self._uploaded(5, "recent event", "Recent Title")]
        with patch.object(analytics, "dedupe_videos", lambda: videos):
            labels = recent_topic_labels({"brand_id": "alpha"})
        self.assertIn("recent event", labels)

    def test_recent_topic_labels_can_be_fully_disabled(self):
        manifest = {
            "brand_id": "alpha",
            "production": {
                "content_strategy": {
                    "recent_topic_lookback": 0,
                    "recent_topic_days": 0,
                }
            },
        }
        videos = [self._uploaded(1, "event", "Title")]
        with patch.object(analytics, "dedupe_videos", lambda: videos):
            self.assertEqual(recent_topic_labels(manifest), [])


if __name__ == "__main__":
    unittest.main()
