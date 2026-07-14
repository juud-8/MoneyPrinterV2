import os
import sys
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
