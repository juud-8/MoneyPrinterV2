import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import closing

ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from tests.test_trend_pipeline import NOW, evergreen_videos, manifest, opportunity
from trend_models import ProviderError, ProviderResult, TrendRequest, ValidationError
from trend_pipeline import approve_opportunity
from trend_providers import CollectionCoordinator, ProviderNotDispatchedError, ProviderSettings
from trend_store import TrendStore


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "trends.sqlite3")
        self.store = TrendStore(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def _provider_request(self):
        return TrendRequest.from_dict(
            {"brand_id": "archive", "terms": ["x"], "geographies": ["US"],
             "languages": ["en"], "window_hours": 24, "max_results": 5,
             "dry_run": False, "requested_at": NOW}
        )

    def _approved_seed(self):
        item = opportunity()
        self.store.save_opportunity(item)
        return approve_opportunity(
            self.store, item.opportunity_id, manifest(), operator="reviewer",
            reason="verified", now=NOW, videos=evergreen_videos(10)
        )[1]

    def test_interrupted_v2_migration_recovers(self):
        self.store.migrate()
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("DELETE FROM schema_migrations WHERE version = 2")
            connection.commit()
        self.store.migrate()
        self.assertIn(2, self.store.schema_versions())

    def test_partially_existing_v2_schema_recovers(self):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.executescript(
                """
                CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT);
                INSERT INTO schema_migrations VALUES (1, CURRENT_TIMESTAMP);
                CREATE TABLE trend_attribution (attribution_id INTEGER PRIMARY KEY);
                """
            )
        with self.assertRaisesRegex(RuntimeError, "foreign key"):
            self.store.migrate()

    def test_recorded_v1_with_incomplete_topic_seed_table_fails_without_advancing(self):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.executescript(
                """
                CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT);
                INSERT INTO schema_migrations VALUES (1, CURRENT_TIMESTAMP);
                CREATE TABLE topic_seeds (seed_id TEXT PRIMARY KEY);
                """
            )
        with self.assertRaisesRegex(RuntimeError, "topic_seeds.*missing column opportunity_id"):
            self.store.migrate()
        with closing(sqlite3.connect(self.path)) as connection:
            versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
        self.assertEqual(versions, [1])

    def test_concurrent_migrations_are_serialized(self):
        errors = []
        barrier = threading.Barrier(4)

        def run():
            try:
                barrier.wait()
                TrendStore(self.path).migrate()
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=run) for _ in range(4)]
        [thread.start() for thread in threads]
        [thread.join() for thread in threads]
        self.assertEqual(errors, [])
        self.assertEqual(self.store.schema_versions(), [1, 2, 3])

    def test_failed_migration_statement_rolls_back(self):
        with self.assertRaises(RuntimeError):
            self.store.migrate(fail_after_version=1)
        with closing(sqlite3.connect(self.path)) as connection:
            table_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            ).fetchone()
            versions = ([row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
                        if table_exists else [])
        self.assertNotIn(1, versions)

    def test_seed_claim_release_complete_lifecycle(self):
        seed = self._approved_seed()
        self.assertTrue(self.store.claim_topic_seed(seed.seed_id, "run-1", NOW))
        self.assertFalse(self.store.claim_topic_seed(seed.seed_id, "run-2", NOW))
        self.assertTrue(self.store.release_topic_seed(seed.seed_id, "run-1", NOW, "safe pre-production failure"))
        self.assertTrue(self.store.claim_topic_seed(seed.seed_id, "run-2", NOW))
        self.assertTrue(self.store.complete_topic_seed(seed.seed_id, "run-2", NOW))
        self.assertFalse(self.store.claim_topic_seed(seed.seed_id, "run-3", NOW))

    def test_concurrent_seed_claim_has_one_winner(self):
        seed = self._approved_seed()
        barrier = threading.Barrier(2)
        outcomes = []

        def claim(name):
            barrier.wait()
            outcomes.append(self.store.claim_topic_seed(seed.seed_id, name, NOW))

        threads = [threading.Thread(target=claim, args=(f"run-{i}",)) for i in range(2)]
        [thread.start() for thread in threads]
        [thread.join() for thread in threads]
        self.assertEqual(sorted(outcomes), [False, True])

    def test_concurrent_content_mix_approval_has_one_winner(self):
        videos = evergreen_videos(9)
        first = opportunity()
        self.store.save_opportunity(first)
        approve_opportunity(
            self.store, first.opportunity_id, manifest(), operator="a",
            reason="a", now=NOW, videos=videos
        )
        items = [opportunity(), opportunity()]
        for item in items:
            self.store.save_opportunity(item)
        barrier = threading.Barrier(2)
        outcomes = []

        def approve(item):
            barrier.wait()
            try:
                approve_opportunity(
                    self.store, item.opportunity_id, manifest(), operator="a",
                    reason="a", now=NOW, videos=videos
                )
                outcomes.append("approved")
            except ValidationError:
                outcomes.append("blocked")

        threads = [threading.Thread(target=approve, args=(item,)) for item in items]
        [thread.start() for thread in threads]
        [thread.join() for thread in threads]
        self.assertEqual(sorted(outcomes), ["approved", "blocked"])

    def test_content_mix_override_records_operator_reason_time_and_shares(self):
        item = opportunity()
        self.store.save_opportunity(item)
        approval, seed, _ = approve_opportunity(
            self.store, item.opportunity_id, manifest(), operator="reviewer",
            reason="editorial exception", override_reason="documented launch exception",
            now=NOW, videos=[],
        )
        self.assertEqual(approval.operator, "reviewer")
        self.assertEqual(approval.decided_at, NOW)
        self.assertEqual(approval.override_reason, "documented launch exception")
        self.assertEqual(approval.previous_calculated_share, 0)
        self.assertEqual(approval.resulting_calculated_share, 1)
        self.assertEqual(seed.approval_record, approval)

    def test_concurrent_quota_reservation_has_one_winner(self):
        calls = []
        barrier = threading.Barrier(2)

        class Provider:
            name = "quota"
            enabled = True
            cache_ttl_minutes = 0
            estimated_max_cost_usd = 0

            def estimated_max_requests(self, request):
                return 1

            def collect(self, request):
                calls.append(1)
                return ProviderResult(self.name, [], [], False, 1, 0, 0, 0, request.requested_at)

        request = TrendRequest.from_dict(
            {"brand_id": "archive", "terms": ["x"], "geographies": ["US"],
             "languages": ["en"], "window_hours": 24, "max_results": 5,
             "dry_run": False, "requested_at": NOW}
        )
        settings = ProviderSettings(enabled=True, daily_request_limit=1)
        results = []

        def collect():
            barrier.wait()
            results.append(
                CollectionCoordinator(self.store, clock=lambda: NOW).collect(
                    Provider(), request, settings
                )
            )

        threads = [threading.Thread(target=collect) for _ in range(2)]
        [thread.start() for thread in threads]
        [thread.join() for thread in threads]
        codes = [error.code for result in results for error in result.errors]
        self.assertEqual(len(calls), 1)
        self.assertIn("daily_quota_exceeded", codes)

    def test_failure_before_dispatch_releases_reservation(self):
        class Provider:
            name = "before"
            enabled = True
            cache_ttl_minutes = 0
            estimated_max_cost_usd = 2

            def estimated_max_requests(self, request):
                return 1

            def collect(self, request):
                raise ProviderNotDispatchedError("local validation")

        settings = ProviderSettings(enabled=True, daily_request_limit=1, daily_cost_limit_usd=2)
        coordinator = CollectionCoordinator(self.store, clock=lambda: NOW)
        with self.assertRaises(ProviderNotDispatchedError):
            coordinator.collect(Provider(), self._provider_request(), settings)
        with self.store.connect() as connection:
            status = connection.execute("SELECT status FROM provider_budget_reservations").fetchone()[0]
        self.assertEqual(status, "released_not_dispatched")
        with self.assertRaises(ProviderNotDispatchedError):
            coordinator.collect(Provider(), self._provider_request(), settings)

    def test_post_dispatch_exception_is_charged_at_reserved_maximum(self):
        calls = []

        class Provider:
            name = "uncertain"
            enabled = True
            cache_ttl_minutes = 0
            estimated_max_cost_usd = 3

            def estimated_max_requests(self, request):
                return 1

            def collect(self, request):
                calls.append(1)
                raise TimeoutError("after dispatch")

        settings = ProviderSettings(enabled=True, daily_request_limit=1, daily_cost_limit_usd=3)
        coordinator = CollectionCoordinator(self.store, clock=lambda: NOW)
        with self.assertRaises(TimeoutError):
            coordinator.collect(Provider(), self._provider_request(), settings)
        blocked = coordinator.collect(Provider(), self._provider_request(), settings)
        self.assertEqual(len(calls), 1)
        self.assertEqual(blocked.errors[0].code, "daily_quota_exceeded")
        with self.store.connect() as connection:
            row = connection.execute(
                "SELECT status, actual_requests, actual_cost_usd FROM provider_budget_reservations"
            ).fetchone()
            metadata = json.loads(connection.execute("SELECT metadata_json FROM provider_usage").fetchone()[0])
        self.assertEqual(tuple(row), ("dispatched_failure_unknown", 1, 3.0))
        self.assertTrue(metadata["usage_uncertain"])

    def test_parser_failure_after_http_success_is_reconciled_as_dispatched_failure(self):
        class Provider:
            name = "parser"
            enabled = True
            cache_ttl_minutes = 0
            estimated_max_cost_usd = 1

            def estimated_max_requests(self, request):
                return 1

            def collect(self, request):
                return ProviderResult(
                    self.name, [], [ProviderError("malformed_response", "invalid JSON")],
                    False, 1, 0, 1, None, request.requested_at,
                )

        settings = ProviderSettings(enabled=True, daily_request_limit=1, daily_cost_limit_usd=1)
        result = CollectionCoordinator(self.store, clock=lambda: NOW).collect(
            Provider(), self._provider_request(), settings
        )
        self.assertEqual(result.errors[0].code, "malformed_response")
        with self.store.connect() as connection:
            status = connection.execute("SELECT status FROM provider_budget_reservations").fetchone()[0]
            metadata = json.loads(connection.execute("SELECT metadata_json FROM provider_usage").fetchone()[0])
        self.assertEqual(status, "dispatched_failure")
        self.assertFalse(metadata["usage_uncertain"])

    def test_concurrent_uncertain_failures_are_each_charged(self):
        barrier = threading.Barrier(2)

        class Provider:
            name = "uncertain-concurrent"
            enabled = True
            cache_ttl_minutes = 0
            estimated_max_cost_usd = 1

            def estimated_max_requests(self, request):
                return 1

            def collect(self, request):
                barrier.wait()
                raise ConnectionError("disconnect after dispatch")

        settings = ProviderSettings(enabled=True, daily_request_limit=2, daily_cost_limit_usd=2)
        errors = []
        provider_request = self._provider_request()

        def collect():
            try:
                CollectionCoordinator(self.store, clock=lambda: NOW).collect(Provider(), provider_request, settings)
            except ConnectionError as error:
                errors.append(error)

        threads = [threading.Thread(target=collect) for _ in range(2)]
        [thread.start() for thread in threads]
        [thread.join() for thread in threads]
        self.assertEqual(len(errors), 2)
        self.assertEqual(self.store.usage_requests_since("uncertain-concurrent", "2026-07-12T00:00:00Z"), 2)


if __name__ == "__main__":
    unittest.main()
