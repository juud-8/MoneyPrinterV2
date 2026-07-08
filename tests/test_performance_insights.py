import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import analytics
import performance_insights


NOW = datetime(2026, 7, 10, 12, 0, 0)


def _video(title: str, views: int | None, days_old: int = 7, brand_id: str = "alpha") -> dict:
    date = (NOW - timedelta(days=days_old)).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "date": date,
        "title": title,
        "format": "short",
        "niche": "test niche",
        "subject": title,
        "video_path": "",
        "url": f"https://www.youtube.com/shorts/{abs(hash(title)) % 10**11:011d}",
        "brand_id": brand_id,
        "status": "uploaded",
        "views": views,
    }


class PerformanceInsightsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.analytics_path = os.path.join(self._tmp.name, "analytics.json")
        brands_dir = os.path.join(self._tmp.name, "brands")
        os.makedirs(brands_dir, exist_ok=True)

        import brand_switcher

        self._patches = [
            patch.object(analytics, "_analytics_path", return_value=self.analytics_path),
            patch.object(brand_switcher, "BRANDS_DIR", brands_dir),
        ]
        for patcher in self._patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self._patches):
            patcher.stop()
        self._tmp.cleanup()

    def _seed(self, videos: list[dict]) -> None:
        with open(self.analytics_path, "w", encoding="utf-8") as f:
            json.dump({"videos": videos, "weekly_notes": [], "asset_spend": []}, f)

    def test_empty_below_min_sample(self):
        self._seed([_video(f"Video {i}", views=100 * i) for i in range(3)])
        self.assertEqual(
            performance_insights.build_topic_insights_block("alpha", now=NOW), ""
        )

    def test_block_contains_top_and_bottom_titles(self):
        videos = [
            _video("Mega Hit Story", views=9000),
            _video("Second Best Tale", views=5000),
            _video("Solid Middle One", views=1000),
            _video("Weak Performer A", views=40),
            _video("Total Flop Story", views=5),
            _video("Another Mid Entry", views=800),
        ]
        self._seed(videos)

        block = performance_insights.build_topic_insights_block("alpha", now=NOW)
        self.assertIn("Mega Hit Story", block)
        self.assertIn("PERFORMANCE DATA", block)
        self.assertIn("Total Flop Story", block)
        self.assertIn("Do NOT reuse", block)

    def test_young_videos_excluded(self):
        videos = [_video(f"Old Video {i}", views=100, days_old=7) for i in range(4)]
        videos.append(_video("Fresh Video", views=99999, days_old=0))
        self._seed(videos)

        # Only 4 mature videos — below MIN_SAMPLE of 5, so no block.
        self.assertEqual(
            performance_insights.build_topic_insights_block("alpha", now=NOW), ""
        )
        scored = performance_insights.get_brand_performance("alpha", now=NOW)
        self.assertNotIn("Fresh Video", [v["title"] for v in scored])

    def test_other_brand_and_unmetered_videos_excluded(self):
        videos = [_video(f"Alpha Video {i}", views=100 + i) for i in range(5)]
        videos.append(_video("Beta Video", views=50000, brand_id="beta"))
        videos.append(_video("No Metrics Yet", views=None))
        self._seed(videos)

        scored = performance_insights.get_brand_performance("alpha", now=NOW)
        titles = [v["title"] for v in scored]
        self.assertEqual(len(scored), 5)
        self.assertNotIn("Beta Video", titles)
        self.assertNotIn("No Metrics Yet", titles)

    def test_longform_videos_excluded(self):
        videos = [_video(f"Alpha Short {i}", views=100 + i) for i in range(5)]
        flop = _video("Great Topic Wrong Format", views=1)
        flop["format"] = "longform"
        videos.append(flop)
        self._seed(videos)

        scored = performance_insights.get_brand_performance("alpha", now=NOW)
        titles = [v["title"] for v in scored]
        self.assertEqual(len(scored), 5)
        self.assertNotIn("Great Topic Wrong Format", titles)
        block = performance_insights.build_topic_insights_block("alpha", now=NOW)
        self.assertNotIn("Great Topic Wrong Format", block)

    def test_retention_blends_into_ranking(self):
        # Fewer views but excellent retention should outrank more views with
        # poor retention: 500 * 0.90 = 450 > 600 * 0.40 = 240.
        strong = _video("High Retention Sleeper", views=500)
        strong["avg_view_pct"] = 90.0
        weak = _video("Low Retention Spike", views=600)
        weak["avg_view_pct"] = 40.0
        videos = [strong, weak] + [
            _video(f"Filler Video {i}", views=50 + i) for i in range(4)
        ]
        self._seed(videos)

        scored = performance_insights.get_brand_performance("alpha", now=NOW)
        self.assertEqual(scored[0]["title"], "High Retention Sleeper")
        self.assertEqual(scored[1]["title"], "Low Retention Spike")

        block = performance_insights.build_topic_insights_block("alpha", now=NOW)
        self.assertIn("90% avg viewed", block)

    def test_insights_summary_shape(self):
        self._seed([_video(f"Video Number {i}", views=100 * (i + 1)) for i in range(6)])
        with patch.object(performance_insights, "datetime") as mock_dt:
            mock_dt.now.return_value = NOW
            summary = performance_insights.get_insights_summary("alpha")
        self.assertTrue(summary["active"])
        self.assertEqual(summary["sample_size"], 6)
        self.assertEqual(len(summary["top"]), 3)
        self.assertLessEqual(len(summary["bottom"]), 2)


if __name__ == "__main__":
    unittest.main()
