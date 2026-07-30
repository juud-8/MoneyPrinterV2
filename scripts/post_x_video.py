#!/usr/bin/env python3
"""Post one or more existing episodes to X as native video tweets.

Unlike Post Bridge (TikTok/Instagram), X has no "schedule this for later"
API available to this bot — classes/Twitter.py drives the real x.com compose
screen via Selenium, so posting happens the moment this script runs. To get
a daily cadence, run this via Windows Task Scheduler (same pattern as
run_daily_early.ps1 / run_daily_prime.ps1) rather than trying to schedule
posts in advance.

Reuses the same episode<->mp4 matching logic as backfill_post_bridge.py so
both platforms draw from the identical, already-verified 39-episode pool.
State is tracked separately in .mp/x_post_state.json (independent of the
Post Bridge state file) since these are two different platforms/paces.

Usage (dry run — shows what would be posted, no browser opens):
    .\\venv\\Scripts\\python.exe scripts\\post_x_video.py the_strange_archive

Usage (actually posts):
    .\\venv\\Scripts\\python.exe scripts\\post_x_video.py the_strange_archive --live

Options:
    --count N   how many episodes to post this run (default 1)
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

from backfill_post_bridge import find_backfill_candidates  # noqa: E402

STATE_PATH = os.path.join(ROOT, ".mp", "x_post_state.json")
HASHTAG_BUDGET = 60  # leave room under X's 280-char limit after the title


def _load_state() -> dict:
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"posted_urls": []}


def _save_state(state: dict) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _load_twitter_account(brand_id: str) -> dict:
    twitter_cache_path = os.path.join(ROOT, ".mp", "twitter.json")
    with open(twitter_cache_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for account in data.get("accounts", []):
        if account.get("brand_id") == brand_id:
            return account
    raise ValueError(
        f"No .mp/twitter.json account found with brand_id={brand_id!r}. "
        "Add 'brand_id' to the account entry first."
    )


def _load_manifest_hashtags(brand_id: str) -> str:
    manifest_path = os.path.join(ROOT, "brands", brand_id, "manifest.json")
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        return manifest.get("default_hashtags", "")
    except Exception:
        return ""


def build_caption(title: str, hashtags: str) -> str:
    caption = title.strip()
    remaining = 280 - len(caption) - 1
    budget = min(remaining, HASHTAG_BUDGET)
    tags = []
    for tag in hashtags.split():
        if len(" ".join(tags + [tag])) > budget:
            break
        tags.append(tag)
    if tags:
        caption = f"{caption} {' '.join(tags)}"
    return caption[:280]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("brand_id")
    parser.add_argument("--live", action="store_true", help="actually open Firefox and post")
    parser.add_argument("--count", type=int, default=1)
    args = parser.parse_args()

    episodes = find_backfill_candidates(args.brand_id)
    state = _load_state()
    already = set(state.get("posted_urls", []))
    pending = [e for e in episodes if e["url"] not in already]

    print(f"\n{len(episodes)} matched episode(s) total.")
    print(f"{len(episodes) - len(pending)} already posted to X in a previous run.")
    print(f"{len(pending)} remaining in the queue.\n")

    if not pending:
        print("Nothing to do.")
        return 0

    hashtags = _load_manifest_hashtags(args.brand_id)
    batch = pending[: args.count]

    print(f"This run would post {len(batch)} video(s):\n")
    for ep in batch:
        caption = build_caption(ep["title"], hashtags)
        print(f"  {ep['title'][:60]}")
        print(f"    caption: {caption}")

    if not args.live:
        print("\nDRY RUN — no browser opened, nothing posted. Re-run with --live to post.")
        return 0

    account = _load_twitter_account(args.brand_id)

    from classes.Twitter import Twitter

    twitter = Twitter(
        account["id"], account["nickname"], account["firefox_profile"], account["topic"]
    )
    try:
        for ep in batch:
            caption = build_caption(ep["title"], hashtags)
            try:
                twitter.post_video(ep["video_path"], text=caption)
                state.setdefault("posted_urls", []).append(ep["url"])
                _save_state(state)
                print(f"  OK  {ep['title'][:60]}")
            except Exception as exc:
                print(f"  FAIL {ep['title'][:60]}: {type(exc).__name__}: {exc}")
                # Stop the batch on first failure rather than hammering a
                # possibly-broken selector/session across every remaining
                # video — check the account manually before re-running.
                break
    finally:
        twitter.close_browser()

    return 0


if __name__ == "__main__":
    sys.exit(main())
