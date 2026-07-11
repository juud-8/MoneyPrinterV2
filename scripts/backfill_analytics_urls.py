"""One-off backfill: fix missing/wrong URLs in .mp/analytics.json.

Queries the YouTube Data API for the channel's full upload list (playlistItems
on the uploads playlist — unlike the RSS feed this is not limited to the last
~15 videos), matches uploads to logged entries by normalized title + publish
date, and fills in or corrects the `url` field.

Scope is intentionally narrow: only entries with status "uploaded" dated
2026-07-02 through 2026-07-09 (the known-broken July 3 / 7 / 8 uploads).

Usage (from repo root):
    python scripts/backfill_analytics_urls.py            # dry run: print diff
    python scripts/backfill_analytics_urls.py --apply    # write (backs up first)
"""

import argparse
import copy
import difflib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYTICS_PATH = os.path.join(ROOT, ".mp", "analytics.json")
CONFIG_PATH = os.path.join(ROOT, "config.json")

CHANNEL_ID = "UCkb-jEr7ZUnETocZ_pzYTVg"
UPLOADS_PLAYLIST = "UU" + CHANNEL_ID[2:]
API_BASE = "https://www.googleapis.com/youtube/v3"

WINDOW_START = "2026-07-02"
WINDOW_END = "2026-07-09"
MAX_PUBLISH_DELTA_DAYS = 5

VIDEO_ID_RE = re.compile(r"(?:watch\?v=|shorts/|youtu\.be/|embed/)([A-Za-z0-9_-]{6,})")


def normalize_title(title: str) -> str:
    """Same normalization as analytics._normalize_title."""
    text = re.sub(r"\s+", " ", (title or "").strip())
    if " | " in text:
        text = text.rsplit(" | ", 1)[0].strip()
    return text.lower()


def get_api_key() -> str:
    key = os.environ.get("YOUTUBE_API_KEY", "")
    if not key and os.path.isfile(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            key = json.load(f).get("youtube_api_key", "")
    if not key:
        sys.exit("No YouTube API key (config.json 'youtube_api_key' or YOUTUBE_API_KEY).")
    return key


def fetch_all_uploads(api_key: str) -> list[dict]:
    """Every upload on the channel: [{video_id, title, published_at}, ...]."""
    uploads = []
    page_token = None
    while True:
        params = {
            "part": "snippet",
            "playlistId": UPLOADS_PLAYLIST,
            "maxResults": 50,
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token
        response = requests.get(f"{API_BASE}/playlistItems", params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        for item in payload.get("items", []):
            snippet = item.get("snippet", {})
            video_id = snippet.get("resourceId", {}).get("videoId", "")
            if video_id:
                uploads.append(
                    {
                        "video_id": video_id,
                        "title": snippet.get("title", ""),
                        "published_at": snippet.get("publishedAt", ""),
                    }
                )
        page_token = payload.get("nextPageToken")
        if not page_token:
            return uploads


def titles_match(entry_norm: str, upload_norm: str) -> bool:
    if entry_norm == upload_norm:
        return True
    # Logged titles are often truncated mid-hashtag; accept prefix matches.
    if len(entry_norm) >= 20 and (
        upload_norm.startswith(entry_norm) or entry_norm.startswith(upload_norm)
    ):
        return True
    return False


def strip_title(norm: str) -> str:
    """Drop hashtags and punctuation for looser matching (renamed uploads)."""
    text = re.sub(r"#\w+", " ", norm)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def stripped_match(entry_norm: str, upload_norm: str) -> bool:
    a, b = strip_title(entry_norm), strip_title(upload_norm)
    return bool(a) and len(a) >= 20 and (a == b or b.startswith(a) or a.startswith(b))


def publish_delta_days(entry_date: str, published_at: str) -> float:
    # Entry dates are naive local time; .astimezone() attaches the system tz.
    local = datetime.strptime(entry_date, "%Y-%m-%d %H:%M:%S").astimezone()
    published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    return abs((published - local).total_seconds()) / 86400


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = parser.parse_args()

    uploads = fetch_all_uploads(get_api_key())
    print(f"Fetched {len(uploads)} upload(s) from channel {CHANNEL_ID}.\n")

    with open(ANALYTICS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    before = json.dumps(data, indent=2, ensure_ascii=False).splitlines(keepends=True)
    original = copy.deepcopy(data)

    videos = data.get("videos", [])
    in_window = [
        e
        for e in videos
        if e.get("status") == "uploaded"
        and WINDOW_START <= e.get("date", "")[:10] <= WINDOW_END
    ]

    def claimed_elsewhere(upload: dict, entry: dict) -> bool:
        """Is this upload already accounted for by a different log entry?"""
        upload_norm = normalize_title(upload["title"])
        for other in videos:
            if other is entry:
                continue
            id_match = VIDEO_ID_RE.search(other.get("url", ""))
            if id_match and id_match.group(1) == upload["video_id"]:
                return True
            if other.get("status") == "uploaded" and titles_match(
                normalize_title(other.get("title", "")), upload_norm
            ):
                return True
        return False

    changes = []
    unmatched = []
    for entry in in_window:
        date = entry["date"]
        entry_norm = normalize_title(entry.get("title", ""))
        recent = [
            u for u in uploads
            if publish_delta_days(date, u["published_at"]) <= MAX_PUBLISH_DELTA_DAYS
        ]

        # 1. Normalized title match (exact / truncation prefix).
        candidates = [u for u in recent if titles_match(entry_norm, normalize_title(u["title"]))]
        how = "title"
        # 2. Hashtag/punctuation-stripped match — catches uploads renamed on YouTube.
        if not candidates:
            candidates = [u for u in recent if stripped_match(entry_norm, normalize_title(u["title"]))]
            how = "stripped title"
        # 3. Unique unclaimed upload published within 45 min of the logged upload.
        if not candidates:
            near = [
                u for u in uploads
                if publish_delta_days(date, u["published_at"]) <= 45 / (24 * 60)
                and not claimed_elsewhere(u, entry)
            ]
            if len(near) == 1:
                candidates = near
                how = "publish time (±45 min)"

        if not candidates:
            unmatched.append((date, entry.get("title", ""), entry.get("url", "")))
            continue

        best = min(candidates, key=lambda u: publish_delta_days(date, u["published_at"]))
        new_url = f"https://www.youtube.com/watch?v={best['video_id']}"
        current = entry.get("url", "")
        current_id_match = VIDEO_ID_RE.search(current)
        current_id = current_id_match.group(1) if current_id_match else ""

        if current_id == best["video_id"]:
            continue  # already correct
        kind = "FILL" if not current else "CORRECT"
        changes.append((kind, date, entry.get("title", ""), current, new_url, best, how))
        entry["url"] = new_url
        # Sync the logged title to the real YouTube title, otherwise the
        # RSS-based repair_video_urls() sees a mismatch and clears the URL
        # again on the next scheduled refresh.
        if normalize_title(best["title"]) != entry_norm:
            entry["title"] = best["title"]

    for kind, date, title, old, new, upload, how in changes:
        print(f"[{kind}] {date}  {title}")
        if old:
            print(f"    old: {old}")
        print(f"    new: {new}  (matched by {how}; YouTube title: {upload['title']!r}, "
              f"published {upload['published_at']})")
    for date, title, current in unmatched:
        print(f"[NO MATCH] {date}  {title}")
        print(f"    url left as-is: {current!r} — no upload with a matching title "
              f"within {MAX_PUBLISH_DELTA_DAYS} days")

    if not changes:
        print("\nNo URL changes needed.")
        return

    after = json.dumps(data, indent=2, ensure_ascii=False).splitlines(keepends=True)
    print("\n--- analytics.json diff " + "-" * 40)
    sys.stdout.writelines(
        difflib.unified_diff(before, after, "analytics.json (before)", "analytics.json (after)")
    )
    print("-" * 64)

    if args.apply:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # .json suffix on purpose: rem_temp_files() deletes non-.json in .mp/.
        backup = os.path.join(os.path.dirname(ANALYTICS_PATH), f"analytics_backup_{stamp}.json")
        shutil.copy2(ANALYTICS_PATH, backup)
        with open(ANALYTICS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"\nApplied {len(changes)} change(s). Backup: {backup}")
    else:
        data.clear()
        data.update(original)
        print(f"\nDry run — {len(changes)} change(s) NOT written. Re-run with --apply.")


if __name__ == "__main__":
    main()
