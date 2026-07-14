import os
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trend_entities import cluster_signals
from trend_models import TrendSignal
from trend_store import TrendStore

NOW = "2026-07-13T12:00:00Z"


def signal(*, provider="manual", provider_id="one", collected=NOW, term="dance",
           entity="dance", geography="US", related=None, expires=None, velocity=50):
    payload = {
        "provider": provider, "provider_signal_id": provider_id, "collected_at": collected,
        "term": term, "normalized_entity": entity, "geography": geography, "language": "en",
        "window_hours": 24, "velocity": velocity, "related_terms": related or [],
    }
    if expires is not None:
        payload["expires_at"] = expires
    return TrendSignal.from_dict(payload)


class IdentityAndExpirationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TrendStore(os.path.join(self.tmp.name, "trends.sqlite3"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_signal_identity_is_stable_for_same_evidence(self):
        self.assertEqual(signal().signal_id, signal().signal_id)

    def test_repeated_signal_and_cluster_upserts_do_not_duplicate(self):
        first = signal()
        for _ in range(2):
            self.store.save_signal(first)
            for cluster in cluster_signals([first], now=NOW, brand_id="archive"):
                self.store.save_cluster(cluster)
        self.assertEqual(len(self.store.list_signals()), 1)
        self.assertEqual(len(self.store.list_clusters()), 1)

    def test_updated_observation_keeps_cluster_identity(self):
        first = signal(velocity=20)
        later = signal(provider_id="two", provider="gdelt", collected="2026-07-13T16:00:00Z", velocity=80)
        left = cluster_signals([first], now=NOW, brand_id="archive")[0]
        right = cluster_signals([first, later], now="2026-07-13T16:00:00Z", brand_id="archive")[0]
        self.assertEqual(left.cluster_id, right.cluster_id)
        self.assertEqual(len(right.signals), 2)

    def test_same_entity_different_geography_is_separate(self):
        clusters = cluster_signals([signal(geography="US"), signal(provider_id="ca", geography="CA")], now=NOW, brand_id="archive")
        self.assertEqual(len(clusters), 2)
        self.assertNotEqual(clusters[0].cluster_id, clusters[1].cluster_id)

    def test_buffalo_city_and_animal_are_separate(self):
        animal = signal(term="Buffalo", entity="buffalo", related=["bison herd animal"])
        city = signal(provider_id="city", term="Buffalo", entity="buffalo", related=["New York city Bills"])
        entities = {item.canonical_entity for item in cluster_signals([animal, city], now=NOW, brand_id="archive")}
        self.assertEqual(entities, {"american bison", "buffalo, new york"})

    def test_missing_expiration_is_derived_at_collection_time(self):
        item = signal()
        self.assertEqual(item.expires_at, "2026-07-14T12:00:00Z")

    def test_expired_signals_are_rejected_individually(self):
        old = signal(provider_id="old", expires="2026-07-13T11:00:00Z")
        fresh = signal(provider_id="fresh", provider="gdelt", expires="2026-07-14T12:00:00Z")
        clusters = cluster_signals([old, fresh], now=NOW, brand_id="archive")
        self.assertEqual(len(clusters), 1)
        self.assertEqual([item.provider_signal_id for item in clusters[0].signals], ["fresh"])

    def test_all_expired_signals_do_not_get_a_renewed_cluster(self):
        old = signal(expires="2026-07-13T11:00:00Z")
        self.assertEqual(cluster_signals([old], now=NOW, brand_id="archive"), [])

    def test_concurrent_same_collection_remains_idempotent(self):
        item = signal()
        barrier = threading.Barrier(3)
        errors = []

        def save():
            try:
                barrier.wait()
                self.store.save_signal(item)
                self.store.save_cluster(cluster_signals([item], now=NOW, brand_id="archive")[0])
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=save) for _ in range(3)]
        [thread.start() for thread in threads]
        [thread.join() for thread in threads]
        self.assertEqual(errors, [])
        self.assertEqual(len(self.store.list_signals()), 1)
        self.assertEqual(len(self.store.list_clusters()), 1)


if __name__ == "__main__":
    unittest.main()
