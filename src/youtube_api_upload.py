"""YouTube Data API v3 resumable upload spike (beside Selenium).

Not the default upload path. Selenium Studio upload remains authoritative until
operators opt in via ``upload_backend: "api"`` (see ``resolve_upload_backend``).

Design goals (research spike):
- Resumable ``videos.insert`` with OAuth (not API-key-only)
- Default privacy ``private`` / ``unlisted`` for review-gate safety
- Optional SRT caption track attach after upload
- Never publish/public without explicit visibility + review gate upstream

This module deliberately does **not** import Selenium or mutate live channels
from unit tests. Live upload requires ``google-api-python-client`` + OAuth
client secrets and is gated behind ``execute=True``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from youtube_upload_flow import VALID_VISIBILITIES, resolve_upload_visibility

# videos.insert costs ~1600 quota units; default project quota is 10_000/day.
QUOTA_UNITS_PER_UPLOAD = 1600
DEFAULT_DAILY_QUOTA = 10_000

# Upload-only scope — deliberately not the broader youtube.force-ssl scope.
OAUTH_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


@dataclass(frozen=True)
class ApiUploadRequest:
    """Validated inputs for a resumable Data API upload."""

    video_path: str
    title: str
    description: str
    tags: tuple[str, ...]
    category_id: str
    privacy_status: str
    made_for_kids: bool
    srt_path: str | None = None
    thumbnail_path: str | None = None

    def to_videos_insert_body(self) -> dict[str, Any]:
        return {
            "snippet": {
                "title": self.title,
                "description": self.description,
                "tags": list(self.tags),
                "categoryId": self.category_id,
            },
            "status": {
                "privacyStatus": self.privacy_status,
                "selfDeclaredMadeForKids": bool(self.made_for_kids),
            },
        }


@dataclass(frozen=True)
class ApiUploadResult:
    video_id: str
    privacy_status: str
    backend: str = "api"
    caption_uploaded: bool = False
    dry_run: bool = False

    def watch_url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


def resolve_upload_backend(
    config: Mapping[str, Any] | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    """Return ``api`` or ``selenium`` (default). Env ``MPV2_UPLOAD_BACKEND`` wins."""
    env_map = env if env is not None else os.environ
    raw_env = str(env_map.get("MPV2_UPLOAD_BACKEND") or "").strip().lower()
    if raw_env in {"api", "selenium"}:
        return raw_env
    raw = ""
    if isinstance(config, Mapping):
        raw = str(config.get("upload_backend") or "").strip().lower()
    if raw in {"api", "selenium"}:
        return raw
    return "selenium"


def estimate_daily_upload_capacity(
    daily_quota: int = DEFAULT_DAILY_QUOTA,
    units_per_upload: int = QUOTA_UNITS_PER_UPLOAD,
) -> int:
    """How many ``videos.insert`` calls fit in a daily quota budget."""
    if units_per_upload <= 0:
        raise ValueError("units_per_upload must be positive")
    return max(0, int(daily_quota) // int(units_per_upload))


def build_api_upload_request(
    *,
    video_path: str,
    title: str,
    description: str = "",
    tags: Sequence[str] | None = None,
    category_id: str = "22",
    publishing: Mapping[str, Any] | None = None,
    privacy_status: str | None = None,
    made_for_kids: bool = False,
    srt_path: str | None = None,
    thumbnail_path: str | None = None,
    fallback_visibility: str = "private",
) -> ApiUploadRequest:
    """Build a validated upload request. Defaults to private for review safety."""
    if not video_path or not str(video_path).strip():
        raise ValueError("video_path is required")
    title_clean = (title or "").strip()
    if not title_clean:
        raise ValueError("title is required")
    if privacy_status is None:
        visibility = resolve_upload_visibility(
            dict(publishing or {}), fallback=fallback_visibility
        )
    else:
        visibility = str(privacy_status).strip().lower()
    if visibility not in VALID_VISIBILITIES:
        raise ValueError(
            f"privacy_status must be one of {VALID_VISIBILITIES}, got {visibility!r}"
        )
    tag_list = [str(tag).strip() for tag in (tags or ()) if str(tag).strip()]
    return ApiUploadRequest(
        video_path=os.path.abspath(video_path),
        title=title_clean[:100],
        description=str(description or ""),
        tags=tuple(tag_list),
        category_id=str(category_id or "22"),
        privacy_status=visibility,
        made_for_kids=bool(made_for_kids),
        srt_path=os.path.abspath(srt_path) if srt_path else None,
        thumbnail_path=os.path.abspath(thumbnail_path) if thumbnail_path else None,
    )


def dry_run_upload(request: ApiUploadRequest) -> ApiUploadResult:
    """Validate paths and return a fake result without calling Google."""
    if not os.path.isfile(request.video_path):
        raise FileNotFoundError(f"Video not found: {request.video_path}")
    if request.srt_path and not os.path.isfile(request.srt_path):
        raise FileNotFoundError(f"SRT not found: {request.srt_path}")
    if request.thumbnail_path and not os.path.isfile(request.thumbnail_path):
        raise FileNotFoundError(f"Thumbnail not found: {request.thumbnail_path}")
    return ApiUploadResult(
        video_id="DRY_RUN_VIDEO_ID",
        privacy_status=request.privacy_status,
        caption_uploaded=bool(request.srt_path),
        dry_run=True,
    )


def load_oauth_client_secrets(path: str) -> dict[str, Any]:
    """Load a Google OAuth client_secrets JSON (installed/web app)."""
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("client_secrets must be a JSON object")
    if "installed" not in data and "web" not in data:
        raise ValueError(
            "client_secrets.json must contain an 'installed' or 'web' OAuth client"
        )
    return data


def load_or_refresh_credentials(client_secrets_path: str, token_path: str) -> Any:
    """Load cached OAuth credentials for the API upload backend, refreshing or
    running first-run interactive consent as needed.

    First-run opens a local browser consent screen (``InstalledAppFlow``) and
    caches the resulting refresh token at ``token_path`` so unattended cron
    runs after that only need a silent token refresh — never a browser popup.
    Requires a Desktop OAuth client secrets JSON from Google Cloud Console
    (not a service account, which cannot drive the consent screen).
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if token_path and os.path.isfile(token_path):
        creds = Credentials.from_authorized_user_file(token_path, OAUTH_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not client_secrets_path or not os.path.isfile(client_secrets_path):
                raise RuntimeError(
                    "youtube_api_client_secrets_path is not set or the file does "
                    "not exist. Download a Desktop OAuth client from Google Cloud "
                    "Console and point youtube_api_client_secrets_path at it, then "
                    "run once interactively to complete consent."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                client_secrets_path, OAUTH_SCOPES
            )
            creds = flow.run_local_server(port=0)
        if token_path:
            os.makedirs(os.path.dirname(os.path.abspath(token_path)) or ".", exist_ok=True)
            with open(token_path, "w", encoding="utf-8") as handle:
                handle.write(creds.to_json())

    return creds


def _run_resumable_insert(
    youtube_service: Any,
    request: ApiUploadRequest,
    *,
    chunksize: int,
) -> str:
    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(
        request.video_path,
        mimetype="video/*",
        resumable=True,
        chunksize=chunksize,
    )
    insert = youtube_service.videos().insert(
        part="snippet,status",
        body=request.to_videos_insert_body(),
        media_body=media,
    )
    response = None
    while response is None:
        _status, response = insert.next_chunk()
    video_id = response.get("id") if isinstance(response, dict) else None
    if not video_id:
        raise RuntimeError("YouTube API upload completed without a video id")
    return str(video_id)


def upload_video_resumable(
    request: ApiUploadRequest,
    *,
    credentials: Any = None,
    execute: bool = False,
    youtube_service: Any = None,
    chunksize: int = 8 * 1024 * 1024,
) -> ApiUploadResult:
    """Perform a resumable Data API upload when ``execute=True``.

    Unit tests pass a fake ``youtube_service``. Live runs require OAuth
    credentials from ``google-auth`` / ``google-api-python-client``.
    """
    if not execute:
        return dry_run_upload(request)

    service = youtube_service
    if service is None:
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "google-api-python-client is required for API upload. "
                "Install it and configure OAuth client secrets before execute=True."
            ) from exc
        if credentials is None:
            raise RuntimeError("OAuth credentials are required for execute=True")
        service = build("youtube", "v3", credentials=credentials)

    video_id = _run_resumable_insert(service, request, chunksize=chunksize)
    caption_uploaded = False
    if request.srt_path:
        caption_uploaded = _upload_caption_track(service, video_id, request.srt_path)
    return ApiUploadResult(
        video_id=video_id,
        privacy_status=request.privacy_status,
        caption_uploaded=caption_uploaded,
        dry_run=False,
    )


def _upload_caption_track(youtube_service: Any, video_id: str, srt_path: str) -> bool:
    """Best-effort SRT caption attach. Returns False if the API call fails."""
    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        return False
    try:
        media = MediaFileUpload(srt_path, mimetype="application/octet-stream")
        youtube_service.captions().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "language": "en",
                    "name": "English",
                    "isDraft": False,
                }
            },
            media_body=media,
        ).execute()
        return True
    except Exception:
        return False
