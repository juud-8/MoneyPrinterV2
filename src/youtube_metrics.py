"""YouTube Data API v3 metrics fetcher.

Fills the empty `views` (plus likes/comments) slots in `.mp/analytics.json`
for every uploaded video that has a URL, and appends per-channel subscriber /
view snapshots so the dashboard can chart channel growth over time.

Uses only a plain API key (no OAuth) — public statistics only. Private
metrics (CTR, impressions, retention) are not available this way; those
fields stay manual or come from a future Studio scrape / Analytics API pass.

Run directly: `python src/youtube_metrics.py`
"""

import re
from datetime import datetime

import requests

import analytics
from config import get_youtube_api_key

API_BASE = "https://www.googleapis.com/youtube/v3"
BATCH_SIZE = 50

_VIDEO_ID_PATTERNS = [
    re.compile(r"youtube\.com/shorts/([A-Za-z0-9_-]{6,})"),
    re.compile(r"youtube\.com/watch\?(?:.*&)?v=([A-Za-z0-9_-]{6,})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{6,})"),
    re.compile(r"youtube\.com/embed/([A-Za-z0-9_-]{6,})"),
]


def extract_video_id(url: str) -> str:
    """Return the YouTube video id from a watch/shorts/youtu.be URL, or ''."""
    if not url:
        return ""
    for pattern in _VIDEO_ID_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return ""


def _chunked(items: list, size: int = BATCH_SIZE):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _raise_with_hint(response: requests.Response) -> None:
    """Turn 401/403 into a setup hint instead of a bare traceback."""
    if response.status_code in (401, 403):
        raise RuntimeError(
            f"YouTube Data API rejected the key (HTTP {response.status_code}). "
            "AI Studio Gemini keys don't work here — create a standard API key "
            "in Google Cloud Console with 'YouTube Data API v3' enabled and set "
            "it as 'youtube_api_key' in config.json.\n"
            "  1. https://console.cloud.google.com/apis/library/youtube.googleapis.com — Enable\n"
            "  2. https://console.cloud.google.com/apis/credentials — Create credentials > API key"
        )
    response.raise_for_status()


def fetch_video_stats(video_ids: list[str], api_key: str | None = None) -> dict[str, dict]:
    """Batch-fetch public statistics for video ids. Returns {id: stats dict}."""
    api_key = api_key or get_youtube_api_key()
    if not api_key:
        raise RuntimeError(
            "No YouTube API key configured. Set 'youtube_api_key' in config.json "
            "(or YOUTUBE_API_KEY env var) with the YouTube Data API v3 enabled."
        )

    results: dict[str, dict] = {}
    for batch in _chunked([v for v in video_ids if v]):
        response = requests.get(
            f"{API_BASE}/videos",
            params={"part": "statistics", "id": ",".join(batch), "key": api_key},
            timeout=30,
        )
        _raise_with_hint(response)
        for item in response.json().get("items", []):
            stats = item.get("statistics", {})
            results[item["id"]] = {
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats["likeCount"]) if "likeCount" in stats else None,
                "comments": int(stats["commentCount"]) if "commentCount" in stats else None,
            }
    return results


def fetch_channel_stats(channel_ids: list[str], api_key: str | None = None) -> dict[str, dict]:
    """Batch-fetch public channel statistics. Returns {channel_id: stats dict}."""
    api_key = api_key or get_youtube_api_key()
    if not api_key:
        raise RuntimeError("No YouTube API key configured.")

    results: dict[str, dict] = {}
    for batch in _chunked([c for c in channel_ids if c]):
        response = requests.get(
            f"{API_BASE}/channels",
            params={"part": "statistics", "id": ",".join(batch), "key": api_key},
            timeout=30,
        )
        _raise_with_hint(response)
        for item in response.json().get("items", []):
            stats = item.get("statistics", {})
            results[item["id"]] = {
                "subscribers": int(stats.get("subscriberCount", 0)),
                "total_views": int(stats.get("viewCount", 0)),
                "video_count": int(stats.get("videoCount", 0)),
            }
    return results


def fetch_channel_uploads_rss(channel_id: str) -> list[dict]:
    """Latest ~15 uploads for a channel via the public RSS feed (no API key).

    Returns [{"video_id": ..., "title": ...}, ...]; empty list on any failure.
    """
    if not channel_id:
        return []
    try:
        response = requests.get(
            "https://www.youtube.com/feeds/videos.xml",
            params={"channel_id": channel_id},
            timeout=20,
        )
        response.raise_for_status()
        import xml.etree.ElementTree as ET

        ns = {
            "a": "http://www.w3.org/2005/Atom",
            "yt": "http://www.youtube.com/xml/schemas/2015",
        }
        root = ET.fromstring(response.text)
        uploads = []
        for entry in root.findall("a:entry", ns):
            video_id = entry.find("yt:videoId", ns)
            title = entry.find("a:title", ns)
            if video_id is not None and title is not None:
                uploads.append({"video_id": video_id.text, "title": title.text or ""})
        return uploads
    except Exception:
        return []


def repair_video_urls() -> dict:
    """Fix stale/missing URLs on uploaded entries using channel RSS feeds.

    The old upload flow could log the URL of the PREVIOUS video when the new
    one was still processing (stale top row in the Studio list). Matching
    logged titles against the channel's actual uploads lets us:
    - reassign an entry whose title matches a different real video,
    - clear a URL whose real video has a different title (stale capture),
    - fill in URLs for uploaded entries that were logged without one.
    Entries whose titles aren't in the feed (e.g. still processing, or older
    than the feed's ~15-item window) are left alone.
    """
    try:
        from brand_switcher import list_brands

        channel_ids = [b.get("channel_id") for b in list_brands() if b.get("channel_id")]
    except ImportError:
        channel_ids = []

    title_to_id: dict[str, str] = {}
    id_to_title: dict[str, str] = {}
    for channel_id in channel_ids:
        for upload in fetch_channel_uploads_rss(channel_id):
            normalized = analytics._normalize_title(upload["title"])
            title_to_id[normalized] = upload["video_id"]
            id_to_title[upload["video_id"]] = normalized

    if not title_to_id:
        return {"reassigned": 0, "cleared": 0, "filled": 0}

    data = analytics._load()
    reassigned = cleared = filled = 0

    for entry in data.get("videos", []):
        if entry.get("status") != "uploaded" and not entry.get("url"):
            continue
        entry_title = analytics._normalize_title(entry.get("title", ""))
        expected_id = title_to_id.get(entry_title, "")
        current_id = extract_video_id(entry.get("url", ""))

        if expected_id and current_id != expected_id:
            entry["url"] = f"https://www.youtube.com/watch?v={expected_id}"
            if current_id:
                reassigned += 1
            else:
                filled += 1
        elif (
            not expected_id
            and current_id
            and current_id in id_to_title
            and id_to_title[current_id] != entry_title
        ):
            # The URL points at a real video whose title doesn't match this
            # entry — a stale capture. Better no URL than a wrong one.
            entry["url"] = ""
            cleared += 1

    if reassigned or cleared or filled:
        analytics._save(data)
    return {"reassigned": reassigned, "cleared": cleared, "filled": filled}


def update_video_metrics(api_key: str | None = None) -> dict:
    """Refresh views/likes/comments for every logged video with a URL.

    Updates the raw entries in analytics.json in place so the deduped
    dashboard rows pick the metrics up automatically.
    """
    data = analytics._load()
    videos = data.get("videos", [])

    id_to_entries: dict[str, list[dict]] = {}
    for entry in videos:
        video_id = extract_video_id(entry.get("url", ""))
        if video_id:
            id_to_entries.setdefault(video_id, []).append(entry)

    if not id_to_entries:
        return {"updated": 0, "found": 0, "missing": 0}

    stats = fetch_video_stats(list(id_to_entries), api_key=api_key)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    updated = 0
    for video_id, entries in id_to_entries.items():
        if video_id not in stats:
            continue  # deleted/private video — leave existing values alone
        for entry in entries:
            entry["views"] = stats[video_id]["views"]
            entry["likes"] = stats[video_id]["likes"]
            entry["comments"] = stats[video_id]["comments"]
            entry["metrics_updated_at"] = now
            updated += 1

    analytics._save(data)
    return {
        "updated": updated,
        "found": len(stats),
        "missing": len(id_to_entries) - len(stats),
    }


def snapshot_channels(api_key: str | None = None) -> list[dict]:
    """Append a per-brand channel stats snapshot to analytics.json."""
    try:
        from brand_switcher import list_brands

        brands = list_brands()
    except ImportError:
        brands = []

    channel_map = {
        b["channel_id"]: b["brand_id"] for b in brands if b.get("channel_id")
    }
    if not channel_map:
        return []

    stats = fetch_channel_stats(list(channel_map), api_key=api_key)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    snapshots = []
    for channel_id, channel_stats in stats.items():
        snapshots.append(
            {
                "date": now,
                "brand_id": channel_map[channel_id],
                "channel_id": channel_id,
                **channel_stats,
            }
        )

    if snapshots:
        data = analytics._load()
        data.setdefault("channel_snapshots", []).extend(snapshots)
        analytics._save(data)
    return snapshots


def get_latest_channel_snapshots() -> dict[str, dict]:
    """Most recent snapshot per brand: {brand_id: snapshot}."""
    data = analytics._load()
    latest: dict[str, dict] = {}
    for snap in data.get("channel_snapshots", []):
        brand_id = snap.get("brand_id", "unknown")
        if brand_id not in latest or (snap.get("date", "") >= latest[brand_id].get("date", "")):
            latest[brand_id] = snap
    return latest


def update_all(api_key: str | None = None) -> dict:
    """Full refresh: URL repair + per-video metrics + channel snapshots."""
    repair_result = repair_video_urls()
    video_result = update_video_metrics(api_key=api_key)
    snapshots = snapshot_channels(api_key=api_key)
    return {**repair_result, **video_result, "channels_snapshotted": len(snapshots)}


if __name__ == "__main__":
    result = update_all()
    print(
        f"URL repair: {result['reassigned']} reassigned, {result['cleared']} cleared, "
        f"{result['filled']} filled."
    )
    print(
        f"Metrics refresh: {result['updated']} entry update(s) across "
        f"{result['found']} live video(s), {result['missing']} not found on API, "
        f"{result['channels_snapshotted']} channel snapshot(s) recorded."
    )
