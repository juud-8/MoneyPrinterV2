import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trend_entities import cluster_signals, resolve_entity
from trend_models import TrendSignal


def signal(term, entity, aliases=None, related=None, provider="manual"):
    return TrendSignal.from_dict(
        {
            "provider": provider,
            "provider_signal_id": f"{provider}-{term}",
            "collected_at": "2026-07-13T12:00:00Z",
            "term": term,
            "normalized_entity": entity,
            "aliases": aliases or [],
            "related_terms": related or [],
            "entity_type": "unknown",
            "geography": "US",
            "language": "en",
            "window_hours": 24,
        }
    )


class EntityTests(unittest.TestCase):
    def test_buffalo_animal_context(self):
        canonical, competing = resolve_entity(signal("#Bison", "buffalo", related=["mammal herd preservation"]))
        self.assertEqual(canonical, "american bison")
        self.assertEqual(competing, [])

    def test_buffalo_new_york_context(self):
        canonical, competing = resolve_entity(signal("Buffalo", "buffalo", related=["New York city Bills"]))
        self.assertEqual(canonical, "buffalo, new york")
        self.assertEqual(competing, [])

    def test_ambiguous_buffalo_preserves_interpretations(self):
        canonical, competing = resolve_entity(signal("Buffalo", "buffalo"))
        self.assertEqual(canonical, "buffalo")
        self.assertEqual(len(competing), 2)

    def test_cross_source_count_uses_providers_not_signal_count(self):
        signals = [
            signal("dance", "dance", provider="manual"),
            signal("dancing", "dance", provider="manual"),
            signal("dance", "dance", provider="gdelt"),
        ]
        cluster = cluster_signals(signals, now="2026-07-13T13:00:00Z")[0]
        self.assertEqual(cluster.cross_source_count, 2)

    def test_reliable_multilingual_alias(self):
        canonical, competing = resolve_entity(signal("Bisonte americano", "bisonte americano"))
        self.assertEqual(canonical, "american bison")
        self.assertEqual(competing, [])

    def test_provider_disagreement_is_explicit(self):
        left = signal("dance", "dance", provider="x")
        right = signal("dance", "dance", provider="gdelt")
        left_payload = left.to_dict()
        right_payload = right.to_dict()
        left_payload["velocity"] = 95
        right_payload["velocity"] = 15
        cluster = cluster_signals(
            [TrendSignal.from_dict(left_payload), TrendSignal.from_dict(right_payload)],
            now="2026-07-13T13:00:00Z",
        )[0]
        self.assertIn("provider velocity signals materially disagree", cluster.unknowns)


if __name__ == "__main__":
    unittest.main()
