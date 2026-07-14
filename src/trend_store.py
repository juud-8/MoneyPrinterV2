"""Versioned SQLite persistence for trend intelligence artifacts."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Iterator

from config import ROOT_DIR
from trend_models import ApprovalRecord, TopicSeed, TrendCluster, TrendOpportunity, TrendSignal, ValidationError


LATEST_SCHEMA_VERSION = 3


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
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self, *, fail_after_version: int | None = None) -> None:
        """Apply and verify migrations under one serialized SQLite transaction."""
        folder = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(folder, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            # A reserved writer lock serializes backup and migration while still
            # allowing the read connection used by sqlite3.Connection.backup().
            connection.execute("BEGIN IMMEDIATE")
            source_version, has_existing_data = self._source_schema_version(connection)
            if source_version > LATEST_SCHEMA_VERSION:
                raise RuntimeError(
                    f"database schema version {source_version} is newer than supported version {LATEST_SCHEMA_VERSION}"
                )
            if has_existing_data and source_version < LATEST_SCHEMA_VERSION:
                self._create_upgrade_backup(source_version, LATEST_SCHEMA_VERSION)
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            applied = {row["version"] for row in connection.execute("SELECT version FROM schema_migrations")}
            # Re-run idempotent DDL even for recorded versions. This repairs an
            # interrupted/manual schema where the ledger and objects disagree.
            self._migration_1(connection)
            self._verify_schema(connection, 1)
            if 1 not in applied:
                if fail_after_version == 1:
                    raise RuntimeError("injected migration failure after version 1")
                connection.execute("INSERT INTO schema_migrations(version) VALUES (1)")
                applied.add(1)
            self._migration_2(connection)
            self._verify_schema(connection, 2)
            if 2 not in applied:
                if fail_after_version == 2:
                    raise RuntimeError("injected migration failure after version 2")
                connection.execute("INSERT INTO schema_migrations(version) VALUES (2)")
                applied.add(2)
            self._migration_3(connection)
            self._verify_schema(connection, 3)
            if 3 not in applied:
                if fail_after_version == 3:
                    raise RuntimeError("injected migration failure after version 3")
                connection.execute("INSERT INTO schema_migrations(version) VALUES (3)")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _source_schema_version(connection: sqlite3.Connection) -> tuple[int, bool]:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if not tables:
            return 0, False
        if "schema_migrations" not in tables:
            return 0, True
        try:
            versions = [int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")]
        except sqlite3.DatabaseError as error:
            raise RuntimeError("cannot read schema_migrations; explicit database repair is required") from error
        return (max(versions) if versions else 0), True

    def _create_upgrade_backup(self, source_version: int, target_version: int) -> str:
        """Create, verify, and atomically publish a unique pre-upgrade backup."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = f"{self.path}.pre-v{source_version}-to-v{target_version}-{stamp}.bak"
        if os.path.exists(backup_path):
            backup_path = f"{backup_path}.{uuid.uuid4().hex}"
        temporary_path = f"{backup_path}.tmp-{uuid.uuid4().hex}"
        source = sqlite3.connect(self.path, timeout=30)
        try:
            destination = sqlite3.connect(temporary_path)
            try:
                source.backup(destination)
                destination.commit()
            finally:
                destination.close()
        finally:
            source.close()
        try:
            verification = sqlite3.connect(temporary_path)
            try:
                integrity = verification.execute("PRAGMA integrity_check").fetchone()
                if not integrity or integrity[0] != "ok":
                    raise RuntimeError("pre-upgrade backup failed SQLite integrity verification")
                version, _ = self._source_schema_version(verification)
                if version != source_version:
                    raise RuntimeError(
                        f"pre-upgrade backup version mismatch: expected {source_version}, found {version}"
                    )
            finally:
                verification.close()
            os.replace(temporary_path, backup_path)
        except Exception:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
            raise
        return backup_path

    @staticmethod
    def _migration_1(connection: sqlite3.Connection) -> None:
        statements = [
                    """CREATE TABLE IF NOT EXISTS trend_signals (
                        signal_id TEXT PRIMARY KEY,
                        provider TEXT NOT NULL,
                        provider_signal_id TEXT NOT NULL,
                        collected_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL DEFAULT '',
                        payload_json TEXT NOT NULL,
                        UNIQUE(provider, provider_signal_id, collected_at)
                    )""",
                    "CREATE INDEX IF NOT EXISTS idx_trend_signals_provider_time ON trend_signals(provider, collected_at)",
                    """CREATE TABLE IF NOT EXISTS trend_clusters (
                        cluster_id TEXT PRIMARY KEY,
                        canonical_entity TEXT NOT NULL,
                        first_seen TEXT NOT NULL,
                        last_seen TEXT NOT NULL,
                        payload_json TEXT NOT NULL
                    )""",
                    """CREATE TABLE IF NOT EXISTS trend_opportunities (
                        opportunity_id TEXT PRIMARY KEY,
                        brand_id TEXT NOT NULL,
                        cluster_id TEXT NOT NULL,
                        recommended_action TEXT NOT NULL,
                        eligible INTEGER NOT NULL,
                        opportunity_score REAL NOT NULL,
                        expires_at TEXT NOT NULL,
                        status TEXT NOT NULL,
                        payload_json TEXT NOT NULL
                    )""",
                    "CREATE INDEX IF NOT EXISTS idx_opportunities_brand_status ON trend_opportunities(brand_id, status, expires_at)",
                    """CREATE TABLE IF NOT EXISTS trend_approvals (
                        approval_id TEXT PRIMARY KEY,
                        opportunity_id TEXT NOT NULL,
                        brand_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        decided_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        FOREIGN KEY(opportunity_id) REFERENCES trend_opportunities(opportunity_id)
                    )""",
                    """CREATE TABLE IF NOT EXISTS topic_seeds (
                        seed_id TEXT PRIMARY KEY,
                        opportunity_id TEXT NOT NULL,
                        brand_id TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        consumed_at TEXT,
                        run_id TEXT,
                        payload_json TEXT NOT NULL,
                        FOREIGN KEY(opportunity_id) REFERENCES trend_opportunities(opportunity_id)
                    )""",
                    """CREATE TABLE IF NOT EXISTS provider_cache (
                        cache_key TEXT PRIMARY KEY,
                        provider TEXT NOT NULL,
                        stored_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL
                    )""",
                    """CREATE TABLE IF NOT EXISTS provider_usage (
                        usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        provider TEXT NOT NULL,
                        occurred_at TEXT NOT NULL,
                        request_count INTEGER NOT NULL,
                        resource_count INTEGER NOT NULL,
                        estimated_cost_usd REAL NOT NULL,
                        actual_cost_usd REAL,
                        metadata_json TEXT NOT NULL DEFAULT '{}'
                    )""",
                    "CREATE INDEX IF NOT EXISTS idx_provider_usage_time ON provider_usage(provider, occurred_at)",
        ]
        for statement in statements:
            connection.execute(statement)

    @classmethod
    def _migration_2(cls, connection: sqlite3.Connection) -> None:
        connection.execute("""CREATE TABLE IF NOT EXISTS trend_attribution (
                        attribution_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        seed_id TEXT NOT NULL,
                        opportunity_id TEXT NOT NULL,
                        brand_id TEXT NOT NULL,
                        run_id TEXT NOT NULL DEFAULT '',
                        youtube_video_id TEXT NOT NULL DEFAULT '',
                        detected_at TEXT NOT NULL,
                        approved_at TEXT NOT NULL,
                        publication_time TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        FOREIGN KEY(seed_id) REFERENCES topic_seeds(seed_id),
                        FOREIGN KEY(opportunity_id) REFERENCES trend_opportunities(opportunity_id)
                    )""")
        cls._ensure_columns(connection, "trend_attribution", {
            "seed_id": "TEXT NOT NULL DEFAULT ''", "opportunity_id": "TEXT NOT NULL DEFAULT ''",
            "brand_id": "TEXT NOT NULL DEFAULT ''", "run_id": "TEXT NOT NULL DEFAULT ''",
            "youtube_video_id": "TEXT NOT NULL DEFAULT ''", "detected_at": "TEXT NOT NULL DEFAULT ''",
            "approved_at": "TEXT NOT NULL DEFAULT ''", "publication_time": "TEXT NOT NULL DEFAULT ''",
            "status": "TEXT NOT NULL DEFAULT ''", "payload_json": "TEXT NOT NULL DEFAULT '{}'",
        })
        connection.execute("CREATE INDEX IF NOT EXISTS idx_trend_attribution_brand_time ON trend_attribution(brand_id, publication_time, approved_at)")

    @classmethod
    def _migration_3(cls, connection: sqlite3.Connection) -> None:
        cls._ensure_columns(connection, "topic_seeds", {
            "claimed_at": "TEXT", "claimed_by": "TEXT", "completed_at": "TEXT",
            "released_at": "TEXT", "failed_at": "TEXT", "failure_reason": "TEXT NOT NULL DEFAULT ''",
        })
        connection.execute("""CREATE TABLE IF NOT EXISTS provider_budget_reservations (
            reservation_id TEXT PRIMARY KEY, provider TEXT NOT NULL, reserved_at TEXT NOT NULL,
            status TEXT NOT NULL, reserved_requests INTEGER NOT NULL, reserved_cost_usd REAL NOT NULL,
            actual_requests INTEGER, actual_cost_usd REAL
        )""")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_budget_reservations_provider_time ON provider_budget_reservations(provider, reserved_at, status)")

    @staticmethod
    def _ensure_columns(connection: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        present = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        for name, declaration in columns.items():
            if name not in present:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")

    @classmethod
    def _verify_schema(cls, connection: sqlite3.Connection, version: int) -> None:
        text = ("TEXT", True, False)
        nullable_text = ("TEXT", False, False)
        integer = ("INTEGER", True, False)
        real = ("REAL", True, False)
        schemas = {
            1: {
                "trend_signals": ({"signal_id": ("TEXT", False, True), "provider": text, "provider_signal_id": text, "collected_at": text, "expires_at": text, "payload_json": text}, [("provider", "provider_signal_id", "collected_at")], [], {"idx_trend_signals_provider_time": ("provider", "collected_at")}),
                "trend_clusters": ({"cluster_id": ("TEXT", False, True), "canonical_entity": text, "first_seen": text, "last_seen": text, "payload_json": text}, [], [], {}),
                "trend_opportunities": ({"opportunity_id": ("TEXT", False, True), "brand_id": text, "cluster_id": text, "recommended_action": text, "eligible": integer, "opportunity_score": real, "expires_at": text, "status": text, "payload_json": text}, [], [], {"idx_opportunities_brand_status": ("brand_id", "status", "expires_at")}),
                "trend_approvals": ({"approval_id": ("TEXT", False, True), "opportunity_id": text, "brand_id": text, "status": text, "decided_at": text, "payload_json": text}, [], [("opportunity_id", "trend_opportunities", "opportunity_id")], {}),
                "topic_seeds": ({"seed_id": ("TEXT", False, True), "opportunity_id": text, "brand_id": text, "created_at": text, "consumed_at": nullable_text, "run_id": nullable_text, "payload_json": text}, [], [("opportunity_id", "trend_opportunities", "opportunity_id")], {}),
                "provider_cache": ({"cache_key": ("TEXT", False, True), "provider": text, "stored_at": text, "expires_at": text, "payload_json": text}, [], [], {}),
                "provider_usage": ({"usage_id": ("INTEGER", False, True), "provider": text, "occurred_at": text, "request_count": integer, "resource_count": integer, "estimated_cost_usd": real, "actual_cost_usd": ("REAL", False, False), "metadata_json": text}, [], [], {"idx_provider_usage_time": ("provider", "occurred_at")}),
            },
            2: {
                "trend_attribution": ({"attribution_id": ("INTEGER", False, True), "seed_id": text, "opportunity_id": text, "brand_id": text, "run_id": text, "youtube_video_id": text, "detected_at": text, "approved_at": text, "publication_time": text, "status": text, "payload_json": text}, [], [("seed_id", "topic_seeds", "seed_id"), ("opportunity_id", "trend_opportunities", "opportunity_id")], {"idx_trend_attribution_brand_time": ("brand_id", "publication_time", "approved_at")}),
            },
            3: {
                "topic_seeds": ({"claimed_at": nullable_text, "claimed_by": nullable_text, "completed_at": nullable_text, "released_at": nullable_text, "failed_at": nullable_text, "failure_reason": text}, [], [], {}),
                "provider_budget_reservations": ({"reservation_id": ("TEXT", False, True), "provider": text, "reserved_at": text, "status": text, "reserved_requests": integer, "reserved_cost_usd": real, "actual_requests": ("INTEGER", False, False), "actual_cost_usd": ("REAL", False, False)}, [], [], {"idx_budget_reservations_provider_time": ("provider", "reserved_at", "status")}),
            },
        }
        for table, (columns, unique_sets, foreign_keys, indexes) in schemas[version].items():
            cls._verify_table(connection, version, table, columns, unique_sets, foreign_keys, indexes)

    @staticmethod
    def _verify_table(
        connection: sqlite3.Connection,
        version: int,
        table: str,
        expected_columns: dict[str, tuple[str, bool, bool]],
        expected_unique_sets: list[tuple[str, ...]],
        expected_foreign_keys: list[tuple[str, str, str]],
        expected_indexes: dict[str, tuple[str, ...]],
    ) -> None:
        table_sql_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not table_sql_row:
            raise RuntimeError(f"migration {version} schema verification failed: missing table {table}")
        actual = {row[1]: row for row in connection.execute(f'PRAGMA table_info("{table}")')}
        problems = []
        for name, (affinity, required_not_null, primary_key) in expected_columns.items():
            row = actual.get(name)
            if row is None:
                problems.append(f"missing column {name}")
                continue
            declared = str(row[2] or "").upper()
            if affinity not in declared:
                problems.append(f"column {name} has type {declared or '<none>'}, expected {affinity}")
            if required_not_null and not bool(row[3]):
                problems.append(f"column {name} must be NOT NULL")
            if bool(row[5]) != primary_key:
                problems.append(f"column {name} primary-key mismatch")
        index_rows = list(connection.execute(f'PRAGMA index_list("{table}")'))
        unique_columns = {
            tuple(row[2] for row in connection.execute(f'PRAGMA index_info("{index[1]}")'))
            for index in index_rows if bool(index[2])
        }
        for columns in expected_unique_sets:
            if columns not in unique_columns:
                problems.append(f"missing unique constraint {columns}")
        available_indexes = {row[1] for row in index_rows}
        for index_name, columns in expected_indexes.items():
            if index_name not in available_indexes:
                problems.append(f"missing index {index_name}")
            else:
                actual_columns = tuple(
                    row[2] for row in connection.execute(f'PRAGMA index_info("{index_name}")')
                )
                if actual_columns != columns:
                    problems.append(f"index {index_name} columns {actual_columns}, expected {columns}")
        actual_foreign_keys = {
            (row[3], row[2], row[4]) for row in connection.execute(f'PRAGMA foreign_key_list("{table}")')
        }
        for foreign_key in expected_foreign_keys:
            if foreign_key not in actual_foreign_keys:
                problems.append(f"missing foreign key {foreign_key}")
        if problems:
            raise RuntimeError(
                f"migration {version} schema verification failed for {table}: " + "; ".join(problems)
            )

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

    def list_provider_refresh_due(self, provider: str, now: str) -> list[TrendSignal]:
        due = []
        current = datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(timezone.utc)
        for signal in self.list_signals(provider):
            value = str(signal.raw_metadata.get("refresh_due_at") or "")
            if value and datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc) <= current:
                due.append(signal)
        return due

    def purge_expired_provider_data(self, provider: str, now: str) -> int:
        """Delete provider records only after their recorded retention deadline."""
        self.migrate()
        current = datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(timezone.utc)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = list(connection.execute(
                "SELECT signal_id, payload_json FROM trend_signals WHERE provider = ?", (provider,)
            ))
            expired_ids = []
            for row in rows:
                payload = json.loads(row["payload_json"])
                value = str((payload.get("raw_metadata") or {}).get("delete_or_expire_at") or "")
                if value and datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc) <= current:
                    expired_ids.append(row["signal_id"])
            if expired_ids:
                expired_set = set(expired_ids)
                cluster_ids = []
                for cluster_row in connection.execute("SELECT cluster_id, payload_json FROM trend_clusters"):
                    cluster_payload = json.loads(cluster_row["payload_json"])
                    signal_ids = {
                        str(item.get("signal_id") or "")
                        for item in cluster_payload.get("signals", [])
                        if isinstance(item, dict)
                    }
                    if signal_ids & expired_set:
                        cluster_ids.append(cluster_row["cluster_id"])
                if cluster_ids:
                    placeholders = ",".join("?" for _ in cluster_ids)
                    opportunity_ids = [
                        row[0] for row in connection.execute(
                            f"SELECT opportunity_id FROM trend_opportunities WHERE cluster_id IN ({placeholders})",
                            cluster_ids,
                        )
                    ]
                    if opportunity_ids:
                        opportunity_placeholders = ",".join("?" for _ in opportunity_ids)
                        connection.execute(
                            f"DELETE FROM trend_attribution WHERE opportunity_id IN ({opportunity_placeholders})",
                            opportunity_ids,
                        )
                        connection.execute(
                            f"DELETE FROM topic_seeds WHERE opportunity_id IN ({opportunity_placeholders})",
                            opportunity_ids,
                        )
                        connection.execute(
                            f"DELETE FROM trend_approvals WHERE opportunity_id IN ({opportunity_placeholders})",
                            opportunity_ids,
                        )
                        connection.execute(
                            f"DELETE FROM trend_opportunities WHERE opportunity_id IN ({opportunity_placeholders})",
                            opportunity_ids,
                        )
                    connection.execute(
                        f"DELETE FROM trend_clusters WHERE cluster_id IN ({placeholders})", cluster_ids
                    )
                connection.executemany("DELETE FROM trend_signals WHERE signal_id = ?", [(value,) for value in expired_ids])
            connection.execute(
                "DELETE FROM provider_cache WHERE provider = ? AND expires_at <= ?", (provider, now)
            )
            return len(expired_ids)

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

    def list_clusters(self) -> list[TrendCluster]:
        self.migrate()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM trend_clusters ORDER BY last_seen DESC"
            )
            return [TrendCluster.from_dict(json.loads(row["payload_json"])) for row in rows]

    def save_opportunity(self, opportunity: TrendOpportunity) -> None:
        self.migrate()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO trend_opportunities
                   (opportunity_id, brand_id, cluster_id, recommended_action, eligible,
                    opportunity_score, expires_at, status, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(opportunity_id) DO UPDATE SET
                     brand_id=excluded.brand_id,
                     cluster_id=excluded.cluster_id,
                     recommended_action=excluded.recommended_action,
                     eligible=excluded.eligible,
                     opportunity_score=excluded.opportunity_score,
                     expires_at=excluded.expires_at,
                     status=excluded.status,
                     payload_json=excluded.payload_json""",
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

    def save_decision(
        self,
        opportunity: TrendOpportunity,
        approval: ApprovalRecord,
        seed: TopicSeed | None = None,
    ) -> None:
        """Persist a decision and optional seed atomically."""
        self.migrate()
        with self.connect() as connection:
            updated = connection.execute(
                """UPDATE trend_opportunities SET status = ?, payload_json = ?
                   WHERE opportunity_id = ?""",
                (opportunity.status.value, self._dump(opportunity.to_dict()), opportunity.opportunity_id),
            )
            if updated.rowcount != 1:
                raise ValueError(f"unknown opportunity: {opportunity.opportunity_id}")
            connection.execute(
                """INSERT INTO trend_approvals
                   (approval_id, opportunity_id, brand_id, status, decided_at, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    approval.approval_id,
                    approval.opportunity_id,
                    approval.brand_id,
                    approval.status.value,
                    approval.decided_at,
                    self._dump(approval.to_dict()),
                ),
            )
            if seed is not None:
                connection.execute(
                    """INSERT INTO topic_seeds
                       (seed_id, opportunity_id, brand_id, created_at, payload_json)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        seed.seed_id,
                        opportunity.opportunity_id,
                        seed.brand_id,
                        seed.created_at,
                        self._dump(seed.to_dict()),
                    ),
                )

    def save_approval_with_mix(
        self,
        opportunity: TrendOpportunity,
        approval: ApprovalRecord,
        seed: TopicSeed,
        *,
        cutoff: str,
        uploaded_total: int,
        uploaded_trend: int,
        maximum_share: float,
    ) -> tuple[ApprovalRecord, TopicSeed, tuple[int, int, float, float]]:
        """Atomically reserve mix capacity and persist an approval and seed."""
        self.migrate()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            approved = int(connection.execute(
                "SELECT COUNT(*) FROM trend_approvals WHERE brand_id = ? AND status = 'approved' AND decided_at >= ?",
                (approval.brand_id, cutoff),
            ).fetchone()[0])
            reserved = max(approved - uploaded_trend, 0)
            trend_count = uploaded_trend + reserved
            total = uploaded_total + reserved
            previous_share = trend_count / total if total else 0.0
            resulting_share = (trend_count + 1) / (total + 1)
            if resulting_share > maximum_share and not approval.content_mix_override:
                raise ValidationError("trend-assisted content share would exceed its configured maximum")
            if approval.content_mix_override and (not approval.operator.strip() or not approval.override_reason.strip()):
                raise ValidationError("content-mix override requires operator and reason")
            approval = replace(
                approval,
                previous_calculated_share=previous_share,
                resulting_calculated_share=resulting_share,
            )
            seed = replace(seed, approval_record=approval)
            self._save_decision(connection, opportunity, approval, seed)
            return approval, seed, (total, trend_count, previous_share, resulting_share)

    def _save_decision(
        self,
        connection: sqlite3.Connection,
        opportunity: TrendOpportunity,
        approval: ApprovalRecord,
        seed: TopicSeed | None,
    ) -> None:
        updated = connection.execute(
            "UPDATE trend_opportunities SET status = ?, payload_json = ? WHERE opportunity_id = ? AND status = 'pending'",
            (opportunity.status.value, self._dump(opportunity.to_dict()), opportunity.opportunity_id),
        )
        if updated.rowcount != 1:
            raise ValidationError("opportunity has already been decided")
        connection.execute(
            "INSERT INTO trend_approvals (approval_id, opportunity_id, brand_id, status, decided_at, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            (approval.approval_id, approval.opportunity_id, approval.brand_id, approval.status.value, approval.decided_at, self._dump(approval.to_dict())),
        )
        if seed is not None:
            connection.execute(
                "INSERT INTO topic_seeds (seed_id, opportunity_id, brand_id, created_at, payload_json) VALUES (?, ?, ?, ?, ?)",
                (seed.seed_id, opportunity.opportunity_id, seed.brand_id, seed.created_at, self._dump(seed.to_dict())),
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

    def claim_topic_seed(self, seed_id: str, claimed_by: str, claimed_at: str) -> bool:
        if not claimed_by.strip():
            raise ValidationError("TopicSeed claim requires a claimant")
        self.migrate()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                """UPDATE topic_seeds SET claimed_at = ?, claimed_by = ?, released_at = NULL,
                   failure_reason = '' WHERE seed_id = ? AND claimed_at IS NULL
                   AND completed_at IS NULL AND failed_at IS NULL""",
                (claimed_at, claimed_by, seed_id),
            )
            return updated.rowcount == 1

    def release_topic_seed(self, seed_id: str, claimed_by: str, released_at: str, reason: str) -> bool:
        if not reason.strip():
            raise ValidationError("TopicSeed release requires a reason")
        self.migrate()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                """UPDATE topic_seeds SET claimed_at = NULL, claimed_by = NULL,
                   released_at = ?, failure_reason = ? WHERE seed_id = ? AND claimed_by = ?
                   AND completed_at IS NULL AND failed_at IS NULL""",
                (released_at, reason, seed_id, claimed_by),
            )
            return updated.rowcount == 1

    def complete_topic_seed(
        self, seed_id: str, claimed_by: str, completed_at: str, *, run_id: str | None = None,
    ) -> bool:
        self.migrate()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                """UPDATE topic_seeds SET completed_at = ?, consumed_at = ?, run_id = ?
                   WHERE seed_id = ? AND claimed_by = ? AND completed_at IS NULL AND failed_at IS NULL""",
                (completed_at, completed_at, run_id or claimed_by, seed_id, claimed_by),
            )
            return updated.rowcount == 1

    def fail_topic_seed(self, seed_id: str, claimed_by: str, failed_at: str, reason: str) -> bool:
        if not reason.strip():
            raise ValidationError("TopicSeed failure requires a reason")
        self.migrate()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                "UPDATE topic_seeds SET failed_at = ?, failure_reason = ? WHERE seed_id = ? AND claimed_by = ? AND completed_at IS NULL",
                (failed_at, reason, seed_id, claimed_by),
            )
            return updated.rowcount == 1

    def count_approved_since(self, brand_id: str, since: str) -> int:
        self.migrate()
        with self.connect() as connection:
            row = connection.execute(
                """SELECT COUNT(*) AS count FROM trend_approvals
                   WHERE brand_id = ? AND status = 'approved' AND decided_at >= ?""",
                (brand_id, since),
            ).fetchone()
        return int(row["count"] or 0)

    def save_attribution(
        self,
        *,
        seed_id: str,
        opportunity_id: str,
        brand_id: str,
        detected_at: str,
        approved_at: str,
        status: str,
        payload: dict,
        run_id: str = "",
        youtube_video_id: str = "",
        publication_time: str = "",
    ) -> None:
        self.migrate()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO trend_attribution
                   (seed_id, opportunity_id, brand_id, run_id, youtube_video_id,
                    detected_at, approved_at, publication_time, status, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    seed_id,
                    opportunity_id,
                    brand_id,
                    run_id,
                    youtube_video_id,
                    detected_at,
                    approved_at,
                    publication_time,
                    status,
                    self._dump(payload),
                ),
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

    def reserve_provider_budget(
        self, provider: str, reserved_at: str, estimated_requests: int, estimated_cost_usd: float,
        *, daily_since: str, monthly_since: str, daily_request_limit: int,
        daily_cost_limit_usd: float, monthly_cost_limit_usd: float,
    ) -> tuple[str | None, str | None]:
        """Reserve the maximum request spend under a serialized transaction."""
        self.migrate()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            usage = connection.execute(
                """SELECT COALESCE(SUM(request_count),0),
                   COALESCE(SUM(CASE WHEN occurred_at >= ? THEN COALESCE(actual_cost_usd, estimated_cost_usd) ELSE 0 END),0),
                   COALESCE(SUM(COALESCE(actual_cost_usd, estimated_cost_usd)),0)
                   FROM provider_usage WHERE provider = ? AND occurred_at >= ?""",
                (daily_since, provider, monthly_since),
            ).fetchone()
            active = connection.execute(
                """SELECT COALESCE(SUM(reserved_requests),0),
                   COALESCE(SUM(CASE WHEN reserved_at >= ? THEN reserved_cost_usd ELSE 0 END),0),
                   COALESCE(SUM(reserved_cost_usd),0) FROM provider_budget_reservations
                   WHERE provider = ? AND status = 'reserved' AND reserved_at >= ?""",
                (daily_since, provider, monthly_since),
            ).fetchone()
            requests = int(usage[0]) + int(active[0])
            daily_cost = float(usage[1]) + float(active[1])
            monthly_cost = float(usage[2]) + float(active[2])
            if daily_request_limit and requests + estimated_requests > daily_request_limit:
                return None, "daily_quota_exceeded"
            if daily_cost_limit_usd and daily_cost + estimated_cost_usd > daily_cost_limit_usd:
                return None, "daily_budget_exceeded"
            if monthly_cost_limit_usd and monthly_cost + estimated_cost_usd > monthly_cost_limit_usd:
                return None, "monthly_budget_exceeded"
            reservation_id = uuid.uuid4().hex
            connection.execute(
                "INSERT INTO provider_budget_reservations VALUES (?, ?, ?, 'reserved', ?, ?, NULL, NULL)",
                (reservation_id, provider, reserved_at, estimated_requests, estimated_cost_usd),
            )
            return reservation_id, None

    def reconcile_provider_budget(
        self, reservation_id: str, *, request_count: int, resource_count: int,
        estimated_cost_usd: float, actual_cost_usd: float | None, metadata: dict,
        outcome: str = "dispatched_success",
    ) -> None:
        if outcome not in {"dispatched_success", "dispatched_failure"}:
            raise ValidationError("invalid provider budget outcome")
        self.migrate()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT provider, reserved_at FROM provider_budget_reservations WHERE reservation_id = ? AND status = 'reserved'",
                (reservation_id,),
            ).fetchone()
            if not row:
                raise ValidationError("unknown or reconciled provider budget reservation")
            connection.execute(
                "UPDATE provider_budget_reservations SET status=?, actual_requests=?, actual_cost_usd=? WHERE reservation_id=?",
                (outcome, request_count, actual_cost_usd if actual_cost_usd is not None else estimated_cost_usd, reservation_id),
            )
            connection.execute(
                """INSERT INTO provider_usage (provider, occurred_at, request_count, resource_count,
                   estimated_cost_usd, actual_cost_usd, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (row["provider"], row["reserved_at"], request_count, resource_count, estimated_cost_usd, actual_cost_usd, self._dump({**metadata, "budget_outcome": outcome, "usage_uncertain": False})),
            )

    def release_provider_budget(self, reservation_id: str, *, reason: str) -> None:
        self.migrate()
        with self.connect() as connection:
            updated = connection.execute(
                "UPDATE provider_budget_reservations SET status='released_not_dispatched' WHERE reservation_id=? AND status='reserved'",
                (reservation_id,),
            )
            if updated.rowcount != 1:
                raise ValidationError("unknown or reconciled provider budget reservation")

    def charge_uncertain_provider_budget(self, reservation_id: str, *, metadata: dict) -> None:
        """Conservatively charge the reservation when dispatch may have occurred."""
        self.migrate()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT provider, reserved_at, reserved_requests, reserved_cost_usd
                   FROM provider_budget_reservations
                   WHERE reservation_id = ? AND status = 'reserved'""",
                (reservation_id,),
            ).fetchone()
            if not row:
                raise ValidationError("unknown or reconciled provider budget reservation")
            connection.execute(
                """UPDATE provider_budget_reservations
                   SET status='dispatched_failure_unknown', actual_requests=reserved_requests,
                       actual_cost_usd=reserved_cost_usd WHERE reservation_id=?""",
                (reservation_id,),
            )
            lifecycle = {
                **metadata,
                "budget_outcome": "dispatched_failure_unknown",
                "usage_uncertain": True,
                "charged_at_reserved_maximum": True,
            }
            connection.execute(
                """INSERT INTO provider_usage (provider, occurred_at, request_count, resource_count,
                   estimated_cost_usd, actual_cost_usd, metadata_json) VALUES (?, ?, ?, 0, ?, ?, ?)""",
                (
                    row["provider"], row["reserved_at"], row["reserved_requests"],
                    row["reserved_cost_usd"], row["reserved_cost_usd"], self._dump(lifecycle),
                ),
            )
