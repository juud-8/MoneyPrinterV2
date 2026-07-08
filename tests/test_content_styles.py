import os
import sys
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from content_styles import (
    CONTENT_STYLES,
    DEFAULT_STYLE_NAME,
    get_content_style,
    resolve_style_name,
)


class ResolveStyleNameTests(unittest.TestCase):
    def test_content_type_horror_maps_to_micro_horror(self) -> None:
        brand = {"content_type": "horror"}
        self.assertEqual(resolve_style_name(brand), "micro_horror")

    def test_content_type_history_maps_to_narrative_nonfiction(self) -> None:
        brand = {"content_type": "history"}
        self.assertEqual(resolve_style_name(brand), "narrative_nonfiction")

    def test_unknown_content_type_falls_back_to_default(self) -> None:
        brand = {"content_type": "education"}
        self.assertEqual(resolve_style_name(brand), DEFAULT_STYLE_NAME)

    def test_missing_content_type_falls_back_to_default(self) -> None:
        self.assertEqual(resolve_style_name({}), DEFAULT_STYLE_NAME)

    def test_explicit_override_wins_over_content_type(self) -> None:
        brand = {
            "content_type": "education",
            "production": {"content_style": "micro_horror"},
        }
        self.assertEqual(resolve_style_name(brand), "micro_horror")

    def test_invalid_explicit_override_falls_back_to_content_type_mapping(self) -> None:
        brand = {
            "content_type": "horror",
            "production": {"content_style": "not_a_real_style"},
        }
        self.assertEqual(resolve_style_name(brand), "micro_horror")

    def test_engine_never_branches_on_brand_id(self) -> None:
        """A brand_id alone (no content_type/override) must NOT select a
        non-default style — style selection must be data-driven, not
        brand-name-driven."""
        brand = {"brand_id": "sixty_second_thrillers"}
        self.assertEqual(resolve_style_name(brand), DEFAULT_STYLE_NAME)


class GetContentStyleTests(unittest.TestCase):
    def test_returns_full_style_dict_for_each_known_style(self) -> None:
        for name in CONTENT_STYLES:
            style = get_content_style({"production": {"content_style": name}})
            self.assertEqual(style, CONTENT_STYLES[name])

    def test_micro_horror_enforces_min_word_count_and_audio_duration(self) -> None:
        style = get_content_style({"content_type": "horror"})
        self.assertTrue(style["enforce_min_word_count"])
        self.assertTrue(style["enforce_min_audio_duration"])
        self.assertIsNotNone(style["short_script_rules"])
        self.assertIsNotNone(style["music_keywords"])

    def test_practical_demo_does_not_enforce_minimums(self) -> None:
        style = get_content_style({"content_type": "education"})
        self.assertFalse(style["enforce_min_word_count"])
        self.assertFalse(style["enforce_min_audio_duration"])
        self.assertIsNone(style["short_script_rules"])
        self.assertIsNone(style["music_keywords"])

    def test_narrative_nonfiction_enforces_minimums_and_requires_real_facts(self) -> None:
        style = get_content_style({"content_type": "history"})
        self.assertTrue(style["enforce_min_word_count"])
        self.assertTrue(style["enforce_min_audio_duration"])
        self.assertIsNotNone(style["short_script_rules"])
        self.assertIsNotNone(style["music_keywords"])
        # The compliance-critical rule: topic prompts must demand verifiable facts,
        # modeled directly on the "True Crime Case Files" termination case
        # (fabricated stories presented as real).
        prompt = style["topic_prompt"]("weird history", "")
        self.assertIn("real, independently verifiable", prompt)

    def test_content_type_history_does_not_auto_select_weird_history(self) -> None:
        """weird_history is opt-in only, via an explicit manifest override —
        it must never become the default for content_type: history, so any
        future non-Strange-Archive history brand keeps the generic
        narrative_nonfiction behavior unless it explicitly opts in."""
        brand = {"content_type": "history"}
        self.assertEqual(resolve_style_name(brand), "narrative_nonfiction")

    def test_weird_history_selected_via_explicit_override(self) -> None:
        brand = {
            "content_type": "history",
            "production": {"content_style": "weird_history"},
        }
        self.assertEqual(resolve_style_name(brand), "weird_history")

    def test_weird_history_requires_verifiable_facts_and_avoids_risky_content(self) -> None:
        style = get_content_style(
            {"production": {"content_style": "weird_history"}}
        )
        prompt = style["topic_prompt"]("weird but true history", "")
        self.assertIn("real, independently verifiable", prompt)
        for avoided in (
            "true crime",
            "living person",
            "conspiracy",
            "Fictional stories",
            "top 10",
        ):
            self.assertIn(avoided, prompt)

    def test_weird_history_targets_70_to_85_seconds_with_narration_ceiling(self) -> None:
        style = get_content_style(
            {"production": {"content_style": "weird_history"}}
        )
        self.assertTrue(70.0 <= style["default_target_seconds"] <= 85.0)
        self.assertTrue(style["subtract_outro_from_target"])
        self.assertTrue(style["enforce_max_word_count"])
        # Narration ceiling leaves headroom for a ~2.8s appended outro (~95s total).
        self.assertEqual(style["max_target_ceiling_seconds"], 92.0)
        self.assertTrue(style["enforce_min_word_count"])

    def test_weird_history_enables_topic_and_title_candidate_scoring(self) -> None:
        style = get_content_style(
            {"production": {"content_style": "weird_history"}}
        )
        self.assertGreater(style["topic_candidate_count"], 1)
        self.assertGreater(style["title_candidate_count"], 1)

    def test_other_styles_keep_candidate_scoring_disabled_by_default(self) -> None:
        for name in ("micro_horror", "practical_demo", "narrative_nonfiction"):
            style = CONTENT_STYLES[name]
            self.assertEqual(style["topic_candidate_count"], 1)
            self.assertEqual(style["title_candidate_count"], 1)
            self.assertFalse(style["enforce_max_word_count"])
            self.assertIsNone(style["max_target_ceiling_seconds"])


if __name__ == "__main__":
    unittest.main()
