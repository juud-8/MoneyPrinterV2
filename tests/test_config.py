import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import config


class PostBridgeConfigTests(unittest.TestCase):
    def write_config(self, directory: str, payload: dict) -> None:
        with open(os.path.join(directory, "config.json"), "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_missing_platforms_uses_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.write_config(temp_dir, {"post_bridge": {"enabled": True}})

            with patch.object(config, "ROOT_DIR", temp_dir):
                post_bridge_config = config.get_post_bridge_config()

        self.assertEqual(post_bridge_config["platforms"], ["tiktok", "instagram"])

    def test_invalid_or_empty_platforms_do_not_expand_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.write_config(
                temp_dir,
                {
                    "post_bridge": {
                        "enabled": True,
                        "platforms": ["youtube", "tik-tok"],
                    }
                },
            )

            with patch.object(config, "ROOT_DIR", temp_dir):
                post_bridge_config = config.get_post_bridge_config()

        self.assertEqual(post_bridge_config["platforms"], [])

    def test_non_list_platforms_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.write_config(
                temp_dir,
                {
                    "post_bridge": {
                        "enabled": True,
                        "platforms": "tiktok",
                    }
                },
            )

            with patch.object(config, "ROOT_DIR", temp_dir):
                post_bridge_config = config.get_post_bridge_config()

        self.assertEqual(post_bridge_config["platforms"], [])

    def test_non_object_post_bridge_config_falls_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.write_config(
                temp_dir,
                {
                    "post_bridge": None,
                },
            )

            with patch.object(config, "ROOT_DIR", temp_dir):
                post_bridge_config = config.get_post_bridge_config()

        self.assertEqual(post_bridge_config["platforms"], ["tiktok", "instagram"])
        self.assertEqual(post_bridge_config["account_ids"], [])
        self.assertFalse(post_bridge_config["enabled"])


class AiDisclosureDefaultTests(unittest.TestCase):
    def write_config(self, directory: str, payload: dict) -> None:
        with open(os.path.join(directory, "config.json"), "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_defaults_to_true_when_unset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.write_config(temp_dir, {})
            with patch.object(config, "ROOT_DIR", temp_dir):
                self.assertTrue(config.get_ai_disclosure_default())

    def test_respects_explicit_false(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.write_config(temp_dir, {"ai_disclosure_default": False})
            with patch.object(config, "ROOT_DIR", temp_dir):
                self.assertFalse(config.get_ai_disclosure_default())


class ImageAndTtsProviderConfigTests(unittest.TestCase):
    def write_config(self, directory: str, payload: dict) -> None:
        with open(os.path.join(directory, "config.json"), "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_standard_image_provider_defaults_to_gemini(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.write_config(temp_dir, {})
            with patch.object(config, "ROOT_DIR", temp_dir):
                self.assertEqual(config.get_standard_image_provider(), "gemini")

    def test_standard_image_provider_normalizes_case(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.write_config(temp_dir, {"standard_image_provider": "FAL"})
            with patch.object(config, "ROOT_DIR", temp_dir):
                self.assertEqual(config.get_standard_image_provider(), "fal")

    def test_standard_image_provider_env_override_wins(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.write_config(temp_dir, {"standard_image_provider": "gemini"})
            with patch.object(config, "ROOT_DIR", temp_dir), patch.dict(
                os.environ, {"MPV2_IMAGE_PROVIDER_OVERRIDE": "fal"}
            ):
                self.assertEqual(config.get_standard_image_provider(), "fal")

    def test_standard_image_provider_invalid_env_override_falls_through(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.write_config(temp_dir, {"standard_image_provider": "fal"})
            with patch.object(config, "ROOT_DIR", temp_dir), patch.dict(
                os.environ, {"MPV2_IMAGE_PROVIDER_OVERRIDE": "bogus"}
            ):
                self.assertEqual(config.get_standard_image_provider(), "fal")

    def test_trend_provider_defaults_to_google_trends(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.write_config(temp_dir, {})
            with patch.object(config, "ROOT_DIR", temp_dir):
                self.assertEqual(config.get_trend_provider(), "google_trends")

    def test_fal_image_model_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.write_config(temp_dir, {})
            with patch.object(config, "ROOT_DIR", temp_dir):
                self.assertEqual(config.get_fal_image_model(), "fal-ai/flux/schnell")

    def test_fishaudio_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.write_config(temp_dir, {})
            with patch.object(config, "ROOT_DIR", temp_dir), patch.dict(
                os.environ, {}, clear=False
            ):
                os.environ.pop("FISH_AUDIO_API_KEY", None)
                self.assertEqual(config.get_fishaudio_api_key(), "")
                self.assertEqual(config.get_fishaudio_model(), "s2-pro")

    def test_fishaudio_api_key_env_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.write_config(temp_dir, {"fishaudio_api_key": ""})
            with patch.object(config, "ROOT_DIR", temp_dir), patch.dict(
                os.environ, {"FISH_AUDIO_API_KEY": "env-key"}
            ):
                self.assertEqual(config.get_fishaudio_api_key(), "env-key")


class CaptionBackendAndApiUploadConfigTests(unittest.TestCase):
    def write_config(self, directory: str, payload: dict) -> None:
        with open(os.path.join(directory, "config.json"), "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_caption_backend_defaults_to_moviepy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.write_config(temp_dir, {})
            with patch.object(config, "ROOT_DIR", temp_dir), patch(
                "brand_switcher.get_production_setting", return_value=None
            ):
                self.assertEqual(config.get_caption_backend(), "moviepy")

    def test_caption_backend_reads_config_and_normalizes_case(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.write_config(temp_dir, {"caption_backend": "ASS_Karaoke"})
            with patch.object(config, "ROOT_DIR", temp_dir), patch(
                "brand_switcher.get_production_setting", return_value=None
            ):
                self.assertEqual(config.get_caption_backend(), "ass_karaoke")

    def test_caption_backend_brand_override_wins(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.write_config(temp_dir, {"caption_backend": "moviepy"})
            with patch.object(config, "ROOT_DIR", temp_dir), patch(
                "brand_switcher.get_production_setting", return_value="ass_karaoke"
            ):
                self.assertEqual(config.get_caption_backend(), "ass_karaoke")

    def test_youtube_api_client_secrets_path_empty_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.write_config(temp_dir, {})
            with patch.object(config, "ROOT_DIR", temp_dir):
                self.assertEqual(config.get_youtube_api_client_secrets_path(), "")

    def test_youtube_api_client_secrets_path_resolved_against_root_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.write_config(
                temp_dir, {"youtube_api_client_secrets_path": "secrets/oauth.json"}
            )
            with patch.object(config, "ROOT_DIR", temp_dir):
                self.assertEqual(
                    config.get_youtube_api_client_secrets_path(),
                    os.path.join(temp_dir, "secrets/oauth.json"),
                )

    def test_youtube_api_token_path_default_resolved_against_root_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.write_config(temp_dir, {})
            with patch.object(config, "ROOT_DIR", temp_dir):
                self.assertEqual(
                    config.get_youtube_api_token_path(),
                    os.path.join(temp_dir, ".mp/youtube_api_token.json"),
                )

    def test_youtube_api_category_id_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.write_config(temp_dir, {})
            with patch.object(config, "ROOT_DIR", temp_dir):
                self.assertEqual(config.get_youtube_api_category_id(), "22")


if __name__ == "__main__":
    unittest.main()
