import os
import sys
import tempfile
import unittest
import sqlite3
from glob import glob
from contextlib import closing

ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trend_models import TrendSignal
from trend_store import TrendStore


class TrendStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TrendStore(os.path.join(self.tmp.name, "trends.sqlite3"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_migration_is_repeatable(self):
        self.store.migrate()
        self.store.migrate()
        self.assertEqual(self.store.schema_versions(), [1, 2, 3])

    def test_signal_round_trip(self):
        signal = TrendSignal.from_dict(
            {
                "provider": "manual",
                "provider_signal_id": "manual-1",
                "collected_at": "2026-07-13T12:00:00Z",
                "term": "bison",
                "normalized_entity": "american bison",
                "aliases": ["bison", "buffalo"],
            }
        )
        self.store.save_signal(signal)
        restored = self.store.list_signals("manual")
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0].signal_id, signal.signal_id)

    def test_existing_v1_database_is_backed_up_before_migration(self):
        path = os.path.join(self.tmp.name, "legacy.sqlite3")
        connection = sqlite3.connect(path)
        connection.executescript(
            """
            CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT);
            INSERT INTO schema_migrations(version, applied_at) VALUES (1, CURRENT_TIMESTAMP);
            """
        )
        connection.close()
        legacy = TrendStore(path)
        legacy.migrate()
        backups = glob(path + ".pre-v1-to-v3-*.bak")
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as backup:
            self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(backup.execute("SELECT max(version) FROM schema_migrations").fetchone()[0], 1)
        self.assertEqual(legacy.schema_versions(), [1, 2, 3])

    def test_v2_database_gets_validated_pre_upgrade_backup(self):
        self.store.migrate()
        with closing(sqlite3.connect(self.store.path)) as connection:
            connection.execute("DELETE FROM schema_migrations WHERE version = 3")
            connection.commit()
        self.store.migrate()
        backups = glob(self.store.path + ".pre-v2-to-v3-*.bak")
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as backup:
            self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(backup.execute("SELECT max(version) FROM schema_migrations").fetchone()[0], 2)

    def test_backups_are_never_silently_overwritten(self):
        self.store.migrate()
        with closing(sqlite3.connect(self.store.path)) as connection:
            connection.execute("DELETE FROM schema_migrations WHERE version = 3")
            connection.commit()
        self.store.migrate()
        with closing(sqlite3.connect(self.store.path)) as connection:
            connection.execute("DELETE FROM schema_migrations WHERE version = 3")
            connection.commit()
        self.store.migrate()
        self.assertEqual(len(glob(self.store.path + ".pre-v2-to-v3-*.bak")), 2)


if __name__ == "__main__":
    unittest.main()
