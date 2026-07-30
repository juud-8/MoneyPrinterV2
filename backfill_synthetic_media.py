#!/usr/bin/env python3
"""Backfill YouTube altered/synthetic-media disclosure, dry-run by default."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

from audit_synthetic_media import (
    _youtube_service,
    disclosure_gaps,
    fetch_owned_videos_with_read_fallback,
)
from brand_switcher import load_active_brand
from youtube_api_upload import load_or_refresh_credentials  # noqa: F401

# Only fields documented as writable by videos.update(part="status").
# Values come from the current API resource; the script changes only
# containsSyntheticMedia and preserves every other writable status value.
WRITABLE_STATUS_FIELDS = (
    "privacyStatus",
    "publishAt",
    "license",
    "embeddable",
    "publicStatsViewable",
    "selfDeclaredMadeForKids",
    "containsSyntheticMedia",
)


def _preserved_status(current: dict[str, Any]) -> dict[str, Any]:
    status = {
        field: current[field]
        for field in WRITABLE_STATUS_FIELDS
        if field in current
    }
    status["containsSyntheticMedia"] = True
    return status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Apply videos.update calls. Without this flag, print a dry run only.",
    )
    args = parser.parse_args()

    try:
        youtube = _youtube_service()
        channel, videos = fetch_owned_videos_with_read_fallback(youtube)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    channel_id = str(channel.get("id") or "")
    channel_title = str(channel.get("snippet", {}).get("title") or "")
    expected_channel_id = str((load_active_brand() or {}).get("channel_id") or "")
    print(f"Channel: {channel_title} ({channel_id})")
    if expected_channel_id and channel_id != expected_channel_id:
        print(
            "ERROR: OAuth token channel does not match the active brand manifest "
            f"({expected_channel_id}). No changes made."
        )
        return 2

    gaps = disclosure_gaps(videos)
    if not gaps:
        print("No missing/false disclosure values found. Nothing to update.")
        return 0

    mode = "LIVE UPDATE" if args.confirm else "DRY RUN"
    print(f"{mode}: {len(gaps)} video(s) need containsSyntheticMedia=true")
    for video in gaps:
        video_id = str(video.get("id") or "")
        title = str(video.get("snippet", {}).get("title") or "")
        print(f"- {video_id}: {title}")

    if not args.confirm:
        print("Dry run only. Re-run with --confirm to apply these updates.")
        return 0

    updated = 0
    for video in gaps:
        video_id = str(video.get("id") or "")
        current_status = dict(video.get("status") or {})
        youtube.videos().update(
            part="status",
            body={
                "id": video_id,
                "status": _preserved_status(current_status),
            },
        ).execute()
        updated += 1
        print(f"UPDATED {video_id}")

    print(f"Updated: {updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
