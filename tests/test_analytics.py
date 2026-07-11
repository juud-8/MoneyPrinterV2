import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import analytics


class AnalyticsDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.analytics_path = os.path.join(self._tmp.name, "analytics.json")
        self.brands_dir = os.path.join(self._tmp.name, "brands")

        os.makedirs(os.path.join(self.brands_dir, "alpha"), exist_ok=True)
        with open(os.path.join(self.brands_dir, "alpha", "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "brand_id": "alpha",
                    "channel_name": "Alpha Channel",
                    "niche": "alpha niche",
                },
                f,
            )

        os.makedirs(os.path.join(self.brands_dir, "beta"), exist_ok=True)
        with open(os.path.join(self.brands_dir, "beta", "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "brand_id": "beta",
                    "channel_name": "Beta Channel",
                    "niche": "beta niche",
                },
                f,
            )

        self._patches = [
            patch.object(analytics, "_analytics_path", return_value=self.analytics_path),
            patch.object(analytics, "ROOT_DIR", self._tmp.name),
        ]
        import brand_switcher

        self._patches.append(patch.object(brand_switcher, "BRANDS_DIR", self.brands_dir))
        for patcher in self._patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self._patches):
            patcher.stop()
        self._tmp.cleanup()

    def _write_analytics(self, payload: dict) -> None:
        os.makedirs(os.path.dirname(self.analytics_path), exist_ok=True)
        with open(self.analytics_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

    def test_log_topic_rejection_appends_entry(self) -> None:
        analytics.log_topic_rejection(
            candidate="The Emu War, but reworded",
            matched="Australia's Bizarre Emu War",
            similarity=0.814,
            brand_id="alpha",
        )
        with open(self.analytics_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data["topic_rejections"]), 1)
        entry = data["topic_rejections"][0]
        self.assertEqual(entry["matched"], "Australia's Bizarre Emu War")
        self.assertEqual(entry["brand_id"], "alpha")
        self.assertAlmostEqual(entry["similarity"], 0.814)

    def test_dedupe_prefers_uploaded_row_with_url(self) -> None:
        self._write_analytics(
            {
                "videos": [
                    {
                        "date": "2026-06-29 10:00:00",
                        "title": "Episode 01: Hook | Alpha Channel",
                        "format": "short",
                        "niche": "alpha niche",
                        "status": "generated",
                    },
                    {
                        "date": "2026-06-29 10:05:00",
                        "title": "Episode 01: Hook | Alpha Channel",
                        "format": "short",
                        "niche": "alpha niche",
                        "url": "https://youtube.com/watch?v=abc",
                        "status": "uploaded",
                        "brand_id": "alpha",
                    },
                ],
                "weekly_notes": [],
                "asset_spend": [],
            }
        )

        merged = analytics.dedupe_videos()
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["status"], "uploaded")
        self.assertEqual(merged[0]["url"], "https://youtube.com/watch?v=abc")
        self.assertEqual(merged[0]["brand_id"], "alpha")
        self.assertEqual(merged[0]["event_count"], 2)

    def test_infer_brand_from_output_path(self) -> None:
        self._write_analytics(
            {
                "videos": [
                    {
                        "date": "2026-06-02 12:00:00",
                        "title": "Legacy Post",
                        "format": "short",
                        "niche": "",
                        "video_path": os.path.join(self._tmp.name, "output", "beta", "video.mp4"),
                    }
                ],
                "weekly_notes": [],
                "asset_spend": [],
            }
        )

        merged = analytics.dedupe_videos()
        self.assertEqual(merged[0]["brand_id"], "beta")

    def test_brand_summary_counts_and_spend(self) -> None:
        recent = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._write_analytics(
            {
                "videos": [
                    {
                        "date": recent,
                        "title": "Alpha One",
                        "format": "short",
                        "niche": "alpha niche",
                        "brand_id": "alpha",
                        "status": "uploaded",
                        "views": 120,
                    },
                    {
                        "date": recent,
                        "title": "Beta One",
                        "format": "short",
                        "niche": "beta niche",
                        "brand_id": "beta",
                        "status": "generated",
                    },
                ],
                "weekly_notes": [],
                "asset_spend": [
                    {
                        "date": recent,
                        "video_title": "Beta One",
                        "brand_id": "beta",
                        "role": "hook",
                        "tier": "premium_image",
                        "modality": "image",
                        "provider": "gemini:test",
                        "cost_usd": 1.25,
                    }
                ],
            }
        )

        summaries = analytics.get_brand_summary(days=7)
        by_id = {row["brand_id"]: row for row in summaries}
        self.assertEqual(by_id["alpha"]["post_count"], 1)
        self.assertEqual(by_id["alpha"]["uploaded_count"], 1)
        self.assertEqual(by_id["alpha"]["tracked_views"], 120)
        self.assertEqual(by_id["beta"]["post_count"], 1)
        self.assertEqual(by_id["beta"]["spend_7d_usd"], 1.25)

        dashboard = analytics.get_dashboard_data(days=7)
        self.assertEqual(dashboard["totals"]["videos"], 2)
        self.assertEqual(dashboard["totals"]["uploaded"], 1)
        self.assertEqual(dashboard["totals"]["spend_7d_usd"], 1.25)

    def test_log_video_records_experiment_research_and_production_metadata(self) -> None:
        analytics.log_video(
            title="Measured video",
            format_type="short",
            niche="history",
            experiment={"experiment_id": "visual-01", "variant": "archive"},
            research={"grounded": True, "source_count": 3},
            production={"tts_provider": "kittentts", "asset_count": 8},
        )
        entry = analytics._load()["videos"][0]
        self.assertEqual(entry["experiment"]["variant"], "archive")
        self.assertTrue(entry["research"]["grounded"])
        self.assertEqual(entry["production"]["asset_count"], 8)
        self.assertIn("engaged_views", entry)
        self.assertIn("subscribers_gained", entry)


if __name__ == "__main__":
    unittest.main()
