import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from classes.YouTube import YouTube
from trend_catalog import CatalogMatch
from trend_entities import cluster_signals
from trend_models import ArchiveBridge, CatalogDecision, TrendRequest, TrendSignal, ValidationError
from trend_pipeline import approve_opportunity, load_trend_strategy
from trend_providers import GdeltProvider, ProviderSettings
from trend_scoring import TrendPolicy, build_opportunity
from trend_store import TrendStore


NOW = "2026-07-13T12:00:00Z"
EXPIRES = "2026-07-15T12:00:00Z"


def manifest():
    return {
        "brand_id": "archive",
        "publishing": {"review_before_upload": True},
        "production": {
            "trend_strategy": {
                "enabled": True,
                "mode": "suggest",
                "max_trend_assisted_share": 0.20,
                "recent_window_days": 30,
            }
        },
    }


def opportunity(catalog_match=None):
    signals = []
    for provider in ("manual", "gdelt"):
        signals.append(
            TrendSignal.from_dict(
                {
                    "provider": provider,
                    "provider_signal_id": provider,
                    "collected_at": NOW,
                    "expires_at": EXPIRES,
                    "term": "dance challenge",
                    "normalized_entity": "dance",
                    "aliases": ["dance", "dancing"],
                    "related_terms": ["public dancing"],
                    "entity_type": "concept",
                    "geography": "US",
                    "language": "en",
                    "window_hours": 24,
                    "velocity": 90,
                    "source_urls": [f"https://{provider}.test/current"],
                    "raw_metadata": {"unique_domains": 4},
                }
            )
        )
    cluster = cluster_signals(signals, now=NOW)[0]
    bridge = ArchiveBridge.from_dict(
        {
            "trend_cluster_id": cluster.cluster_id,
            "current_trigger_summary": "A safe fictional dance challenge fixture is circulating.",
            "historical_event": "The dancing plague of 1518",
            "relationship_type": "exact_entity",
            "relationship_explanation": "Both concern sustained public dancing, separated by five centuries.",
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
            "supporting_sources": ["https://news.test/current"],
            "current_news_sources": ["https://news.test/current"],
            "historical_sources": ["https://history.test/a", "https://archive.test/b"],
        }
    )
    return build_opportunity(
        cluster,
        bridge,
        "archive",
        catalog_match or CatalogMatch(CatalogDecision.NEW_VIDEO, 0, None, "new"),
        EXPIRES,
        NOW,
        TrendPolicy(minimum_opportunity_score=50),
    )


def evergreen_videos(count):
    return [
        {
            "brand_id": "archive",
            "status": "uploaded",
            "date": "2026-07-13 11:00:00",
            "production": {},
        }
        for _ in range(count)
    ]


class TrendPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TrendStore(os.path.join(self.tmp.name, "trends.sqlite3"))
        self.opportunity = opportunity()
        self.store.save_opportunity(self.opportunity)

    def tearDown(self):
        self.tmp.cleanup()

    def test_approval_creates_seed_but_never_uploads(self):
        with patch.object(YouTube, "upload_video") as upload:
            _, seed, mix = approve_opportunity(
                self.store,
                self.opportunity.opportunity_id,
                manifest(),
                operator="reviewer",
                reason="Verified safe and timely",
                now=NOW,
                videos=evergreen_videos(10),
            )
        upload.assert_not_called()
        self.assertEqual(seed.historical_event, "The dancing plague of 1518")
        self.assertFalse(mix.at_limit)
        self.assertEqual(self.store.get_topic_seed(seed.seed_id), seed)

    def test_seed_enters_normal_topic_and_research_gates(self):
        _, seed, _ = approve_opportunity(
            self.store,
            self.opportunity.opportunity_id,
            manifest(),
            operator="reviewer",
            reason="Verified safe and timely",
            now=NOW,
            videos=evergreen_videos(10),
        )
        youtube = YouTube.__new__(YouTube)
        youtube.topic_seed = seed
        youtube._research_rejected_topics = []
        youtube.research_brief = {}
        youtube.research_notes = ""
        youtube.research_brief_path = ""

        def research():
            youtube.research_brief = {
                "topic": "The dancing plague of 1518",
                "claims": [{"text": str(i), "source_ids": ["a"]} for i in range(4)],
                "cited_source_ids": ["a", "b"],
            }
            return "grounded"

        youtube.generate_research = research
        with patch("classes.YouTube.load_active_brand", return_value=manifest()), patch(
            "classes.YouTube.recent_topic_labels", return_value=[]
        ):
            youtube._generate_topic_and_research()
        self.assertEqual(youtube.subject, seed.historical_event)

    def test_duplicate_gate_still_rejects_seed(self):
        _, seed, _ = approve_opportunity(
            self.store,
            self.opportunity.opportunity_id,
            manifest(),
            operator="reviewer",
            reason="Verified safe and timely",
            now=NOW,
            videos=evergreen_videos(10),
        )
        youtube = YouTube.__new__(YouTube)
        youtube.topic_seed = seed
        with patch("classes.YouTube.load_active_brand", return_value=manifest()), patch(
            "classes.YouTube.recent_topic_labels", return_value=["The dancing plague of 1518"]
        ), patch("classes.YouTube.log_topic_rejection"):
            with self.assertRaisesRegex(ValidationError, "duplicates recent topic"):
                youtube.generate_topic()

    def test_content_mix_blocks_without_recorded_override(self):
        videos = evergreen_videos(4) + [
            {
                "brand_id": "archive",
                "status": "uploaded",
                "date": "2026-07-13 11:00:00",
                "production": {"trend_attribution": {"seed_id": "older"}},
            }
        ]
        with self.assertRaisesRegex(ValidationError, "configured maximum"):
            approve_opportunity(
                self.store,
                self.opportunity.opportunity_id,
                manifest(),
                operator="reviewer",
                reason="timely",
                now=NOW,
                videos=videos,
            )
        approval, _, mix = approve_opportunity(
            self.store,
            self.opportunity.opportunity_id,
            manifest(),
            operator="reviewer",
            reason="timely",
            override_reason="Editorial exception approved for this one slot",
            now=NOW,
            videos=videos,
        )
        self.assertTrue(mix.at_limit)
        self.assertTrue(approval.content_mix_override)

    def test_priority_mode_is_explicitly_unsupported(self):
        value = manifest()
        value["production"]["trend_strategy"]["mode"] = "priority"
        with self.assertRaisesRegex(ValidationError, "not implemented"):
            load_trend_strategy(value)

    def test_existing_story_cannot_create_a_new_seed(self):
        existing = opportunity(
            CatalogMatch(CatalogDecision.RESURFACE_EXISTING, 0.9, None, "already published")
        )
        self.store.save_opportunity(existing)
        with self.assertRaisesRegex(ValidationError, "ineligible|cannot create"):
            approve_opportunity(
                self.store,
                existing.opportunity_id,
                manifest(),
                operator="reviewer",
                reason="should not pass",
                now=NOW,
                videos=evergreen_videos(10),
            )

    def test_provider_outage_does_not_enter_evergreen_generation(self):
        failed = GdeltProvider(
            ProviderSettings(enabled=True),
            fetch_json=lambda *_: (_ for _ in ()).throw(ValueError("offline")),
        ).collect(
            TrendRequest.from_dict(
                {
                    "brand_id": "archive",
                    "terms": ["dance"],
                    "geographies": ["US"],
                    "languages": ["en"],
                    "window_hours": 24,
                    "max_results": 5,
                    "requested_at": NOW,
                }
            )
        )
        self.assertTrue(failed.errors)
        youtube = YouTube.__new__(YouTube)
        youtube.topic_seed = None
        youtube.subject = "An evergreen historical story"
        self.assertEqual(youtube.generate_topic(), "An evergreen historical story")


if __name__ == "__main__":
    unittest.main()
