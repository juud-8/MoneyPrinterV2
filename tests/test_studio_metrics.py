"""Tests for honest Studio metric ingestion helpers."""

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
from studio_metrics import (
    MetricSource,
    StudioMetricValue,
    ingestion_plan,
    metric_is_usable_for_strategy,
    missing_studio_fields,
)


class StudioMetricsTests(unittest.TestCase):
    def test_ctr_bounds_and_strategy_gate(self):
        good = StudioMetricValue("ctr", 4.5, MetricSource.MANUAL_STUDIO)
        self.assertTrue(metric_is_usable_for_strategy(good))
        proxy = StudioMetricValue("ctr", 4.5, MetricSource.PROXY_ESTIMATE)
        self.assertFalse(metric_is_usable_for_strategy(proxy))
        with self.assertRaises(ValueError):
            StudioMetricValue("ctr", 140, MetricSource.MANUAL_STUDIO)

    def test_missing_fields(self):
        missing = missing_studio_fields({"views": 10, "ctr": None})
        self.assertIn("ctr", missing)
        self.assertIn("avg_view_pct", missing)

    def test_ingestion_plan_shape(self):
        plan = ingestion_plan()
        self.assertEqual(plan["schema_version"], 1)
        self.assertIn("ctr", plan["studio_private_fields"])
        self.assertIn("proxy_estimate", plan["forbidden_for_strategy"])


class AnalyticsCtrTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "analytics.json")
        self._patch = patch.object(analytics, "_analytics_path", return_value=self.path)
        self._patch.start()
        analytics.log_video(
            title="Emu War Short",
            format_type="short",
            niche="history",
            subject="emus",
            video_path="x.mp4",
            url="https://youtube.com/shorts/abc123XYZ",
            brand_id="alpha",
            status="uploaded",
        )

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def test_set_ctr_and_retention_label_sources(self):
        self.assertEqual(analytics.set_video_ctr("abc123XYZ", 3.2), 1)
        self.assertEqual(analytics.set_video_retention("abc123XYZ", 55.0), 1)
        data = analytics._load()
        entry = data["videos"][0]
        self.assertEqual(entry["ctr"], 3.2)
        self.assertEqual(entry["avg_view_pct"], 55.0)
        self.assertEqual(entry["metric_sources"]["ctr"], "manual_studio")
        self.assertEqual(entry["metric_sources"]["avg_view_pct"], "manual_studio")

    def test_refuse_proxy_by_default(self):
        with self.assertRaises(ValueError):
            analytics.set_studio_metrics(
                "abc123XYZ",
                [
                    {
                        "field": "ctr",
                        "value": 1.0,
                        "source": "proxy_estimate",
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
