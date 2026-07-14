import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trend_models import (
    ApprovalRecord,
    TopicSeed,
    TrendSignal,
    ValidationError,
)


NOW = "2026-07-13T12:00:00Z"
LATER = "2026-07-15T12:00:00Z"


def approval() -> dict:
    return {
        "opportunity_id": "opp-1",
        "brand_id": "archive",
        "status": "approved",
        "decided_at": NOW,
        "operator": "tester",
        "reason": "Verified sources and fit",
    }


class TrendModelTests(unittest.TestCase):
    def test_mvp_manual_fixture_is_valid(self):
        fixture = os.path.join(ROOT, "tests", "fixtures", "trends", "mvp_cases.json")
        with open(fixture, encoding="utf-8") as file:
            payload = json.load(file)
        signals = [TrendSignal.from_dict(item) for item in payload["signals"]]
        self.assertEqual(len(signals), 4)
        self.assertEqual(signals[0].normalized_entity, "american bison")

    def test_relative_google_interest_cannot_be_absolute(self):
        with self.assertRaisesRegex(ValidationError, "relative"):
            TrendSignal.from_dict(
                {
                    "provider": "google_trends",
                    "provider_signal_id": "g-1",
                    "collected_at": NOW,
                    "term": "bison",
                    "normalized_entity": "american bison",
                    "volume": 73,
                    "volume_is_absolute": True,
                }
            )

    def test_missing_score_is_preserved_as_unknown(self):
        signal = TrendSignal.from_dict(
            {
                "provider": "manual",
                "provider_signal_id": "m-1",
                "collected_at": NOW,
                "term": "bison",
                "normalized_entity": "american bison",
                "volume": None,
                "velocity": None,
            }
        )
        self.assertIsNone(signal.volume)
        self.assertIsNone(signal.velocity)

    def test_topic_seed_requires_approval(self):
        bad = approval()
        bad["status"] = "rejected"
        with self.assertRaisesRegex(ValidationError, "approved"):
            self._seed(bad)

    def test_topic_seed_rejects_resurface_action(self):
        with self.assertRaisesRegex(ValidationError, "new-video or alternate-angle"):
            self._seed(approval(), catalog_decision="resurface_existing")

    def test_content_mix_override_requires_reason(self):
        payload = approval()
        payload["content_mix_override"] = True
        with self.assertRaisesRegex(ValidationError, "override"):
            ApprovalRecord.from_dict(payload)

    def test_valid_topic_seed_round_trip(self):
        seed = self._seed(approval())
        restored = TopicSeed.from_dict(seed.to_dict())
        self.assertEqual(restored.seed_id, seed.seed_id)
        self.assertEqual(restored.primary_entity, "dance")

    @staticmethod
    def _seed(approval_payload: dict, catalog_decision: str = "new_video") -> TopicSeed:
        return TopicSeed.from_dict(
            {
                "brand_id": "archive",
                "primary_entity": "dance",
                "primary_keyword": "dance",
                "keyword_aliases": ["dancing"],
                "related_search_terms": ["dance challenge"],
                "current_trigger_summary": "A safe fictional dance challenge fixture.",
                "current_news_source_references": ["https://example.test/current"],
                "trend_geographies": ["US"],
                "detected_at": NOW,
                "expires_at": LATER,
                "historical_event": "The dancing plague of 1518",
                "historical_source_references": ["https://example.test/history"],
                "relationship_type": "exact_entity",
                "relationship_explanation": "Both concern sustained public dancing, separated by five centuries.",
                "specific_number_date": "1518",
                "absurd_contradiction": "Authorities answered involuntary dancing by encouraging more dancing.",
                "suggested_first_spoken_sentence": "In 1518, officials prescribed more dancing to people who could not stop.",
                "suggested_first_frame_text": "THE CURE WAS MORE DANCING",
                "description_context_sentence": "A documented episode from Strasbourg in 1518.",
                "catalog_decision": catalog_decision,
                "existing_video_match": None,
                "component_scores": [],
                "confidence": 0.8,
                "unknowns": [],
                "approval_record": approval_payload,
                "attribution_metadata": {"trend_cluster_id": "cluster-1"},
                "created_at": NOW,
            }
        )


if __name__ == "__main__":
    unittest.main()
