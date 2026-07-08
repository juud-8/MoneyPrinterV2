import os
import sys
import unittest
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import asset_gen
from asset_gen import AssetResult


def _video_result(**overrides) -> AssetResult:
    base = dict(path="/tmp/clip.mp4", modality="video_clip", tier="premium_video", provider="fal:test", cost_usd=1.0)
    base.update(overrides)
    return AssetResult(**base)


def _image_result(**overrides) -> AssetResult:
    base = dict(path="/tmp/img.png", modality="image", tier="standard", provider="gemini:test")
    base.update(overrides)
    return AssetResult(**base)


class EstimateFalVideoCostTests(unittest.TestCase):
    def test_known_model_uses_its_rate(self) -> None:
        self.assertEqual(asset_gen.estimate_fal_video_cost("fal-ai/veo3.1", 5), 1.0)
        self.assertEqual(asset_gen.estimate_fal_video_cost("fal-ai/veo3.1/fast", 5), 0.5)

    def test_unknown_model_uses_default_rate(self) -> None:
        self.assertEqual(
            asset_gen.estimate_fal_video_cost("some/unknown-model", 2),
            round(asset_gen.DEFAULT_FAL_VIDEO_PRICE_PER_SECOND_USD * 2, 2),
        )


class StandardImageProviderTests(unittest.TestCase):
    def test_fal_provider_routes_standard_to_fal(self) -> None:
        with patch.object(asset_gen, "get_standard_image_provider", return_value="fal"), patch.object(
            asset_gen, "get_fal_image_model", return_value="fal-ai/flux/schnell"
        ), patch.object(
            asset_gen, "get_nanobanana2_aspect_ratio", return_value="9:16"
        ), patch.object(
            asset_gen, "_generate_via_fal_image", return_value=b"png-bytes"
        ) as mock_fal, patch.object(
            asset_gen, "_generate_via_gemini"
        ) as mock_gemini, patch.object(
            asset_gen, "_persist_bytes", return_value="/tmp/img.png"
        ), patch.object(
            asset_gen, "get_verbose", return_value=False
        ):
            result = asset_gen.generate_image("a prompt")

        mock_fal.assert_called_once_with("a prompt", "fal-ai/flux/schnell", "9:16")
        mock_gemini.assert_not_called()
        self.assertEqual(result.tier, "standard")
        self.assertEqual(result.provider, "fal:fal-ai/flux/schnell")
        self.assertEqual(result.cost_usd, asset_gen.FAL_IMAGE_PRICE_PER_IMAGE_USD["fal-ai/flux/schnell"])

    def test_fal_failure_falls_back_to_gemini(self) -> None:
        with patch.object(asset_gen, "get_standard_image_provider", return_value="fal"), patch.object(
            asset_gen, "get_fal_image_model", return_value="fal-ai/flux/schnell"
        ), patch.object(
            asset_gen, "get_nanobanana2_aspect_ratio", return_value="9:16"
        ), patch.object(
            asset_gen, "get_nanobanana2_model", return_value="gemini-test"
        ), patch.object(
            asset_gen, "_generate_via_fal_image", side_effect=RuntimeError("boom")
        ), patch.object(
            asset_gen, "_generate_via_gemini", return_value=b"png-bytes"
        ) as mock_gemini, patch.object(
            asset_gen, "_persist_bytes", return_value="/tmp/img.png"
        ), patch.object(
            asset_gen, "get_verbose", return_value=False
        ):
            result = asset_gen.generate_image("a prompt")

        mock_gemini.assert_called_once()
        self.assertEqual(result.provider, "gemini:gemini-test")

    def test_premium_image_never_uses_fal(self) -> None:
        with patch.object(asset_gen, "get_standard_image_provider", return_value="fal"), patch.object(
            asset_gen, "get_nanobanana2_aspect_ratio", return_value="9:16"
        ), patch.object(
            asset_gen, "get_premium_image_model", return_value="gemini-premium"
        ), patch.object(
            asset_gen, "_generate_via_fal_image"
        ) as mock_fal, patch.object(
            asset_gen, "_generate_via_gemini", return_value=b"png-bytes"
        ), patch.object(
            asset_gen, "_persist_bytes", return_value="/tmp/img.png"
        ), patch.object(
            asset_gen, "get_verbose", return_value=False
        ):
            result = asset_gen.generate_image("a prompt", use_premium=True)

        mock_fal.assert_not_called()
        self.assertEqual(result.tier, "premium_image")
        self.assertEqual(result.provider, "gemini:gemini-premium")

    def test_gemini_provider_skips_fal(self) -> None:
        with patch.object(asset_gen, "get_standard_image_provider", return_value="gemini"), patch.object(
            asset_gen, "get_nanobanana2_aspect_ratio", return_value="9:16"
        ), patch.object(
            asset_gen, "get_nanobanana2_model", return_value="gemini-test"
        ), patch.object(
            asset_gen, "_generate_via_fal_image"
        ) as mock_fal, patch.object(
            asset_gen, "_generate_via_gemini", return_value=b"png-bytes"
        ), patch.object(
            asset_gen, "_persist_bytes", return_value="/tmp/img.png"
        ), patch.object(
            asset_gen, "get_verbose", return_value=False
        ):
            result = asset_gen.generate_image("a prompt")

        mock_fal.assert_not_called()
        self.assertEqual(result.provider, "gemini:gemini-test")


class GenerateAssetWithFallbackTests(unittest.TestCase):
    def test_premium_video_success_returns_video_result(self) -> None:
        with patch.object(asset_gen, "generate_video_clip", return_value=_video_result()):
            result = asset_gen.generate_asset_with_fallback("a hook prompt", "premium_video")
        self.assertEqual(result.tier, "premium_video")
        self.assertEqual(result.modality, "video_clip")

    def test_premium_video_failure_falls_back_to_premium_image(self) -> None:
        with patch.object(asset_gen, "generate_video_clip", return_value=None), patch.object(
            asset_gen, "generate_image", return_value=_image_result(tier="premium_image")
        ) as mock_image:
            result = asset_gen.generate_asset_with_fallback("a hook prompt", "premium_video")

        self.assertEqual(result.tier, "premium_image")
        mock_image.assert_called_once()
        self.assertTrue(mock_image.call_args.kwargs.get("use_premium"))

    def test_premium_image_failure_falls_back_to_standard(self) -> None:
        with patch.object(
            asset_gen, "generate_image", side_effect=[None, _image_result(tier="standard")]
        ) as mock_image:
            result = asset_gen.generate_asset_with_fallback("a prompt", "premium_image")

        self.assertEqual(result.tier, "standard")
        self.assertEqual(mock_image.call_count, 2)
        # First call requests premium, second call (the fallback) does not.
        self.assertTrue(mock_image.call_args_list[0].kwargs.get("use_premium"))
        self.assertFalse(mock_image.call_args_list[1].kwargs.get("use_premium"))

    def test_everything_failing_raises_runtime_error(self) -> None:
        with patch.object(asset_gen, "generate_video_clip", return_value=None), patch.object(
            asset_gen, "generate_image", return_value=None
        ):
            with self.assertRaises(RuntimeError):
                asset_gen.generate_asset_with_fallback("a prompt", "premium_video")

    def test_standard_tier_never_calls_video_or_premium(self) -> None:
        with patch.object(asset_gen, "generate_video_clip") as mock_video, patch.object(
            asset_gen, "generate_image", return_value=_image_result()
        ) as mock_image:
            result = asset_gen.generate_asset_with_fallback("a prompt", "standard")

        mock_video.assert_not_called()
        mock_image.assert_called_once_with("a prompt", aspect_ratio=None, use_premium=False)
        self.assertEqual(result.tier, "standard")


if __name__ == "__main__":
    unittest.main()
