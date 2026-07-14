import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trend_catalog import CatalogEntry, TrendCatalog
from trend_models import ArchiveBridge


def bridge(event, relationship="exact_entity"):
    return ArchiveBridge.from_dict(
        {
            "trend_cluster_id": "cluster-1",
            "current_trigger_summary": "Safe fictional bison fixture",
            "historical_event": event,
            "relationship_type": relationship,
            "relationship_explanation": "The trend and story concern the same historical species.",
            "specific_number": "1905",
            "absurd_contradiction": "A private herd helped rescue a national symbol.",
            "first_spoken_sentence": "In 1905, a private bison herd helped save a national symbol.",
            "first_frame_text": "THE HERD THAT SAVED BISON",
            "working_titles": [],
            "central_payoff": "A private herd became preservation stock.",
            "target_seconds": 55,
            "archive_fit_score": 90,
            "sourceability_score": 90,
            "visual_potential_score": 80,
            "competition_score": 30,
            "duplicate_similarity": 0,
            "risk_flags": [],
            "supporting_sources": [],
            "historical_sources": ["https://history.test/a", "https://archive.test/b"],
        }
    )


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = TrendCatalog(
            [
                CatalogEntry(
                    catalog_id="video:bison1905",
                    brand_id="archive",
                    title="How a 1905 Bison Herd Helped Preserve the Species",
                    subject="The 1905 bison preservation herd",
                    status="uploaded",
                    youtube_video_id="bison1905",
                    entities=["american bison"],
                )
            ]
        )

    def test_same_bison_story_resurfaces_existing(self):
        match = self.catalog.best_match(bridge("The 1905 bison preservation herd"), "american bison")
        self.assertEqual(match.decision.value, "resurface_existing")

    def test_materially_different_bison_story_is_alternate_angle(self):
        match = self.catalog.best_match(
            bridge("The 1886 Smithsonian expedition that collected bison specimens", "alternate_angle"),
            "american bison",
        )
        self.assertEqual(match.decision.value, "alternate_angle")

    def test_new_entity_is_new_video(self):
        match = self.catalog.best_match(bridge("The dancing plague of 1518"), "dance")
        self.assertEqual(match.decision.value, "new_video")


if __name__ == "__main__":
    unittest.main()
