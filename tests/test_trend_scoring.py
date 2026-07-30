import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trend_catalog import CatalogMatch
from trend_entities import cluster_signals
from trend_models import ArchiveBridge, CatalogDecision, ScoreComponent, TrendSignal
from trend_scoring import TrendPolicy, advisory_score, build_opportunity


NOW = "2026-07-13T12:00:00Z"
EXPIRES = "2026-07-15T12:00:00Z"


def signal(provider, velocity=90, active_tragedy=False):
    return TrendSignal.from_dict(
        {
            "provider": provider,
            "provider_signal_id": provider,
            "collected_at": NOW,
            "term": "dance",
            "normalized_entity": "dance",
            "entity_type": "concept",
            "geography": "US",
            "language": "en",
            "window_hours": 24,
            "velocity": velocity,
            "source_urls": [f"https://{provider}.test/current"],
            "raw_metadata": {"unique_domains": 4, "active_tragedy": active_tragedy},
        }
    )


def bridge(**overrides):
    payload = {
        "trend_cluster_id": "placeholder",
        "current_trigger_summary": "Safe current dance fixture",
        "historical_event": "The dancing plague of 1518",
        "relationship_type": "exact_entity",
        "relationship_explanation": "Both concern public dancing, separated by five centuries.",
        "specific_number": "1518",
        "absurd_contradiction": "Officials prescribed more dancing to people who could not stop.",
        "first_spoken_sentence": "In 1518, officials prescribed more dancing to people who could not stop.",
        "first_frame_text": "THE CURE WAS MORE DANCING",
        "working_titles": [],
        "central_payoff": "The attempted cure repeated the apparent symptom.",
        "target_seconds": 55,
        "archive_fit_score": 95,
        "sourceability_score": 95,
        "visual_potential_score": 80,
        "competition_score": 20,
        "duplicate_similarity": 5,
        "risk_flags": [],
        "supporting_sources": [],
        "historical_sources": ["https://history.test/a", "https://archive.test/b"],
    }
    payload.update(overrides)
    return payload


class ScoringTests(unittest.TestCase):
    def test_unknown_component_does_not_become_zero(self):
        known = ScoreComponent.from_dict({"name": "archive_fit", "score": 90, "confidence": 1, "source": "test"})
        unknown = ScoreComponent.from_dict({"name": "search_intent", "score": None, "confidence": 0, "source": "test", "unknown_reason": "missing"})
        self.assertEqual(advisory_score([known, unknown]), 90)

    def test_valid_opportunity_is_new_video(self):
        cluster = cluster_signals([signal("manual"), signal("gdelt")], now=NOW)[0]
        candidate = ArchiveBridge.from_dict({**bridge(), "trend_cluster_id": cluster.cluster_id})
        opportunity = build_opportunity(
            cluster,
            candidate,
            "archive",
            CatalogMatch(CatalogDecision.NEW_VIDEO, 0, None, "new"),
            EXPIRES,
            NOW,
            TrendPolicy(minimum_opportunity_score=50),
        )
        self.assertTrue(opportunity.eligible)
        self.assertEqual(opportunity.recommended_action.value, "new_video")

    def test_high_velocity_weak_archive_fit_is_skipped(self):
        cluster = cluster_signals([signal("manual", 99), signal("gdelt", 99)], now=NOW)[0]
        candidate = ArchiveBridge.from_dict({**bridge(archive_fit_score=20), "trend_cluster_id": cluster.cluster_id})
        opportunity = build_opportunity(
            cluster, candidate, "archive", CatalogMatch(CatalogDecision.NEW_VIDEO, 0, None, "new"), EXPIRES, NOW
        )
        self.assertFalse(opportunity.eligible)
        self.assertIn("archive fit below threshold", opportunity.eligibility_failures)

    def test_active_tragedy_hard_rejects(self):
        cluster = cluster_signals([signal("manual"), signal("gdelt")], now=NOW)[0]
        candidate = ArchiveBridge.from_dict({**bridge(risk_flags=["active_tragedy"]), "trend_cluster_id": cluster.cluster_id})
        opportunity = build_opportunity(
            cluster, candidate, "archive", CatalogMatch(CatalogDecision.NEW_VIDEO, 0, None, "new"), EXPIRES, NOW
        )
        self.assertFalse(opportunity.eligible)
        self.assertIn("hard safety or policy risk", opportunity.eligibility_failures)

    def test_expired_trend_is_skipped(self):
        cluster = cluster_signals([signal("manual"), signal("gdelt")], now=NOW)[0]
        candidate = ArchiveBridge.from_dict({**bridge(), "trend_cluster_id": cluster.cluster_id})
        opportunity = build_opportunity(
            cluster,
            candidate,
            "archive",
            CatalogMatch(CatalogDecision.NEW_VIDEO, 0, None, "new"),
            "2026-07-13T13:00:00Z",
            NOW,
        )
        self.assertIn("trend expires before production can complete", opportunity.eligibility_failures)


if __name__ == "__main__":
    unittest.main()
