"""Tests for EL JEFE Mission Control Flask API (webui.py)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import webui  # noqa: E402


class WebuiApiTests(unittest.TestCase):
    def setUp(self):
        self.app = webui.app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_health_shape(self):
        with patch.object(webui, "_build_health", return_value={
            "checked_at": "2026-07-16 12:00:00",
            "keys": {"gemini": True, "youtube_data": False},
            "ollama": {"ok": True, "detail": "v0"},
            "imagemagick_ok": True,
            "brand_profiles": [],
            "latest_channel_snapshot": "",
            "disk_free_gb": 50.0,
            "config_present": True,
        }):
            res = self.client.get("/api/health?force=1")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("keys", data)
        self.assertIn("ollama", data)
        self.assertTrue(data["ollama"]["ok"])

    def test_ops_payload_shape(self):
        fake = {
            "generated_at": "2026-07-16 12:00:00",
            "window_days": 7,
            "totals": {"videos": 1, "uploaded": 0, "spend_window_usd": 0.0, "spend_all_time_usd": 0.0},
            "spend_alert": {"triggered": False, "threshold_usd": 25, "recent_spend_usd": 0},
            "rejection_summary": {"topic_rejections": 0, "duration_aborts": 0},
            "brands": [{"brand_id": "demo_brand", "channel_name": "Demo"}],
            "videos": [],
            "status_counts": {"uploaded": 0, "generated": 0, "other": 0},
        }
        with patch.object(webui, "get_dashboard_data", return_value=fake), patch.object(
            webui, "get_latest_channel_snapshots", return_value={}
        ), patch.object(webui, "list_brands", return_value=[]), patch.object(
            webui, "get_insights_summary", return_value={"active": False, "sample_size": 0, "min_sample": 5}
        ):
            res = self.client.get("/api/ops?days=7")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("totals", data)
        self.assertIn("brands_meta", data)
        self.assertIn("videos", data)
        self.assertEqual(data["window_days"], 7)

    def test_generate_passes_topic_and_image_provider_override(self):
        captured = {}

        def fake_run_python_script(kind, label, script_relpath, args, brand_id="", env_extra=None):
            captured["args"] = args
            captured["env_extra"] = env_extra
            return {"id": "job-1", "label": label}

        with patch.object(webui, "load_brand", return_value={"brand_id": "demo_brand"}), patch(
            "archived_brands.is_brand_archived", return_value=False
        ), patch.object(webui.webui_jobs, "run_python_script", side_effect=fake_run_python_script):
            res = self.client.post(
                "/api/generate",
                json={"brand_id": "demo_brand", "topic": "The Dancing Plague of 1518", "image_provider": "fal"},
            )
        self.assertEqual(res.status_code, 200)
        self.assertIn("--topic", captured["args"])
        self.assertIn("The Dancing Plague of 1518", captured["args"])
        self.assertEqual(captured["env_extra"].get("MPV2_IMAGE_PROVIDER_OVERRIDE"), "fal")

    def test_generate_ignores_invalid_image_provider(self):
        captured = {}

        def fake_run_python_script(kind, label, script_relpath, args, brand_id="", env_extra=None):
            captured["env_extra"] = env_extra
            return {"id": "job-1", "label": label}

        with patch.object(webui, "load_brand", return_value={"brand_id": "demo_brand"}), patch(
            "archived_brands.is_brand_archived", return_value=False
        ), patch.object(webui.webui_jobs, "run_python_script", side_effect=fake_run_python_script):
            res = self.client.post(
                "/api/generate",
                json={"brand_id": "demo_brand", "image_provider": "bogus"},
            )
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("MPV2_IMAGE_PROVIDER_OVERRIDE", captured["env_extra"])

    def test_trending_topics_returns_suggestions(self):
        with patch.object(webui, "load_brand", return_value={"brand_id": "demo_brand", "niche": "weird history"}), \
            patch.object(webui, "fetch_trending_topics", return_value=["topic a", "topic b"]):
            res = self.client.post("/api/brands/demo_brand/trending-topics")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["topics"], ["topic a", "topic b"])

    def test_trending_topics_unknown_brand_404s(self):
        with patch.object(webui, "load_brand", return_value=None):
            res = self.client.post("/api/brands/nope/trending-topics")
        self.assertEqual(res.status_code, 404)

    def test_overview_still_works(self):
        fake = {
            "generated_at": "2026-07-16 12:00:00",
            "window_days": 7,
            "brands": [{"brand_id": "demo_brand"}],
            "videos": [],
            "totals": {},
            "channel_growth": {},
            "video_metrics_table": [],
            "recent_spend": [],
            "spend_by_provider": {},
            "spend_by_tier": {},
            "rejection_summary": {},
            "spend_alert": {"triggered": False},
            "status_counts": {},
        }
        with patch.object(webui, "get_dashboard_data", return_value=fake), patch.object(
            webui, "get_latest_channel_snapshots", return_value={}
        ), patch.object(
            webui, "get_insights_summary", return_value={"active": False}
        ):
            res = self.client.get("/api/overview?days=7")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("insights", data)
        self.assertIn("channel_snapshots", data)

    def test_retention_validation(self):
        res = self.client.post(
            "/api/retention",
            json={"needle": "", "avg_view_pct": 50},
        )
        self.assertEqual(res.status_code, 400)

        res = self.client.post(
            "/api/retention",
            json={"needle": "abc", "avg_view_pct": "nope"},
        )
        self.assertEqual(res.status_code, 400)

        with patch.object(webui, "set_video_retention", return_value=2):
            res = self.client.post(
                "/api/retention",
                json={"needle": "some-video", "avg_view_pct": 72.5},
            )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["updated"], 2)

        with patch.object(webui, "set_video_retention", return_value=0):
            res = self.client.post(
                "/api/retention",
                json={"needle": "missing", "avg_view_pct": 10},
            )
        self.assertEqual(res.status_code, 404)

        with patch.object(webui, "set_video_retention", side_effect=ValueError("avg_view_pct must be 0-100")):
            res = self.client.post(
                "/api/retention",
                json={"needle": "x", "avg_view_pct": 200},
            )
        self.assertEqual(res.status_code, 400)

    def test_archive_songs_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "output")
            os.makedirs(out)
            with patch.object(webui, "ROOT_DIR", tmp):
                res = self.client.get("/api/archive-songs")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json(), [])

    def test_weekly_includes_text(self):
        fake = {
            "generated_at": "2026-07-16 12:00:00",
            "totals": {"uploaded": 2, "spend_window_usd": 1.0, "spend_all_time_usd": 2.0},
            "spend_alert": {"triggered": False},
            "rejection_summary": {},
            "videos": [{"title": "A", "date": "2026-07-15"}],
            "brands": [],
        }
        with patch.object(webui, "get_dashboard_data", return_value=fake), patch.object(
            webui, "get_weekly_summary", return_value="=== Weekly ===\n"
        ):
            res = self.client.get("/api/weekly")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("text", data)
        self.assertEqual(data["cost_per_uploaded_short_usd"], 0.5)

    def test_index_renders(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("EL JEFE", html)
        self.assertIn("Command Deck", html)
        self.assertIn("webui-core.js", html)


if __name__ == "__main__":
    unittest.main()
