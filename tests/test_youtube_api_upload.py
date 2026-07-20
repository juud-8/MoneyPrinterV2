"""Tests for YouTube Data API upload spike (no live network)."""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from youtube_api_upload import (
    OAUTH_SCOPES,
    build_api_upload_request,
    dry_run_upload,
    estimate_daily_upload_capacity,
    load_oauth_client_secrets,
    load_or_refresh_credentials,
    normalize_publish_at,
    resolve_upload_backend,
    upload_video_resumable,
)


class NormalizePublishAtTests(unittest.TestCase):
    def test_naive_local_time_converts_to_utc_z(self):
        from datetime import datetime, timezone

        past_now = datetime(2000, 1, 1, tzinfo=timezone.utc)
        result = normalize_publish_at("2026-07-21T18:30", now=past_now)
        self.assertTrue(result.endswith("Z"))
        self.assertRegex(result, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_space_separator_accepted(self):
        from datetime import datetime, timezone

        past_now = datetime(2000, 1, 1, tzinfo=timezone.utc)
        self.assertTrue(normalize_publish_at("2026-07-21 18:30", now=past_now).endswith("Z"))

    def test_past_time_rejected(self):
        with self.assertRaises(ValueError):
            normalize_publish_at("2001-01-01T00:00")

    def test_garbage_rejected(self):
        with self.assertRaises(ValueError):
            normalize_publish_at("tomorrow at 6")
        with self.assertRaises(ValueError):
            normalize_publish_at("")

    def test_build_request_with_publish_at_forces_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "v.mp4")
            with open(video, "wb") as handle:
                handle.write(b"fake")
            req = build_api_upload_request(
                video_path=video,
                title="Scheduled Short",
                privacy_status="public",
                publish_at="2099-01-01T12:00",
            )
            self.assertEqual(req.privacy_status, "private")
            body = req.to_videos_insert_body()
            self.assertEqual(body["status"]["privacyStatus"], "private")
            self.assertTrue(body["status"]["publishAt"].endswith("Z"))
            result = dry_run_upload(req)
            self.assertEqual(result.publish_at, req.publish_at)

    def test_no_publish_at_omits_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "v.mp4")
            with open(video, "wb") as handle:
                handle.write(b"fake")
            req = build_api_upload_request(video_path=video, title="T")
            self.assertNotIn("publishAt", req.to_videos_insert_body()["status"])


class YoutubeApiUploadTests(unittest.TestCase):
    def test_resolve_backend_defaults_selenium(self):
        self.assertEqual(resolve_upload_backend({}), "selenium")
        self.assertEqual(resolve_upload_backend({"upload_backend": "api"}), "api")
        self.assertEqual(
            resolve_upload_backend({"upload_backend": "selenium"}, env={"MPV2_UPLOAD_BACKEND": "api"}),
            "api",
        )

    def test_quota_capacity(self):
        self.assertEqual(estimate_daily_upload_capacity(10_000, 1600), 6)

    def test_build_request_defaults_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "v.mp4")
            with open(video, "wb") as handle:
                handle.write(b"fake")
            req = build_api_upload_request(
                video_path=video,
                title="Test Short",
                tags=["history", ""],
            )
            self.assertEqual(req.privacy_status, "private")
            body = req.to_videos_insert_body()
            self.assertEqual(body["status"]["privacyStatus"], "private")
            self.assertEqual(body["snippet"]["tags"], ["history"])

    def test_dry_run_validates_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "v.mp4")
            with open(video, "wb") as handle:
                handle.write(b"fake")
            req = build_api_upload_request(video_path=video, title="T", privacy_status="unlisted")
            result = dry_run_upload(req)
            self.assertTrue(result.dry_run)
            self.assertEqual(result.video_id, "DRY_RUN_VIDEO_ID")
            self.assertEqual(result.privacy_status, "unlisted")

    def test_execute_false_never_calls_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "v.mp4")
            with open(video, "wb") as handle:
                handle.write(b"fake")
            req = build_api_upload_request(video_path=video, title="T")
            service = MagicMock()
            result = upload_video_resumable(req, youtube_service=service, execute=False)
            self.assertTrue(result.dry_run)
            service.videos.assert_not_called()

    def test_load_client_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "client.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"installed": {"client_id": "x"}}, handle)
            data = load_oauth_client_secrets(path)
            self.assertIn("installed", data)


class LoadOrRefreshCredentialsTests(unittest.TestCase):
    """No live network/browser — every Google call is mocked at its source module."""

    def test_raises_when_client_secrets_missing_and_no_cached_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_path = os.path.join(tmp, "token.json")
            with self.assertRaises(RuntimeError):
                load_or_refresh_credentials("", token_path)

    def test_uses_cached_valid_token_without_consent_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_path = os.path.join(tmp, "token.json")
            with open(token_path, "w", encoding="utf-8") as handle:
                handle.write("{}")
            fake_creds = MagicMock(valid=True)
            with patch(
                "google.oauth2.credentials.Credentials.from_authorized_user_file",
                return_value=fake_creds,
            ), patch(
                "google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file"
            ) as flow_factory:
                result = load_or_refresh_credentials("", token_path)
            self.assertIs(result, fake_creds)
            flow_factory.assert_not_called()

    def test_refreshes_expired_token_without_consent_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_path = os.path.join(tmp, "token.json")
            with open(token_path, "w", encoding="utf-8") as handle:
                handle.write("{}")
            fake_creds = MagicMock(valid=False, expired=True, refresh_token="rt")
            fake_creds.to_json.return_value = '{"refreshed": true}'
            with patch(
                "google.oauth2.credentials.Credentials.from_authorized_user_file",
                return_value=fake_creds,
            ), patch("google.auth.transport.requests.Request"), patch(
                "google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file"
            ) as flow_factory:
                result = load_or_refresh_credentials("", token_path)
            fake_creds.refresh.assert_called_once()
            flow_factory.assert_not_called()
            self.assertIs(result, fake_creds)
            with open(token_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), '{"refreshed": true}')

    def test_runs_consent_flow_and_caches_token_when_none_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            secrets_path = os.path.join(tmp, "client.json")
            with open(secrets_path, "w", encoding="utf-8") as handle:
                json.dump({"installed": {}}, handle)
            token_path = os.path.join(tmp, "nested", "token.json")

            fake_creds = MagicMock()
            fake_creds.to_json.return_value = '{"minted": true}'
            fake_flow = MagicMock()
            fake_flow.run_local_server.return_value = fake_creds

            with patch(
                "google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file",
                return_value=fake_flow,
            ) as flow_factory:
                result = load_or_refresh_credentials(secrets_path, token_path)

            flow_factory.assert_called_once_with(secrets_path, OAUTH_SCOPES)
            fake_flow.run_local_server.assert_called_once_with(port=0)
            self.assertIs(result, fake_creds)
            with open(token_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), '{"minted": true}')


if __name__ == "__main__":
    unittest.main()
