import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trend_models import ProviderResult, TrendRequest
from trend_providers import (
    CollectionCoordinator,
    GdeltProvider,
    GoogleTrendsProviderStub,
    ManualProvider,
    ProviderSettings,
    YouTubeTrendProvider,
    WikimediaProvider,
    XProviderStub,
)
from trend_store import TrendStore


NOW = "2026-07-13T12:00:00Z"


def request(**overrides):
    payload = {
        "brand_id": "archive",
        "terms": ["dance"],
        "geographies": ["US"],
        "languages": ["en"],
        "window_hours": 24,
        "max_results": 5,
        "dry_run": False,
        "requested_at": NOW,
    }
    payload.update(overrides)
    return TrendRequest.from_dict(payload)


class ProviderTests(unittest.TestCase):
    def test_manual_fixture_provider(self):
        path = os.path.join(ROOT, "tests", "fixtures", "trends", "mvp_cases.json")
        result = ManualProvider(path).collect(request(max_results=10))
        self.assertFalse(result.errors)
        self.assertEqual(len(result.signals), 4)

    def test_gdelt_outage_is_partial_error(self):
        def fail(*args):
            raise ValueError("offline")

        provider = GdeltProvider(ProviderSettings(enabled=True), fetch_json=fail)
        result = provider.collect(request())
        self.assertEqual(result.signals, [])
        self.assertEqual(result.errors[0].code, "provider_request_failed")

    def test_wikimedia_pageviews_are_absolute_but_not_search_volume(self):
        def fake(*args):
            return {"items": [{"views": 100}] * 12 + [{"views": 300}, {"views": 400}]}

        provider = WikimediaProvider(ProviderSettings(enabled=True), fetch_json=fake)
        result = provider.collect(request())
        self.assertTrue(result.signals[0].volume_is_absolute)
        self.assertEqual(result.signals[0].metric_type, "wikimedia_pageviews")

    def test_youtube_requires_dedicated_credentials(self):
        provider = YouTubeTrendProvider(ProviderSettings(enabled=True, api_key=""))
        result = provider.collect(request())
        self.assertEqual(result.errors[0].code, "missing_credentials")

    def test_x_and_google_are_stubs(self):
        self.assertEqual(XProviderStub().collect(request()).errors[0].code, "mvp_stub")
        self.assertEqual(GoogleTrendsProviderStub().collect(request()).errors[0].code, "mvp_stub")

    def test_coordinator_uses_cache(self):
        calls = {"count": 0}

        def fake(*args):
            calls["count"] += 1
            return {"articles": [{"url": "https://news.test/a", "domain": "news.test"}]}

        with tempfile.TemporaryDirectory() as tmp:
            store = TrendStore(os.path.join(tmp, "trends.sqlite3"))
            settings = ProviderSettings(enabled=True, cache_ttl_minutes=60)
            provider = GdeltProvider(settings, fetch_json=fake)
            coordinator = CollectionCoordinator(store)
            first = coordinator.collect(provider, request(), settings)
            second = coordinator.collect(provider, request(), settings)
        self.assertFalse(first.cache_hit)
        self.assertTrue(second.cache_hit)
        self.assertEqual(calls["count"], 1)

    def test_cost_ceiling_blocks_before_provider_call(self):
        class PaidFixtureProvider:
            name = "paid"
            enabled = True
            cache_ttl_minutes = 0
            estimated_max_cost_usd = 3.0

            def collect(self, req):
                raise AssertionError("must not be called")

        with tempfile.TemporaryDirectory() as tmp:
            settings = ProviderSettings(enabled=True, daily_cost_limit_usd=2.0)
            result = CollectionCoordinator(TrendStore(os.path.join(tmp, "db.sqlite3"))).collect(
                PaidFixtureProvider(), request(), settings
            )
        self.assertEqual(result.errors[0].code, "daily_budget_exceeded")

    def test_youtube_quota_ceiling_blocks_before_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = ProviderSettings(enabled=True, api_key="dedicated", daily_request_limit=1)
            provider = YouTubeTrendProvider(settings, fetch_json=lambda *args: {})
            result = CollectionCoordinator(TrendStore(os.path.join(tmp, "db.sqlite3"))).collect(
                provider, request(), settings
            )
        self.assertEqual(result.errors[0].code, "daily_quota_exceeded")


if __name__ == "__main__":
    unittest.main()
