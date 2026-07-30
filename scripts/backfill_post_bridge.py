#!/usr/bin/env python3
"""Backfill existing uploaded episodes to TikTok/Instagram via Post Bridge.

Matches each already-uploaded episode in .mp/analytics.json to its local mp4
in output/<brand_id>/ (by the date-time prefix both share), then schedules
each one via Post Bridge's create_post(scheduled_at=...) API, spread out
oldest-first at a configurable pace (default 2/day) so a brand-new account
doesn't get 49 posts dumped on it in one burst.

State is tracked in .mp/post_bridge_backfill_state.json so re-running this
script is safe/idempotent — anything already scheduled is skipped.

Usage (dry run, shows the plan without calling the API):
    .\\venv\\Scripts\\python.exe scripts\\backfill_post_bridge.py the_strange_archive

Usage (actually schedules posts):
    .\\venv\\Scripts\\python.exe scripts\\backfill_post_bridge.py the_strange_archive --live

Options:
    --per-day N       posts per day per platform pair (default 2)
    --start TIME      first post time, ISO local time e.g. 2026-07-24T11:00
                       (default: tomorrow 11:00 local)
    --post-times H1,H2  hours of day (local, 24h) to post at, comma-separated
                        (default 11,19 — matches the brand's publish windows)
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

from config import get_post_bridge_config  # noqa: E402
from classes.PostBridge import PostBridge, PostBridgeClientError  # noqa: E402
from post_bridge_integration import build_platform_configurations  # noqa: E402

STATE_PATH = os.path.join(ROOT, ".mp", "post_bridge_backfill_state.json")


def _tz():
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("America/New_York")
    except Exception:
        return None


def _load_state() -> dict:
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"scheduled_urls": []}


def _save_state(state: dict) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _clean_title(title: str) -> str:
    return title.split("#")[0].strip().rstrip("|").strip()


def _filename_to_title_guess(filename: str) -> str:
    """Strip the leading date_time_ prefix and .mp4 extension, then turn
    underscores back into spaces for title-similarity comparison. Filenames
    encode *generation* time, not upload time, so this can be tens of minutes
    off the analytics.json "date" field — title text is the only reliable key.
    """
    name = os.path.splitext(filename)[0]
    parts = name.split("_", 2)
    remainder = parts[2] if len(parts) >= 3 else name
    return remainder.replace("_", " ")


def find_backfill_candidates(brand_id: str, min_score: float = 0.5) -> list[dict]:
    from topic_similarity import topic_similarity

    analytics_path = os.path.join(ROOT, ".mp", "analytics.json")
    with open(analytics_path, "r", encoding="utf-8") as f:
        analytics = json.load(f)

    output_dir = os.path.join(ROOT, "output", brand_id)
    available = os.listdir(output_dir) if os.path.isdir(output_dir) else []
    used_files: set[str] = set()

    episodes = []
    missing = []
    for v in analytics.get("videos", []):
        if v.get("brand_id") != brand_id or v.get("status") != "uploaded":
            continue
        url = (v.get("url") or "").strip()
        if not url:
            continue
        clean_title = _clean_title(v.get("title", ""))

        best_file, best_score = None, 0.0
        for f in available:
            if f in used_files:
                continue
            score = topic_similarity(clean_title, _filename_to_title_guess(f))
            if score > best_score:
                best_file, best_score = f, score

        if not best_file or best_score < min_score:
            missing.append(v.get("title", "?"))
            continue

        used_files.add(best_file)
        episodes.append(
            {
                "url": url,
                "title": clean_title,
                "date": v["date"],
                "video_path": os.path.join(output_dir, best_file),
                "match_score": round(best_score, 2),
            }
        )

    episodes.sort(key=lambda e: e["date"])
    if missing:
        print(f"NOTE: {len(missing)} uploaded episode(s) have no local mp4, skipping:")
        for t in missing:
            print(f"   - {t[:80]}")
    return episodes


def build_schedule(
    episodes: list[dict], start: datetime, per_day: int, post_hours: list[int]
) -> list[datetime]:
    tz = _tz()
    if tz and start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    times = []
    day_offset = 0
    slot_index = 0
    for _ in episodes:
        hour = post_hours[slot_index % len(post_hours)]
        when = (start + timedelta(days=day_offset)).replace(
            hour=hour, minute=0, second=0, microsecond=0
        )
        times.append(when)
        slot_index += 1
        if slot_index % per_day == 0:
            day_offset += 1
    return times


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("brand_id")
    parser.add_argument("--live", action="store_true", help="actually call the Post Bridge API")
    parser.add_argument("--per-day", type=int, default=2)
    parser.add_argument("--start", type=str, default=None, help="ISO local start time")
    parser.add_argument("--post-times", type=str, default="11,19")
    args = parser.parse_args()

    post_hours = [int(h) for h in args.post_times.split(",")]

    tz = _tz()
    if args.start:
        start = datetime.fromisoformat(args.start)
    else:
        now = datetime.now(tz) if tz else datetime.now()
        start = now + timedelta(days=1)

    episodes = find_backfill_candidates(args.brand_id)
    state = _load_state()
    already = set(state.get("scheduled_urls", []))
    pending = [e for e in episodes if e["url"] not in already]

    print(f"\n{len(episodes)} uploaded episode(s) with a local mp4 found.")
    print(f"{len(episodes) - len(pending)} already scheduled in a previous run — skipping.")
    print(f"{len(pending)} to schedule now.\n")

    if not pending:
        print("Nothing to do.")
        return 0

    schedule = build_schedule(pending, start, args.per_day, post_hours)
    span_days = (schedule[-1] - schedule[0]).days if len(schedule) > 1 else 0

    print(f"Plan: {args.per_day}/day at hours {post_hours}, spanning ~{span_days} days.\n")
    for ep, when in zip(pending, schedule):
        print(f"  {when.strftime('%Y-%m-%d %H:%M %Z'):<25} {ep['title'][:70]}")

    if not args.live:
        print("\nDRY RUN — no posts scheduled. Re-run with --live to actually schedule these.")
        return 0

    config = get_post_bridge_config()
    if not config["enabled"] or not config["api_key"]:
        print("ERROR: post_bridge is not enabled / api_key missing in config.json")
        return 1

    client = PostBridge(config["api_key"])
    account_ids = config["account_ids"]
    if not account_ids:
        print("ERROR: config.json post_bridge.account_ids is empty. Run "
              "scripts/resolve_post_bridge_accounts.py first.")
        return 1

    print("\nScheduling live via Post Bridge...\n")
    ok_count = 0
    for ep, when in zip(pending, schedule):
        try:
            media_id = client.upload_media(ep["video_path"])
            result = client.create_post(
                caption=ep["title"],
                social_account_ids=account_ids,
                media_ids=[media_id],
                platform_configurations=build_platform_configurations(ep["title"]),
                scheduled_at=when.isoformat(),
            )
            print(f"  OK  {when.strftime('%Y-%m-%d %H:%M')}  {ep['title'][:60]}  "
                  f"(post {result.get('id', '?')})")
            state.setdefault("scheduled_urls", []).append(ep["url"])
            _save_state(state)
            ok_count += 1
        except PostBridgeClientError as exc:
            print(f"  FAIL {ep['title'][:60]}: {exc}")

    print(f"\nScheduled {ok_count}/{len(pending)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
