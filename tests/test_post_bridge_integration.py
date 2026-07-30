import os
import sys
import tempfile
import unittest
from unittest.mock import Mock
from unittest.mock import patch


ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import post_bridge_integration
from post_bridge_integration import build_platform_configurations
from post_bridge_integration import maybe_crosspost_youtube_short
from post_bridge_integration import resolve_social_account_ids


class BuildPlatformConfigurationsTests(unittest.TestCase):
    def test_instagram_always_gets_a_cover_past_the_opening_fade(self) -> None:
        """Reels default their cover to frame 0, which is mid-fade here."""
        config = build_platform_configurations("A title")
        self.assertEqual(
            config["instagram"]["video_cover_timestamp_ms"],
            post_bridge_integration.INSTAGRAM_COVER_TIMESTAMP_MS,
        )
        self.assertGreater(config["instagram"]["video_cover_timestamp_ms"], 0)

    def test_no_placement_key_is_sent_for_instagram(self) -> None:
        """Post Bridge's only placement value is "story"; omitting it yields a
        Reel. Sending anything else would make the post a Story by accident."""
        self.assertNotIn("placement", build_platform_configurations("A title")["instagram"])

    def test_blank_title_still_configures_instagram_but_omits_tiktok(self) -> None:
        config = build_platform_configurations("   ")
        self.assertIn("instagram", config)
        self.assertNotIn("tiktok", config)

    def test_tiktok_title_is_passed_through_trimmed(self) -> None:
        self.assertEqual(
            build_platform_configurations("  My title  ")["tiktok"], {"title": "My title"}
        )


class PostBridgeIntegrationTests(unittest.TestCase):
    def test_resolve_social_account_ids_interactive_prompts_for_ambiguous_accounts(self) -> None:
        client = Mock()
        client.list_social_accounts.return_value = [
            {"id": 21, "platform": "tiktok", "username": "brand"},
            {"id": 22, "platform": "tiktok", "username": "personal"},
            {"id": 31, "platform": "instagram", "username": "brand_ig"},
        ]
        prompt = Mock(side_effect=["2"])

        account_ids = resolve_social_account_ids(
            client=client,
            configured_account_ids=[],
            platforms=["tiktok", "instagram"],
            interactive=True,
            prompt_fn=prompt,
        )

        self.assertEqual(account_ids, [22, 31])
        prompt.assert_called_once()

    def test_resolve_social_account_ids_skips_non_interactive_when_multiple_accounts_exist(self) -> None:
        client = Mock()
        client.list_social_accounts.return_value = [
            {"id": 21, "platform": "tiktok", "username": "brand"},
            {"id": 22, "platform": "tiktok", "username": "personal"},
        ]

        account_ids = resolve_social_account_ids(
            client=client,
            configured_account_ids=[],
            platforms=["tiktok"],
            interactive=False,
        )

        self.assertEqual(account_ids, [])

    @patch("post_bridge_integration.PostBridge")
    @patch("post_bridge_integration.get_post_bridge_config")
    def test_cron_mode_skips_when_auto_crosspost_is_disabled(
        self,
        get_config_mock,
        post_bridge_cls_mock,
    ) -> None:
        get_config_mock.return_value = {
            "enabled": True,
            "api_key": "token",
            "platforms": ["tiktok", "instagram"],
            "account_ids": [12, 34],
            "auto_crosspost": False,
        }

        with tempfile.NamedTemporaryFile(suffix=".mp4") as media_file:
            result = maybe_crosspost_youtube_short(
                video_path=media_file.name,
                title="My title",
                interactive=False,
                youtube_privacy_status="public",
            )

        self.assertIsNone(result)
        post_bridge_cls_mock.assert_not_called()

    @patch("post_bridge_integration.PostBridge")
    @patch("post_bridge_integration.get_post_bridge_config")
    def test_interactive_crosspost_uploads_and_posts(
        self,
        get_config_mock,
        post_bridge_cls_mock,
    ) -> None:
        get_config_mock.return_value = {
            "enabled": True,
            "api_key": "token",
            "platforms": ["tiktok", "instagram"],
            "account_ids": [12, 34],
            "auto_crosspost": False,
        }
        client = post_bridge_cls_mock.return_value
        client.upload_media.return_value = "media-123"
        client.create_post.return_value = {"id": "post-123", "warnings": []}

        with tempfile.NamedTemporaryFile(suffix=".mp4") as media_file:
            result = maybe_crosspost_youtube_short(
                video_path=media_file.name,
                title="My title",
                interactive=True,
                youtube_privacy_status="public",
                prompt_fn=lambda _: "yes",
            )

        self.assertTrue(result)
        client.upload_media.assert_called_once()
        client.create_post.assert_called_once_with(
            caption="My title",
            social_account_ids=[12, 34],
            media_ids=["media-123"],
            platform_configurations={
                "instagram": {
                    "video_cover_timestamp_ms": (
                        post_bridge_integration.INSTAGRAM_COVER_TIMESTAMP_MS
                    )
                },
                "tiktok": {"title": "My title"},
            },
        )

    @patch("post_bridge_integration.PostBridge")
    @patch("post_bridge_integration.get_post_bridge_config")
    def test_account_ids_work_without_platform_filters(
        self,
        get_config_mock,
        post_bridge_cls_mock,
    ) -> None:
        get_config_mock.return_value = {
            "enabled": True,
            "api_key": "token",
            "platforms": [],
            "account_ids": [12, 34],
            "auto_crosspost": True,
        }
        client = post_bridge_cls_mock.return_value
        client.upload_media.return_value = "media-123"
        client.create_post.return_value = {"id": "post-123", "warnings": []}

        with tempfile.NamedTemporaryFile(suffix=".mp4") as media_file:
            result = maybe_crosspost_youtube_short(
                video_path=media_file.name,
                title="My title",
                interactive=False,
                youtube_privacy_status="public",
            )

        self.assertTrue(result)
        client.upload_media.assert_called_once()
        client.create_post.assert_called_once_with(
            caption="My title",
            social_account_ids=[12, 34],
            media_ids=["media-123"],
            platform_configurations={
                "instagram": {
                    "video_cover_timestamp_ms": (
                        post_bridge_integration.INSTAGRAM_COVER_TIMESTAMP_MS
                    )
                },
                "tiktok": {"title": "My title"},
            },
        )

    @patch("post_bridge_integration.PostBridge")
    @patch("post_bridge_integration.get_post_bridge_config")
    def test_private_youtube_upload_never_crossposts(
        self,
        get_config_mock,
        post_bridge_cls_mock,
    ) -> None:
        get_config_mock.return_value = {
            "enabled": True,
            "api_key": "token",
            "platforms": ["tiktok", "instagram"],
            "account_ids": [12, 34],
            "auto_crosspost": True,
        }

        result = maybe_crosspost_youtube_short(
            video_path="video.mp4",
            title="Private staging upload",
            interactive=False,
            youtube_privacy_status="private",
        )

        self.assertIsNone(result)
        get_config_mock.assert_not_called()
        post_bridge_cls_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
