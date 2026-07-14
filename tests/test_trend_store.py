import os
import sys
import tempfile
import unittest
import sqlite3

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
        self.assertEqual(self.store.schema_versions(), [1, 2])

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
        self.assertTrue(os.path.isfile(path + ".v1.bak"))
        self.assertEqual(legacy.schema_versions(), [1, 2])


if __name__ == "__main__":
    unittest.main()
