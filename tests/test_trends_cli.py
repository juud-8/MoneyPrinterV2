import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import trends
from trend_store import TrendStore


NOW = "2026-07-13T12:00:00Z"


def manifest():
    return {
        "brand_id": "archive",
        "niche": "strange documented history",
        "publishing": {"review_before_upload": True},
        "production": {
            "trend_strategy": {
                "enabled": True,
                "mode": "suggest",
                "max_trend_assisted_share": 0.20,
                "providers": {
                    "gdelt": {"enabled": False},
                    "wikimedia": {"enabled": False},
                    "youtube": {"enabled": False},
                },
                "scoring": {
                    "minimum_cross_source_count": 1,
                    "minimum_opportunity_score": 50
                },
            }
        },
    }


class TrendsCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TrendStore(os.path.join(self.tmp.name, "trends.sqlite3"))
        self.manual = os.path.join(ROOT, "tests", "fixtures", "trends", "mvp_cases.json")
        self.bridges = os.path.join(ROOT, "tests", "fixtures", "trends", "bridge_candidates.json")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, argv):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("trends.load_brand", return_value=manifest()), redirect_stdout(stdout), redirect_stderr(stderr):
            code = trends.main(argv, store=self.store)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_offline_vertical_slice_stops_at_approved_seed(self):
        code, output, _ = self.run_cli(
            ["collect", "--brand", "archive", "--manual", self.manual, "--now", NOW]
        )
        self.assertEqual(code, 0, output)
        dance = next(item for item in self.store.list_clusters() if item.canonical_entity == "dance")
        code, output, error = self.run_cli(
            [
                "bridge",
                dance.cluster_id,
                "--brand",
                "archive",
                "--bridge-file",
                self.bridges,
                "--now",
                NOW,
            ]
        )
        self.assertEqual(code, 0, error)
        opportunity = next(
            item for item in self.store.list_opportunities("archive") if item.eligible
        )
        videos = [
            {
                "brand_id": "archive",
                "status": "uploaded",
                "date": "2026-07-13 11:00:00",
                "production": {},
            }
            for _ in range(10)
        ]
        with patch("analytics.dedupe_videos", return_value=videos):
            code, output, error = self.run_cli(
                [
                    "approve",
                    opportunity.opportunity_id,
                    "--brand",
                    "archive",
                    "--operator",
                    "reviewer",
                    "--reason",
                    "verified fixture",
                    "--now",
                    NOW,
                ]
            )
        self.assertEqual(code, 0, error)
        self.assertIn('"upload_triggered": false', output)
        self.assertIn("--trend-seed", output)

    def test_default_collect_does_not_call_live_providers(self):
        with patch("trend_providers.fetch_json_with_retries") as fetch:
            code, _, error = self.run_cli(
                ["collect", "--brand", "archive", "--manual", self.manual, "--now", NOW]
            )
        self.assertEqual(code, 0, error)
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
