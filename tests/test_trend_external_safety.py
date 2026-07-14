import argparse
import importlib.util
import io
import json
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
from tests.test_trend_pipeline import NOW, evergreen_videos, manifest, opportunity
from trend_pipeline import approve_opportunity, validate_topic_seed_for_brand
from trend_providers import ProviderSettings, YouTubeTrendProvider
from trend_models import TrendRequest, ValidationError
from trend_store import TrendStore


class ExternalSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TrendStore(os.path.join(self.tmp.name, "trends.sqlite3"))

    def tearDown(self):
        self.tmp.cleanup()

    def _seed(self):
        item = opportunity()
        self.store.save_opportunity(item)
        return approve_opportunity(
            self.store,
            item.opportunity_id,
            manifest(),
            operator="reviewer",
            reason="verified",
            now=NOW,
            videos=evergreen_videos(10),
        )[1]

    def test_trend_seed_requires_both_review_settings(self):
        seed = self._seed()
        for global_review, brand_review, allowed in (
            (True, True, True),
            (True, False, False),
            (False, True, False),
            (False, False, False),
        ):
            value = manifest()
            value["publishing"]["review_before_upload"] = brand_review
            with self.subTest(global_review=global_review, brand_review=brand_review), patch(
                "config.get_review_before_upload", return_value=global_review
            ):
                if allowed:
                    validate_topic_seed_for_brand(seed, value, now=NOW)
                else:
                    with self.assertRaisesRegex(ValidationError, "review_before_upload"):
                        validate_topic_seed_for_brand(seed, value, now=NOW)

    def test_top_level_disabled_prevents_provider_construction_even_with_live(self):
        args = argparse.Namespace(
            brand="archive", manual="", term=["dance"], provider=["gdelt"],
            geography=["US"], language=["en"], window_hours=24,
            max_results=5, live=True, now="",
        )
        for enabled, mode in ((False, "suggest"), (True, "off")):
            value = manifest()
            value["production"]["trend_strategy"].update(
                {"enabled": enabled, "mode": mode, "providers": {"gdelt": {"enabled": True}}}
            )
            with self.subTest(enabled=enabled, mode=mode), patch(
                "trends._manifest", return_value=value
            ), patch("trends.provider_from_name") as factory, redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValidationError, "disabled"):
                    trends._collect(args, self.store)
                factory.assert_not_called()

    def test_offline_bridge_with_missing_sources_never_collects_sources(self):
        value = manifest()
        cluster = opportunity().trend
        self.store.save_cluster(cluster)
        bridge_path = os.path.join(self.tmp.name, "bridge.json")
        with open(
            os.path.join(ROOT, "tests", "fixtures", "trends", "bridge_candidates.json"),
            encoding="utf-8",
        ) as file:
            payload = json.load(file)
        payload["bridges"][0]["historical_sources"] = []
        with open(bridge_path, "w", encoding="utf-8") as file:
            json.dump(payload, file)
        args = argparse.Namespace(
            brand="archive", cluster_id=cluster.cluster_id, bridge_file=bridge_path,
            live_research=False, now=NOW,
        )
        with patch("trends._manifest", return_value=value), patch("trends.collect_sources") as collect:
            with self.assertRaisesRegex(ValidationError, "offline"):
                trends._bridge(args, self.store)
            collect.assert_not_called()

    def test_credential_bearing_provider_error_is_redacted(self):
        secret = "TOP_SECRET_KEY"

        def fail(*_):
            raise ValueError(f"401 https://example.test?q=x&key={secret}")

        provider = YouTubeTrendProvider(
            ProviderSettings(enabled=True, api_key=secret), fetch_json=fail
        )
        request = TrendRequest.from_dict(
            {
                "brand_id": "archive", "terms": ["dance"], "geographies": ["US"],
                "languages": ["en"], "window_hours": 24, "max_results": 5,
                "dry_run": False, "requested_at": NOW,
            }
        )
        result = provider.collect(request)
        serialized = json.dumps(result.to_dict())
        self.assertNotIn(secret, serialized)
        self.assertIn("[REDACTED]", serialized)

    def test_preflight_offline_makes_no_network_calls(self):
        path = os.path.join(ROOT, "scripts", "preflight_local.py")
        spec = importlib.util.spec_from_file_location("preflight_offline_test", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(module)
        with patch.object(module.requests, "get", side_effect=AssertionError("network call")) as get:
            with redirect_stdout(io.StringIO()):
                module.main(["--offline"])
            get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
