"""Versioned SQLite persistence for trend intelligence artifacts."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Iterator

from config import ROOT_DIR
from trend_models import ApprovalRecord, TopicSeed, TrendCluster, TrendOpportunity, TrendSignal


LATEST_SCHEMA_VERSION = 1


def default_store_path() -> str:
    return os.path.join(ROOT_DIR, ".mp", "trends.sqlite3")


class TrendStore:
    def __init__(self, path: str | None = None):
        self.path = path or default_store_path()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        folder = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(folder, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> None:
        with self.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            applied = {
                row["version"]
                for row in connection.execute("SELECT version FROM schema_migrations")
            }
            if 1 not in applied:
                connection.executescript(
                    """
                    CREATE TABLE trend_signals (
                        signal_id TEXT PRIMARY KEY,
                        provider TEXT NOT NULL,
                        provider_signal_id TEXT NOT NULL,
                        collected_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL DEFAULT '',
                        payload_json TEXT NOT NULL,
                        UNIQUE(provider, provider_signal_id, collected_at)
                    );
                    CREATE INDEX idx_trend_signals_provider_time ON trend_signals(provider, collected_at);

                    CREATE TABLE trend_clusters (
                        cluster_id TEXT PRIMARY KEY,
                        canonical_entity TEXT NOT NULL,
                        first_seen TEXT NOT NULL,
                        last_seen TEXT NOT NULL,
                        payload_json TEXT NOT NULL
                    );

                    CREATE TABLE trend_opportunities (
                        opportunity_id TEXT PRIMARY KEY,
                        brand_id TEXT NOT NULL,
                        cluster_id TEXT NOT NULL,
                        recommended_action TEXT NOT NULL,
                        eligible INTEGER NOT NULL,
                        opportunity_score REAL NOT NULL,
                        expires_at TEXT NOT NULL,
                        status TEXT NOT NULL,
                        payload_json TEXT NOT NULL
                    );
                    CREATE INDEX idx_opportunities_brand_status ON trend_opportunities(brand_id, status, expires_at);

                    CREATE TABLE trend_approvals (
                        approval_id TEXT PRIMARY KEY,
                        opportunity_id TEXT NOT NULL,
                        brand_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        decided_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        FOREIGN KEY(opportunity_id) REFERENCES trend_opportunities(opportunity_id)
                    );

                    CREATE TABLE topic_seeds (
                        seed_id TEXT PRIMARY KEY,
                        opportunity_id TEXT NOT NULL,
                        brand_id TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        consumed_at TEXT,
                        run_id TEXT,
                        payload_json TEXT NOT NULL,
                        FOREIGN KEY(opportunity_id) REFERENCES trend_opportunities(opportunity_id)
                    );

                    CREATE TABLE provider_cache (
                        cache_key TEXT PRIMARY KEY,
                        provider TEXT NOT NULL,
                        stored_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL
                    );

                    CREATE TABLE provider_usage (
                        usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        provider TEXT NOT NULL,
                        occurred_at TEXT NOT NULL,
                        request_count INTEGER NOT NULL,
                        resource_count INTEGER NOT NULL,
                        estimated_cost_usd REAL NOT NULL,
                        actual_cost_usd REAL,
                        metadata_json TEXT NOT NULL DEFAULT '{}'
                    );
                    CREATE INDEX idx_provider_usage_time ON provider_usage(provider, occurred_at);
                    """
                )
                connection.execute("INSERT INTO schema_migrations(version) VALUES (1)")

    @staticmethod
    def _dump(payload: dict) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _load(row: sqlite3.Row | None) -> dict | None:
        return json.loads(row["payload_json"]) if row else None

    def save_signal(self, signal: TrendSignal) -> None:
        self.migrate()
        with self.connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO trend_signals
                   (signal_id, provider, provider_signal_id, collected_at, expires_at, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (signal.signal_id, signal.provider, signal.provider_signal_id, signal.collected_at, signal.expires_at, self._dump(signal.to_dict())),
            )

    def list_signals(self, provider: str | None = None) -> list[TrendSignal]:
        self.migrate()
        query = "SELECT payload_json FROM trend_signals"
        parameters: tuple = ()
        if provider:
            query += " WHERE provider = ?"
            parameters = (provider,)
        query += " ORDER BY collected_at DESC"
        with self.connect() as connection:
            return [TrendSignal.from_dict(json.loads(row["payload_json"])) for row in connection.execute(query, parameters)]

    def save_cluster(self, cluster: TrendCluster) -> None:
        self.migrate()
        with self.connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO trend_clusters
                   (cluster_id, canonical_entity, first_seen, last_seen, payload_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (cluster.cluster_id, cluster.canonical_entity, cluster.first_seen, cluster.last_seen, self._dump(cluster.to_dict())),
            )

    def get_cluster(self, cluster_id: str) -> TrendCluster | None:
        self.migrate()
        with self.connect() as connection:
            row = connection.execute("SELECT payload_json FROM trend_clusters WHERE cluster_id = ?", (cluster_id,)).fetchone()
        payload = self._load(row)
        return TrendCluster.from_dict(payload) if payload else None

    def save_opportunity(self, opportunity: TrendOpportunity) -> None:
        self.migrate()
        with self.connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO trend_opportunities
                   (opportunity_id, brand_id, cluster_id, recommended_action, eligible,
                    opportunity_score, expires_at, status, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    opportunity.opportunity_id,
                    opportunity.brand_id,
                    opportunity.trend.cluster_id,
                    opportunity.recommended_action.value,
                    int(opportunity.eligible),
                    opportunity.opportunity_score,
                    opportunity.expires_at,
                    opportunity.status.value,
                    self._dump(opportunity.to_dict()),
                ),
            )

    def get_opportunity(self, opportunity_id: str) -> TrendOpportunity | None:
        self.migrate()
        with self.connect() as connection:
            row = connection.execute("SELECT payload_json FROM trend_opportunities WHERE opportunity_id = ?", (opportunity_id,)).fetchone()
        payload = self._load(row)
        return TrendOpportunity.from_dict(payload) if payload else None

    def list_opportunities(self, brand_id: str | None = None) -> list[TrendOpportunity]:
        self.migrate()
        query = "SELECT payload_json FROM trend_opportunities"
        parameters: tuple = ()
        if brand_id:
            query += " WHERE brand_id = ?"
            parameters = (brand_id,)
        query += " ORDER BY opportunity_score DESC"
        with self.connect() as connection:
            return [TrendOpportunity.from_dict(json.loads(row["payload_json"])) for row in connection.execute(query, parameters)]

    def save_approval(self, approval: ApprovalRecord) -> None:
        self.migrate()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO trend_approvals
                   (approval_id, opportunity_id, brand_id, status, decided_at, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (approval.approval_id, approval.opportunity_id, approval.brand_id, approval.status.value, approval.decided_at, self._dump(approval.to_dict())),
            )

    def save_topic_seed(self, seed: TopicSeed, opportunity_id: str) -> None:
        self.migrate()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO topic_seeds
                   (seed_id, opportunity_id, brand_id, created_at, payload_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (seed.seed_id, opportunity_id, seed.brand_id, seed.created_at, self._dump(seed.to_dict())),
            )

    def get_topic_seed(self, seed_id: str) -> TopicSeed | None:
        self.migrate()
        with self.connect() as connection:
            row = connection.execute("SELECT payload_json FROM topic_seeds WHERE seed_id = ?", (seed_id,)).fetchone()
        payload = self._load(row)
        return TopicSeed.from_dict(payload) if payload else None

    def mark_seed_consumed(self, seed_id: str, run_id: str, consumed_at: str) -> None:
        self.migrate()
        with self.connect() as connection:
            connection.execute(
                "UPDATE topic_seeds SET run_id = ?, consumed_at = ? WHERE seed_id = ?",
                (run_id, consumed_at, seed_id),
            )

    def schema_versions(self) -> list[int]:
        self.migrate()
        with self.connect() as connection:
            return [row["version"] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]

    def get_cache(self, cache_key: str, now: str) -> dict | None:
        self.migrate()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload_json, expires_at FROM provider_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        if not row:
            return None
        current = datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(timezone.utc)
        expires = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
        return json.loads(row["payload_json"]) if current < expires else None

    def set_cache(self, cache_key: str, provider: str, stored_at: str, expires_at: str, payload: dict) -> None:
        self.migrate()
        with self.connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO provider_cache
                   (cache_key, provider, stored_at, expires_at, payload_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (cache_key, provider, stored_at, expires_at, self._dump(payload)),
            )

    def record_usage(
        self,
        provider: str,
        occurred_at: str,
        request_count: int,
        resource_count: int,
        estimated_cost_usd: float,
        actual_cost_usd: float | None,
        metadata: dict | None = None,
    ) -> None:
        self.migrate()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO provider_usage
                   (provider, occurred_at, request_count, resource_count,
                    estimated_cost_usd, actual_cost_usd, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    provider,
                    occurred_at,
                    request_count,
                    resource_count,
                    estimated_cost_usd,
                    actual_cost_usd,
                    self._dump(metadata or {}),
                ),
            )

    def usage_cost_since(self, provider: str, since: str) -> float:
        self.migrate()
        with self.connect() as connection:
            row = connection.execute(
                """SELECT COALESCE(SUM(COALESCE(actual_cost_usd, estimated_cost_usd)), 0) AS cost
                   FROM provider_usage WHERE provider = ? AND occurred_at >= ?""",
                (provider, since),
            ).fetchone()
        return float(row["cost"] or 0)

    def usage_requests_since(self, provider: str, since: str) -> int:
        self.migrate()
        with self.connect() as connection:
            row = connection.execute(
                """SELECT COALESCE(SUM(request_count), 0) AS requests
                   FROM provider_usage WHERE provider = ? AND occurred_at >= ?""",
                (provider, since),
            ).fetchone()
        return int(row["requests"] or 0)
