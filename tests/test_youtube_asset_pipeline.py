"""Tests for the parallelized per-shot asset generation pipeline."""

import inspect
import os
import sys
import time
import unittest
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import classes.YouTube as youtube_module  # noqa: E402
from asset_gen import AssetResult  # noqa: E402
from classes.YouTube import YouTube  # noqa: E402


class GenerateShotAssetFallbackTests(unittest.TestCase):
    def test_returns_fallback_path_when_both_tiers_fail(self):
        yt = YouTube.__new__(YouTube)
        yt.subject = "Test Subject"
        with patch("classes.YouTube.generate_asset_with_fallback", side_effect=RuntimeError("boom")), \
            patch("classes.YouTube.get_production_setting", return_value=""), \
            patch("classes.YouTube.warning"):
            result = yt._generate_shot_asset(
                "a prompt", "standard", per_shot_seconds=3.0, fallback_path="prior.png"
            )
        self.assertEqual(result.path, "prior.png")
        self.assertEqual(result.provider, "reuse")

    def test_raises_when_both_tiers_fail_and_no_fallback_supplied(self):
        yt = YouTube.__new__(YouTube)
        yt.subject = "Test Subject"
        with patch("classes.YouTube.generate_asset_with_fallback", side_effect=RuntimeError("boom")), \
            patch("classes.YouTube.get_production_setting", return_value=""), \
            patch("classes.YouTube.warning"):
            with self.assertRaises(RuntimeError):
                yt._generate_shot_asset(
                    "a prompt", "standard", per_shot_seconds=3.0, fallback_path=None
                )


class GenerateShotAssetsParallelTests(unittest.TestCase):
    def _make_youtube(self):
        yt = YouTube.__new__(YouTube)
        yt.subject = "Test Subject"
        return yt

    def test_preserves_prompt_order_even_when_completions_resolve_out_of_sequence(self):
        yt = self._make_youtube()
        prompts = [f"prompt-{i}" for i in range(5)]

        def fake_generate(prompt, tier, *, per_shot_seconds, fallback_path=None):
            # Reverse-order sleeping: earlier prompts finish LAST, so results
            # complete out of submission order — the final list must still
            # match prompts' original order, not completion order.
            index = int(prompt.split("-")[1])
            time.sleep(0.02 * (len(prompts) - index))
            return AssetResult(path=f"{prompt}.png", modality="image", tier="standard")

        with patch.object(yt, "_generate_shot_asset", side_effect=fake_generate):
            results = yt._generate_shot_assets_parallel(prompts, per_shot_seconds=3.0)

        self.assertEqual([r.path for r in results], [f"{p}.png" for p in prompts])

    def test_failed_shot_is_backfilled_from_nearest_successful_neighbor(self):
        yt = self._make_youtube()
        prompts = ["prompt-0", "prompt-1", "prompt-2"]

        def fake_generate(prompt, tier, *, per_shot_seconds, fallback_path=None):
            if prompt == "prompt-1":
                raise RuntimeError("both tiers failed")
            return AssetResult(path=f"{prompt}.png", modality="image", tier="standard")

        with patch.object(yt, "_generate_shot_asset", side_effect=fake_generate), \
            patch("classes.YouTube.warning"):
            results = yt._generate_shot_assets_parallel(prompts, per_shot_seconds=3.0)

        self.assertEqual(results[0].path, "prompt-0.png")
        self.assertEqual(results[2].path, "prompt-2.png")
        self.assertIn(results[1].path, ("prompt-0.png", "prompt-2.png"))
        self.assertEqual(results[1].provider, "reuse")

    def test_raises_when_every_shot_fails(self):
        yt = self._make_youtube()
        prompts = ["prompt-0", "prompt-1"]

        def fake_generate(prompt, tier, *, per_shot_seconds, fallback_path=None):
            raise RuntimeError("both tiers failed")

        with patch.object(yt, "_generate_shot_asset", side_effect=fake_generate), \
            patch("classes.YouTube.warning"):
            with self.assertRaises(RuntimeError):
                yt._generate_shot_assets_parallel(prompts, per_shot_seconds=3.0)


class ArchiveSongFallbackRegressionTests(unittest.TestCase):
    """The checkpointed Archive Song loop is sequential by design (it saves
    resume state after every shot) and was deliberately left untouched by the
    parallel pipeline. Guards that it still passes its own self.images[-1]
    fallback explicitly, since _generate_shot_asset no longer reads that
    implicitly — an accidental revert here would silently break resume
    safety for that call site."""

    def test_archive_song_call_site_still_passes_explicit_fallback(self):
        source = inspect.getsource(youtube_module)
        self.assertIn("fallback_path=self.images[-1] if self.images else None", source)


if __name__ == "__main__":
    unittest.main()
