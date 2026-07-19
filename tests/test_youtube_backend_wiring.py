"""Tests for the opt-in ASS-caption and YouTube-Data-API upload backends
wired into classes/YouTube.py (see config.get_caption_backend() /
config.get_upload_backend()). No Selenium, ffmpeg, or live network involved —
every external call is mocked at its source module.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from classes.YouTube import YouTube  # noqa: E402


def _make_youtube(**extra):
    yt = YouTube.__new__(YouTube)
    yt.run_id = "run-1"
    yt.format_type = "short"
    yt.research_brief = {}
    yt.research_brief_path = ""
    yt.production_metadata = {}
    yt._niche = "test niche"
    yt.subject = "Test Subject"
    yt.video_path = "video.mp4"
    yt.metadata = {"title": "Title", "description": "Description"}
    for key, value in extra.items():
        setattr(yt, key, value)
    return yt


class BurnAssCaptionsTests(unittest.TestCase):
    def test_returns_burned_path_on_success(self):
        yt = _make_youtube()
        with patch("caption_ass.write_ass_from_srt") as write_ass, patch(
            "caption_ass.burn_captions"
        ) as burn:
            result = yt._burn_ass_captions("video.mp4", "subs.srt")
        write_ass.assert_called_once()
        burn.assert_called_once()
        self.assertNotEqual(result, "video.mp4")
        self.assertTrue(result.endswith(".mp4"))

    def test_falls_back_to_original_path_on_failure(self):
        yt = _make_youtube()
        with patch(
            "caption_ass.write_ass_from_srt", side_effect=RuntimeError("boom")
        ), patch("classes.YouTube.warning") as warn:
            result = yt._burn_ass_captions("video.mp4", "subs.srt")
        self.assertEqual(result, "video.mp4")
        warn.assert_called_once()


class UploadVideoBackendSelectionTests(unittest.TestCase):
    def test_upload_video_delegates_to_api_backend_when_selected(self):
        yt = _make_youtube()
        with patch("classes.YouTube.get_upload_backend", return_value="api"), patch.object(
            yt, "_upload_video_api", return_value=True
        ) as api_upload:
            result = yt.upload_video()
        self.assertTrue(result)
        api_upload.assert_called_once()

    def test_upload_video_keeps_selenium_path_by_default(self):
        yt = _make_youtube()
        with patch("classes.YouTube.get_upload_backend", return_value="selenium"), patch.object(
            yt, "_upload_video_api"
        ) as api_upload, patch.object(
            yt, "get_channel_id", side_effect=RuntimeError("stop before Selenium")
        ), patch.object(yt, "close_browser"), patch("classes.YouTube.emit_stage"), patch(
            "classes.YouTube.error"
        ):
            yt.upload_video()
        api_upload.assert_not_called()


class UploadVideoApiTests(unittest.TestCase):
    def test_success_path_logs_and_returns_true(self):
        yt = _make_youtube(subtitles_path="subs.srt", thumbnail_path="")
        fake_result = MagicMock()
        fake_result.watch_url.return_value = "https://www.youtube.com/watch?v=abc123"

        with patch("classes.YouTube.emit_stage"), patch(
            "classes.YouTube.get_youtube_api_category_id", return_value="22"
        ), patch("classes.YouTube.get_publishing_config", return_value={}), patch(
            "classes.YouTube.get_is_for_kids", return_value=False
        ), patch(
            "classes.YouTube.get_youtube_api_client_secrets_path", return_value=""
        ), patch(
            "classes.YouTube.get_youtube_api_token_path", return_value=""
        ), patch(
            "classes.YouTube.load_active_brand", return_value={"brand_id": "test_brand"}
        ), patch(
            "classes.YouTube.log_video"
        ) as log_video, patch.object(
            yt, "add_video"
        ) as add_video, patch(
            "youtube_api_upload.build_api_upload_request"
        ) as build_request, patch(
            "youtube_api_upload.load_or_refresh_credentials", return_value="creds"
        ) as load_creds, patch(
            "youtube_api_upload.upload_video_resumable", return_value=fake_result
        ) as resumable:
            result = yt._upload_video_api()

        self.assertTrue(result)
        self.assertEqual(yt.uploaded_video_url, "https://www.youtube.com/watch?v=abc123")
        build_request.assert_called_once()
        _, kwargs = build_request.call_args
        self.assertEqual(kwargs["video_path"], "video.mp4")
        self.assertEqual(kwargs["title"], "Title")
        self.assertEqual(kwargs["srt_path"], "subs.srt")
        load_creds.assert_called_once()
        resumable.assert_called_once()
        _, resumable_kwargs = resumable.call_args
        self.assertTrue(resumable_kwargs["execute"])
        log_video.assert_called_once()
        add_video.assert_called_once()

    def test_failure_path_records_error_and_returns_false(self):
        yt = _make_youtube(subtitles_path="", thumbnail_path="")

        with patch("classes.YouTube.emit_stage"), patch(
            "classes.YouTube.get_youtube_api_category_id", return_value="22"
        ), patch("classes.YouTube.get_publishing_config", return_value={}), patch(
            "classes.YouTube.get_is_for_kids", return_value=False
        ), patch(
            "classes.YouTube.get_youtube_api_client_secrets_path", return_value=""
        ), patch(
            "classes.YouTube.get_youtube_api_token_path", return_value=""
        ), patch(
            "youtube_api_upload.build_api_upload_request"
        ), patch(
            "youtube_api_upload.load_or_refresh_credentials",
            side_effect=RuntimeError("no client secrets configured"),
        ), patch("classes.YouTube.error"):
            result = yt._upload_video_api()

        self.assertFalse(result)
        self.assertIn("no client secrets configured", yt.last_upload_error)


if __name__ == "__main__":
    unittest.main()
