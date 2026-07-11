#!/usr/bin/env python3
"""ARCHIVED — daily scheduled runner for 60 Second Thrillers.

Moved to scripts/_archived/ on 2026-07-11 when the brand was paused.
Previously logged to .mp/logs/thrillers_scheduled.log and wrote analytics
via the normal YouTube pipeline.

Do not invoke while ``sixty_second_thrillers`` remains in ARCHIVED_BRANDS.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

LOG_DIR = os.path.join(ROOT, ".mp", "logs")
BRAND_ID = "sixty_second_thrillers"
LOG_FILE = os.path.join(LOG_DIR, "thrillers_scheduled.log")


def _log(msg: str) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> None:
    from archived_brands import assert_brand_runnable, is_brand_archived

    if is_brand_archived(BRAND_ID):
        print(
            "SKIP: sixty_second_thrillers is archived — remove from "
            "ARCHIVED_BRANDS in src/archived_brands.py to resurrect."
        )
        sys.exit(2)

    parser = argparse.ArgumentParser()
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--episode", default=None, help="Episode label, e.g. 03")
    args = parser.parse_args()

    assert_brand_runnable(BRAND_ID)

    if args.upload:
        os.environ.setdefault("MPV2_PILOT_UPLOAD_CONFIRMED", "1")

    _log(f"Starting scheduled run — Episode {args.episode or '(auto)'}, upload={args.upload}")

    from llm_provider import select_model
    from config import get_ollama_model
    from brand_switcher import switch_brand, resolve_youtube_account, load_active_brand
    from classes.Tts import TTS
    from classes.YouTube import YouTube
    from review_gate import should_proceed_with_upload

    model = get_ollama_model()
    if not model:
        _log("ERROR: ollama_model not set in config.json")
        sys.exit(1)
    select_model(model)

    summary = switch_brand(BRAND_ID)
    for w in summary.get("warnings", []):
        _log(f"WARN: {w}")

    brand = load_active_brand()
    account = resolve_youtube_account(brand, create=True)
    if not account:
        _log("ERROR: Could not resolve YouTube account")
        sys.exit(1)

    youtube = YouTube(
        account["id"],
        account["nickname"],
        account["firefox_profile"],
        account["niche"],
        account["language"],
    )
    if args.episode:
        youtube.episode_number = args.episode

    tts = TTS()
    path = youtube.generate_video(tts, interactive=False)
    saved = getattr(youtube, "output_video_path", None) or path
    title = youtube.metadata.get("title", "")

    _log(f"Generated: {saved}")
    _log(f"Title: {title}")

    if not args.upload:
        youtube.close_browser()
        _log("Upload skipped (--upload not passed).")
        return

    if should_proceed_with_upload(
        youtube.video_path,
        title,
        youtube.metadata.get("description", ""),
        interactive=False,
    ):
        ok = youtube.upload_video()
        if ok:
            url = getattr(youtube, "uploaded_video_url", "unknown")
            _log(f"UPLOAD OK: {url}")
        else:
            _log("UPLOAD FAILED — video saved locally for manual upload")
            sys.exit(1)
    else:
        youtube.close_browser()
        _log("Upload blocked by review gate")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback

        _log(f"FATAL: {type(exc).__name__}: {exc}")
        for line in traceback.format_exc().splitlines():
            _log(line)
        sys.exit(1)
