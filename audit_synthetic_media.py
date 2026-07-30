#!/usr/bin/env python3
"""Read-only audit of YouTube altered/synthetic-media disclosure state."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from typing import Any

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

from brand_switcher import load_active_brand
from config import (
    get_youtube_api_client_secrets_path,
    get_youtube_api_key,
    get_youtube_api_token_path,
)
from youtube_api_upload import load_or_refresh_credentials


def _youtube_service() -> Any:
    from googleapiclient.discovery import build

    credentials = load_or_refresh_credentials(
        get_youtube_api_client_secrets_path(),
        get_youtube_api_token_path(),
    )
    return build("youtube", "v3", credentials=credentials)


def _public_youtube_service() -> Any:
    from googleapiclient.discovery import build

    api_key = get_youtube_api_key()
    if not api_key:
        raise RuntimeError(
            "youtube_api_key is required for the read-only audit fallback"
        )
    return build("youtube", "v3", developerKey=api_key)


def _channel_and_uploads_playlist(
    youtube: Any,
    *,
    channel_id: str = "",
) -> tuple[dict[str, Any], str]:
    request = {
        "part": "snippet,contentDetails",
        "maxResults": 1,
    }
    if channel_id:
        request["id"] = channel_id
    else:
        request["mine"] = True
    response = youtube.channels().list(**request).execute()
    items = response.get("items") or []
    if not items:
        raise RuntimeError("OAuth token is not linked to a YouTube channel")
    channel = items[0]
    uploads = (
        channel.get("contentDetails", {})
        .get("relatedPlaylists", {})
        .get("uploads")
    )
    if not uploads:
        raise RuntimeError("YouTube channel response did not include an uploads playlist")
    return channel, str(uploads)


def _video_ids(youtube: Any, uploads_playlist: str) -> Iterator[str]:
    page_token = None
    while True:
        response = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=uploads_playlist,
            maxResults=50,
            pageToken=page_token,
        ).execute()
        for item in response.get("items") or []:
            video_id = item.get("contentDetails", {}).get("videoId")
            if video_id:
                yield str(video_id)
        page_token = response.get("nextPageToken")
        if not page_token:
            break


def _chunks(values: list[str], size: int = 50) -> Iterator[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _video_details(youtube: Any, ids: list[str]) -> list[dict[str, Any]]:
    videos: list[dict[str, Any]] = []
    for batch in _chunks(ids):
        response = youtube.videos().list(
            part="snippet,status",
            id=",".join(batch),
            maxResults=50,
        ).execute()
        videos.extend(response.get("items") or [])
    order = {video_id: index for index, video_id in enumerate(ids)}
    videos.sort(key=lambda item: order.get(str(item.get("id") or ""), len(order)))
    return videos


def fetch_owned_videos(
    youtube: Any,
    *,
    channel_id: str = "",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    channel, uploads_playlist = _channel_and_uploads_playlist(
        youtube,
        channel_id=channel_id,
    )
    ids = list(_video_ids(youtube, uploads_playlist))
    return channel, _video_details(youtube, ids)


def fetch_owned_videos_with_read_fallback(
    youtube: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        return fetch_owned_videos(youtube)
    except Exception as exc:
        if getattr(getattr(exc, "resp", None), "status", None) != 403:
            raise
        print(
            "OAuth token cannot read channel metadata; using the configured "
            "YouTube Data API key for this read-only audit."
        )
        channel_id = str((load_active_brand() or {}).get("channel_id") or "")
        if not channel_id:
            raise RuntimeError(
                "Active brand manifest must provide channel_id for audit fallback"
            ) from exc
        try:
            public_youtube = _public_youtube_service()
            channel, uploads_playlist = _channel_and_uploads_playlist(
                public_youtube,
                channel_id=channel_id,
            )
            ids = list(_video_ids(public_youtube, uploads_playlist))
        except Exception as public_exc:
            status = getattr(getattr(public_exc, "resp", None), "status", "unknown")
            raise RuntimeError(
                f"Read-only YouTube API-key audit failed (HTTP {status})"
            ) from None
        try:
            return channel, _video_details(youtube, ids)
        except Exception as owner_exc:
            status = getattr(getattr(owner_exc, "resp", None), "status", "unknown")
            raise RuntimeError(
                "OAuth token cannot read owner disclosure state "
                f"(HTTP {status}); the token needs a YouTube read/manage scope."
            ) from None


def disclosure_gaps(videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        video
        for video in videos
        if video.get("status", {}).get("containsSyntheticMedia") is not True
    ]


def print_audit(channel: dict[str, Any], videos: list[dict[str, Any]]) -> int:
    channel_id = str(channel.get("id") or "")
    channel_title = str(channel.get("snippet", {}).get("title") or "")
    expected_channel_id = str((load_active_brand() or {}).get("channel_id") or "")
    print(f"Channel: {channel_title} ({channel_id})")
    if expected_channel_id and channel_id != expected_channel_id:
        print(
            "ERROR: OAuth token channel does not match the active brand manifest "
            f"({expected_channel_id})."
        )
        return 2

    print("video_id\tdisclosure\ttitle")
    for video in videos:
        status = video.get("status", {})
        value = status.get("containsSyntheticMedia")
        disclosure = "true" if value is True else "false" if value is False else "missing"
        title = str(video.get("snippet", {}).get("title") or "").replace("\t", " ")
        print(f"{video.get('id', '')}\t{disclosure}\t{title}")

    gaps = disclosure_gaps(videos)
    print()
    print(f"Total videos: {len(videos)}")
    print(f"Disclosure true: {len(videos) - len(gaps)}")
    print(f"Missing/false: {len(gaps)}")
    return 0


def main() -> int:
    try:
        youtube = _youtube_service()
        channel, videos = fetch_owned_videos_with_read_fallback(youtube)
        return print_audit(channel, videos)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
