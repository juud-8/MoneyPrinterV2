import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trend_bridges import parse_bridge_candidates, verify_historical_sources, with_detected_risks
from trend_entities import cluster_signals
from trend_models import TrendSignal, ValidationError


class BridgeTests(unittest.TestCase):
    def setUp(self):
        signal = TrendSignal.from_dict(
            {
                "provider": "manual",
                "provider_signal_id": "dance",
                "collected_at": "2026-07-13T12:00:00Z",
                "term": "dance",
                "normalized_entity": "dance",
                "entity_type": "concept",
                "geography": "US",
                "language": "en",
                "window_hours": 24,
                "source_urls": ["https://current.test/dance"],
            }
        )
        self.cluster = cluster_signals([signal], now="2026-07-13T12:00:00Z")[0]

    def payload(self):
        return {
            "historical_event": "The dancing plague of 1518",
            "relationship_type": "exact_entity",
            "relationship_explanation": "Both concern sustained public dancing, separated by five centuries.",
            "specific_number": "1518",
            "absurd_contradiction": "Officials encouraged more dancing.",
            "first_spoken_sentence": "In 1518, officials prescribed dancing to people who could not stop.",
            "first_frame_text": "THE CURE WAS MORE DANCING",
            "working_titles": [],
            "central_payoff": "The attempted cure repeated the apparent symptom.",
            "target_seconds": 55,
            "archive_fit_score": 95,
            "sourceability_score": 90,
            "visual_potential_score": 80,
            "competition_score": None,
            "duplicate_similarity": None,
            "risk_flags": [],
            "unknowns": ["exact contemporary diagnosis is disputed"],
        }

    def test_malformed_llm_output_fails(self):
        with self.assertRaises(ValidationError):
            parse_bridge_candidates("not json", self.cluster)

    def test_bridge_sources_are_separated(self):
        bridge = parse_bridge_candidates(json.dumps([self.payload()]), self.cluster)[0]
        verified = verify_historical_sources(
            bridge,
            lambda topic: [
                {"url": "https://history.test/a"},
                {"url": "https://archive.test/b"},
            ],
        )
        self.assertEqual(verified.current_news_sources, ["https://current.test/dance"])
        self.assertEqual(len(verified.historical_sources), 2)

    def test_active_disaster_metadata_adds_hard_risk(self):
        signal_payload = self.cluster.signals[0].to_dict()
        signal_payload["raw_metadata"] = {"active_tragedy": True}
        cluster = cluster_signals([TrendSignal.from_dict(signal_payload)], now="2026-07-13T12:00:00Z")[0]
        bridge = parse_bridge_candidates(json.dumps([self.payload()]), cluster)[0]
        self.assertIn("active_tragedy", with_detected_risks(cluster, bridge).risk_flags)


if __name__ == "__main__":
    unittest.main()
