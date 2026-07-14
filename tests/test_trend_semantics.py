import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from tests.test_trend_catalog import bridge as catalog_bridge
from tests.test_trend_pipeline import NOW, evergreen_videos, manifest, opportunity
from tests.test_trend_scoring import EXPIRES, bridge as scoring_bridge, signal
from trend_catalog import CatalogEntry, CatalogMatch, TrendCatalog
from trend_entities import cluster_signals
from trend_models import ArchiveBridge, CatalogDecision, ValidationError
from trend_pipeline import approve_opportunity, validate_topic_seed_script
from trend_scoring import TrendPolicy, build_opportunity
from trend_store import TrendStore


class CatalogAuthorityTests(unittest.TestCase):
    def _catalog(self, **metadata):
        return TrendCatalog([CatalogEntry(
            catalog_id="existing", brand_id="archive",
            title="How the 1905 Bison Herd Preserved the Species",
            subject="The 1905 bison preservation herd", status="uploaded",
            entities=["american bison"], metadata=metadata,
        )])

    def test_light_rewrite_cannot_be_alternate_angle(self):
        candidate = catalog_bridge("How a bison preservation herd saved the species in 1905", "alternate_angle")
        self.assertNotEqual(self._catalog().best_match(candidate, "american bison").decision, CatalogDecision.ALTERNATE_ANGLE)

    def test_same_event_and_payoff_with_new_title_is_not_alternate(self):
        candidate = catalog_bridge("The preservation of bison by a private herd in 1905", "alternate_angle")
        self.assertNotEqual(self._catalog(central_payoff="A private herd became preservation stock.").best_match(candidate, "american bison").decision, CatalogDecision.ALTERNATE_ANGLE)

    def test_same_event_with_two_documented_material_differences_is_alternate(self):
        candidate = catalog_bridge("The 1905 bison transfer to a federal reserve", "alternate_angle")
        candidate = ArchiveBridge.from_dict({
            **candidate.to_dict(),
            "central_payoff": "The transfer created a new federal breeding population.",
            "absurd_contradiction": "Animals once confined privately became the core of a federal herd.",
        })
        match = self._catalog(
            central_payoff="A private herd became preservation stock.",
            consequence="The private herd preserved breeding stock locally.",
        ).best_match(candidate, "american bison")
        self.assertEqual(match.decision, CatalogDecision.ALTERNATE_ANGLE)

    def test_uncertain_distinction_requires_review(self):
        candidate = catalog_bridge("The role of private bison collections in conservation policy", "alternate_angle")
        match = self._catalog().best_match(candidate, "american bison")
        self.assertEqual(match.decision, CatalogDecision.SKIP)
        self.assertIn("human review", match.reason.lower())


class ScoreSeparationTests(unittest.TestCase):
    def test_low_advisory_score_does_not_change_hard_eligibility(self):
        cluster = cluster_signals([signal("manual"), signal("gdelt")], now=NOW)[0]
        candidate = ArchiveBridge.from_dict({**scoring_bridge(), "trend_cluster_id": cluster.cluster_id})
        item = build_opportunity(
            cluster, candidate, "archive", CatalogMatch(CatalogDecision.NEW_VIDEO, 0, None, "new"),
            EXPIRES, NOW, TrendPolicy(minimum_opportunity_score=100),
        )
        self.assertTrue(item.eligible)
        self.assertEqual(item.recommended_action.value, "new_video")
        self.assertNotIn("advisory opportunity score below threshold", item.eligibility_failures)
        self.assertTrue(any("advisory" in reason for reason in item.reasoning))

    def test_catalog_similarity_overrides_llm_duplicate_score(self):
        cluster = cluster_signals([signal("manual"), signal("gdelt")], now=NOW)[0]
        candidate = ArchiveBridge.from_dict({**scoring_bridge(duplicate_similarity=0), "trend_cluster_id": cluster.cluster_id})
        item = build_opportunity(
            cluster, candidate, "archive", CatalogMatch(CatalogDecision.NEW_VIDEO, 0.81, None, "measured"),
            EXPIRES, NOW,
        )
        duplicate = next(component for component in item.components if component.name == "duplicate_risk")
        self.assertEqual(duplicate.score, 81)


class ScriptAnchorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TrendStore(os.path.join(self.tmp.name, "trends.sqlite3"))
        item = opportunity()
        self.store.save_opportunity(item)
        with patch("config.get_review_before_upload", return_value=True):
            self.seed = approve_opportunity(
                self.store, item.opportunity_id, manifest(), operator="reviewer", reason="verified",
                now=NOW, videos=evergreen_videos(10),
            )[1]

    def tearDown(self):
        self.tmp.cleanup()

    def test_unrelated_1518_cooking_story_fails(self):
        script = ("In 1518 a palace kitchen prepared an enormous royal feast. "
                  "Cooks measured flour, tended ovens, served nobles, and recorded recipes. " * 4)
        with self.assertRaises(ValidationError):
            validate_topic_seed_script(self.seed, script)

    def test_valid_multi_anchor_script_passes(self):
        script = ("In Strasbourg in 1518, the dancing plague drove people to dance for days. "
                  "Officials responded to involuntary dancing by ordering still more dancing, "
                  "a documented contradiction in accounts of the historical outbreak. "
                  "The episode involved exhausted dancers, civic authorities, and a disastrous attempted cure. " * 2)
        validate_topic_seed_script(self.seed, script)

    def test_short_date_only_script_fails(self):
        with self.assertRaises(ValidationError):
            validate_topic_seed_script(self.seed, "A completely unrelated event happened in 1518.")


if __name__ == "__main__":
    unittest.main()
