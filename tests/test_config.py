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


if __name__ == "__main__":
    unittest.main()
