import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import analytics
import youtube_metrics


class ExtractVideoIdTests(unittest.TestCase):
    def test_shorts_url(self):
        self.assertEqual(
            youtube_metrics.extract_video_id("https://www.youtube.com/shorts/abc123XYZ_-"),
            "abc123XYZ_-",
        )

    def test_watch_url(self):
        self.assertEqual(
            youtube_metrics.extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )

    def test_watch_url_with_extra_params(self):
        self.assertEqual(
            youtube_metrics.extract_video_id(
                "https://www.youtube.com/watch?feature=share&v=dQw4w9WgXcQ"
            ),
            "dQw4w9WgXcQ",
        )

    def test_youtu_be_url(self):
        self.assertEqual(
            youtube_metrics.extract_video_id("https://youtu.be/dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )

    def test_invalid_urls(self):
        self.assertEqual(youtube_metrics.extract_video_id(""), "")
        self.assertEqual(youtube_metrics.extract_video_id("https://example.com/foo"), "")
        self.assertEqual(youtube_metrics.extract_video_id(None), "")


class UpdateVideoMetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.analytics_path = os.path.join(self._tmp.name, "analytics.json")
        self._patch = patch.object(
            analytics, "_analytics_path", return_value=self.analytics_path
        )
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def _seed(self, videos: list[dict]) -> None:
        with open(self.analytics_path, "w", encoding="utf-8") as f:
            json.dump({"videos": videos, "weekly_notes": [], "asset_spend": []}, f)

    def test_updates_all_entries_for_same_video(self):
        self._seed(
            [
                {
                    "date": "2026-07-01 10:00:00",
                    "title": "A",
                    "url": "https://www.youtube.com/shorts/vid00000001",
                    "views": None,
                },
                {
                    "date": "2026-07-01 11:00:00",
                    "title": "A",
                    "url": "https://www.youtube.com/shorts/vid00000001",
                    "views": None,
                },
                {"date": "2026-07-01 12:00:00", "title": "No URL", "url": "", "views": None},
            ]
        )

        fake_stats = {"vid00000001": {"views": 1234, "likes": 56, "comments": 7}}
        with patch.object(youtube_metrics, "fetch_video_stats", return_value=fake_stats):
            result = youtube_metrics.update_video_metrics(api_key="test")

        self.assertEqual(result["updated"], 2)
        self.assertEqual(result["found"], 1)
        self.assertEqual(result["missing"], 0)

        saved = analytics._load()["videos"]
        self.assertEqual(saved[0]["views"], 1234)
        self.assertEqual(saved[1]["likes"], 56)
        self.assertIn("metrics_updated_at", saved[0])
        self.assertIsNone(saved[2]["views"])

    def test_missing_video_leaves_existing_values(self):
        self._seed(
            [
                {
                    "date": "2026-07-01 10:00:00",
                    "title": "Deleted",
                    "url": "https://www.youtube.com/shorts/gone00000001",
                    "views": 42,
                }
            ]
        )
        with patch.object(youtube_metrics, "fetch_video_stats", return_value={}):
            result = youtube_metrics.update_video_metrics(api_key="test")

        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["missing"], 1)
        self.assertEqual(analytics._load()["videos"][0]["views"], 42)

    def test_no_urls_short_circuits_without_api_call(self):
        self._seed([{"date": "2026-07-01 10:00:00", "title": "X", "url": "", "views": None}])
        with patch.object(youtube_metrics, "fetch_video_stats") as mock_fetch:
            result = youtube_metrics.update_video_metrics(api_key="test")
        mock_fetch.assert_not_called()
        self.assertEqual(result, {"updated": 0, "found": 0, "missing": 0})

    def test_repair_video_urls(self):
        self._seed(
            [
                {   # correct URL — untouched
                    "date": "2026-07-01 10:00:00",
                    "title": "Correct Video | Chan",
                    "status": "uploaded",
                    "url": "https://www.youtube.com/watch?v=correct0001",
                },
                {   # stale URL pointing at another real video — cleared
                    "date": "2026-07-02 10:00:00",
                    "title": "Newer Video | Chan",
                    "status": "uploaded",
                    "url": "https://www.youtube.com/watch?v=correct0001",
                },
                {   # uploaded without URL, title in feed — filled
                    "date": "2026-07-02 11:00:00",
                    "title": "Missing Url Video | Chan",
                    "status": "uploaded",
                    "url": "",
                },
                {   # wrong URL, title in feed under other id — reassigned
                    "date": "2026-07-02 12:00:00",
                    "title": "Swapped Video | Chan",
                    "status": "uploaded",
                    "url": "https://www.youtube.com/watch?v=correct0001",
                },
            ]
        )
        feed = [
            {"video_id": "correct0001", "title": "Correct Video"},
            {"video_id": "missing0001", "title": "Missing Url Video"},
            {"video_id": "swapped0001", "title": "Swapped Video"},
        ]

        import brand_switcher

        fake_brands = [{"brand_id": "alpha", "channel_id": "UCfake"}]
        with patch.object(brand_switcher, "list_brands", return_value=fake_brands), patch.object(
            youtube_metrics, "fetch_channel_uploads_rss", return_value=feed
        ):
            result = youtube_metrics.repair_video_urls()

        self.assertEqual(result, {"reassigned": 1, "cleared": 1, "filled": 1})
        saved = analytics._load()["videos"]
        self.assertIn("correct0001", saved[0]["url"])
        self.assertEqual(saved[1]["url"], "")  # stale capture cleared
        self.assertIn("missing0001", saved[2]["url"])
        self.assertIn("swapped0001", saved[3]["url"])

    def test_latest_channel_snapshots(self):
        with open(self.analytics_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "videos": [],
                    "weekly_notes": [],
                    "asset_spend": [],
                    "channel_snapshots": [
                        {"date": "2026-07-01 10:00:00", "brand_id": "alpha", "subscribers": 10},
                        {"date": "2026-07-02 10:00:00", "brand_id": "alpha", "subscribers": 25},
                        {"date": "2026-07-01 10:00:00", "brand_id": "beta", "subscribers": 3},
                    ],
                },
                f,
            )
        latest = youtube_metrics.get_latest_channel_snapshots()
        self.assertEqual(latest["alpha"]["subscribers"], 25)
        self.assertEqual(latest["beta"]["subscribers"], 3)


if __name__ == "__main__":
    unittest.main()
