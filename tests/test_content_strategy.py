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
    build_topic_avoid_block,
    build_topic_strategy_block,
    recent_topic_labels,
    script_engagement_instruction,
)


class TopicAvoidBlockTests(unittest.TestCase):
    def test_empty_inputs_produce_empty_block(self):
        self.assertEqual(build_topic_avoid_block([], []), "")
        self.assertEqual(build_topic_avoid_block([], None), "")

    def test_lists_published_titles(self):
        block = build_topic_avoid_block(["The Emu War", "The Pastry War"])
        self.assertIn("ALREADY PUBLISHED", block)
        self.assertIn("- The Emu War", block)
        self.assertIn("- The Pastry War", block)
        self.assertNotIn("REJECTED", block)

    def test_lists_within_call_rejections(self):
        block = build_topic_avoid_block(
            ["The Emu War"], ["How 1 soup kettle defeated a flagship in 1784"]
        )
        self.assertIn("REJECTED as near-duplicates", block)
        self.assertIn("- How 1 soup kettle defeated a flagship in 1784", block)

    def test_caps_published_and_rejected_counts(self):
        published = [f"published {i}" for i in range(30)]
        rejected = [f"rejected {i}" for i in range(12)]
        block = build_topic_avoid_block(published, rejected)
        self.assertIn("published 19", block)
        self.assertNotIn("published 20", block)
        # Rejected list keeps the most recent entries.
        self.assertIn("rejected 11", block)
        self.assertNotIn("rejected 3\n", block)

    def test_skips_blank_entries(self):
        block = build_topic_avoid_block(["", "Real Title"], ["", None])
        self.assertIn("- Real Title", block)
        self.assertNotIn("REJECTED", block)


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

    def test_recent_topic_labels_warns_when_dedupe_cap_is_reached(self):
        manifest = {
            "brand_id": "alpha",
            "production": {
                "content_strategy": {
                    "recent_topic_lookback": 400,
                    "recent_topic_days": 0,
                }
            },
        }
        videos = [
            self._uploaded(1, f"event {index}", f"title {index}")
            for index in range(300)
        ]
        with patch.object(analytics, "dedupe_videos", return_value=videos), patch(
            "content_strategy.logger.warning"
        ) as warning_mock:
            labels = recent_topic_labels(manifest)

        self.assertEqual(len(labels), 600)
        warning_mock.assert_called_once_with(
            "Dedupe corpus at cap (%d) — older episodes are no longer "
            "protected from republication.",
            600,
        )


if __name__ == "__main__":
    unittest.main()
