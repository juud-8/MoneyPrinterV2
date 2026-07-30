#!/usr/bin/env python3
"""Daily scheduled runner for The Strange Archive (generate + optional upload).

Optimized publish-window scheduling
------------------------------------
Rather than uploading the instant generation finishes (which would make the
publish time drift with however long that day's LLM/TTS/image-gen run takes),
this script targets a specific daily publish window and holds the finished
video until a random moment inside that window before calling `upload_video()`.

Configured slots live in manifest `publishing.publish_slots`. Disabled slots
and slots that do not apply to today's weekday exit before generation.

The exact publish second still varies day to day (account-safety jitter).

If generation finishes after the window has closed, upload runs immediately.
"""
import argparse
import os
import random
import sys
import time
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

LOG_DIR = os.path.join(ROOT, ".mp", "logs")
BRAND_ID = "the_strange_archive"
_STATUS_TASK = "prime"

DEFAULT_SLOTS = {
    "midday": {"window_start": "12:15", "window_end": "12:30", "scheduler_start_hint": "11:45"},
    "early": {"window_start": "17:45", "window_end": "18:00", "scheduler_start_hint": "17:15"},
    "prime": {"window_start": "18:30", "window_end": "19:00", "scheduler_start_hint": "18:00"},
}


def _log(msg: str) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with open(os.path.join(LOG_DIR, "strange_archive_scheduled.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _write_status(ok: bool, reason: str = "") -> None:
    from run_status import write_run_status

    write_run_status(ok, reason, task=_STATUS_TASK)


def _run_with_status() -> None:
    from run_status import format_run_failure

    ok = False
    reason = ""
    try:
        main()
        ok = True
    except BaseException as exc:
        reason = format_run_failure(exc)
        raise
    finally:
        _write_status(ok, reason)


def _resolve_slot(slot: str) -> dict:
    """Merge manifest publish_slots over engine defaults."""
    merged = dict(DEFAULT_SLOTS.get(slot, DEFAULT_SLOTS["prime"]))
    try:
        from brand_switcher import load_brand

        manifest = load_brand(BRAND_ID) or {}
        configured = (manifest.get("publishing") or {}).get("publish_slots") or {}
        if isinstance(configured.get(slot), dict):
            for key in ("window_start", "window_end", "scheduler_start_hint"):
                if configured[slot].get(key):
                    merged[key] = configured[slot][key]
    except ImportError:
        pass
    return merged


def _parse_hhmm_today(value: str) -> datetime:
    hour, minute = (int(p) for p in value.split(":"))
    return datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)


def _pick_publish_time(window_start: str, window_end: str) -> datetime:
    """Pick a random target datetime inside [window_start, window_end] today,
    clamped to not be in the past relative to now."""
    now = datetime.now()
    start = _parse_hhmm_today(window_start)
    end = _parse_hhmm_today(window_end)
    if end <= start:
        end += timedelta(days=1)  # window spans midnight

    if now > start:
        start = now
    if start >= end:
        return now  # window already closed — publish immediately

    delta_seconds = (end - start).total_seconds()
    return start + timedelta(seconds=random.uniform(0, delta_seconds))


def _wait_until(target: datetime) -> None:
    now = datetime.now()
    if target <= now:
        return
    seconds = (target - now).total_seconds()
    _log(
        f"Holding finished video — publishing at {target.strftime('%H:%M:%S')} "
        f"(sleeping {seconds / 60:.1f} min)."
    )
    time.sleep(seconds)


def main():
    global _STATUS_TASK

    parser = argparse.ArgumentParser()
    parser.add_argument("--upload", action="store_true")
    parser.add_argument(
        "--slot",
        choices=sorted(DEFAULT_SLOTS),
        default="prime",
        help="Daily publish slot: midday (12:15-12:30 PM), early (5:45-6:00 PM), or prime (6:30-7:00 PM).",
    )
    parser.add_argument(
        "--publish-window-start",
        default=None,
        help="Override slot — HH:MM (24h) earliest publish time.",
    )
    parser.add_argument(
        "--publish-window-end",
        default=None,
        help="Override slot — HH:MM (24h) latest publish time.",
    )
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="Skip publish-window targeting and upload immediately after generation.",
    )
    parser.add_argument(
        "--max-hold-minutes",
        type=int,
        default=60,
        help="Cap the publish-window hold. If the next in-window publish time is "
        "further away than this (e.g. a catch-up run after the PC was off and Task "
        "Scheduler launched a missed slot), upload immediately instead of holding "
        "Firefox open for hours. Set 0 to disable the cap.",
    )
    parser.add_argument(
        "--jitter-max-minutes",
        type=int,
        default=0,
        help="Optional random delay (0-N minutes) before generation starts.",
    )
    parser.add_argument(
        "--topic",
        default=None,
        help="Preset topic/subject (skips LLM topic generation).",
    )
    parser.add_argument(
        "--force-topic",
        default=None,
        help="Deliberately regenerate this exact topic. Like --topic, presets "
        "the subject and BYPASSES the near-duplicate topic check (which only "
        "screens LLM-generated candidates). Pair with --title to control the "
        "upload title.",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Preset the video title verbatim (skips LLM title generation). "
        "Hashtag stripping and length limits still apply.",
    )
    args = parser.parse_args()
    _STATUS_TASK = args.slot
    os.environ["MPV2_RUN_TASK"] = args.slot
    if args.upload:
        os.environ["MPV2_UNATTENDED_UPLOAD"] = "1"

    from brand_switcher import load_brand
    from publishing_strategy import is_publish_slot_active, validate_publishing_strategy

    manifest = load_brand(BRAND_ID) or {}
    for strategy_warning in validate_publishing_strategy(manifest):
        _log(f"PUBLISHING CONFIG WARN: {strategy_warning}")
    if args.force_topic:
        _log("Manual forced-topic run — skipping publish-slot gating.")
    elif not is_publish_slot_active(manifest, args.slot):
        _log(f"SKIP [{args.slot}]: slot is disabled or not scheduled for today.")
        return

    slot_cfg = _resolve_slot(args.slot)
    window_start = args.publish_window_start or slot_cfg["window_start"]
    window_end = args.publish_window_end or slot_cfg["window_end"]

    if args.jitter_max_minutes > 0:
        delay_seconds = random.uniform(0, args.jitter_max_minutes * 60)
        _log(f"Startup jitter: sleeping {delay_seconds / 60:.1f} minutes before starting.")
        time.sleep(delay_seconds)

    from llm_provider import select_model
    from config import get_ollama_model
    from brand_switcher import switch_brand, resolve_youtube_account, load_active_brand
    from classes.Tts import TTS
    from classes.YouTube import YouTube
    from provider_health import assert_pilot_providers_ready
    from review_gate import should_proceed_with_upload

    skip_checks = os.environ.get("MPV2_SKIP_PROVIDER_CHECKS", "").strip() == "1"
    if not skip_checks:
        try:
            assert_pilot_providers_ready(BRAND_ID, ROOT)
        except RuntimeError as exc:
            _log(f"PROVIDER CHECK FAILED: {exc}")
            sys.exit(2)

    model = get_ollama_model()
    if not model:
        _log("ERROR: ollama_model not set in config.json")
        sys.exit(1)

    _log(
        f"Starting scheduled run — slot={args.slot}, "
        f"window={window_start}-{window_end}, upload={args.upload}"
    )
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
    forced_topic = (args.force_topic or args.topic or "").strip()
    if forced_topic:
        youtube.subject = forced_topic
        _log(f"Preset topic (dedupe bypassed): {youtube.subject}")
    if args.title:
        youtube.preset_title = args.title.strip()
        _log(f"Preset title: {youtube.preset_title}")

    tts = TTS()
    path = youtube.generate_video(tts, interactive=False)
    saved = getattr(youtube, "output_video_path", None) or path
    title = youtube.metadata.get("title", "")

    _log(f"Generated: {saved}")
    _log(f"Title: {title}")

    if not args.upload:
        youtube.close_browser()
        _log("Upload skipped (--upload not passed). Video saved for manual review.")
        return

    if not args.no_window:
        target = _pick_publish_time(window_start, window_end)
        if args.max_hold_minutes > 0:
            hold_minutes = (target - datetime.now()).total_seconds() / 60
            if hold_minutes > args.max_hold_minutes:
                _log(
                    f"Publish window is {hold_minutes:.0f} min away (> max-hold "
                    f"{args.max_hold_minutes} min) — treating as a missed/catch-up "
                    f"run and uploading now instead of holding Firefox open."
                )
                target = datetime.now()
        _wait_until(target)

    if should_proceed_with_upload(
        youtube.video_path,
        title,
        youtube.metadata.get("description", ""),
        interactive=False,
    ):
        ok = youtube.upload_video()
        if ok:
            url = getattr(youtube, "uploaded_video_url", "unknown")
            _log(f"UPLOAD OK [{args.slot}]: {url}")
            try:
                from post_bridge_integration import maybe_crosspost_youtube_short

                crosspost_result = maybe_crosspost_youtube_short(
                    video_path=youtube.video_path,
                    title=title,
                    interactive=False,
                    youtube_privacy_status=getattr(
                        youtube, "uploaded_privacy_status", ""
                    ),
                )
                if crosspost_result is True:
                    _log(f"POST BRIDGE CROSSPOST OK [{args.slot}]")
                elif crosspost_result is False:
                    _log(f"POST BRIDGE CROSSPOST FAILED [{args.slot}] (see warnings above)")
                # None means skipped (disabled/auto_crosspost off) — no log needed.
            except Exception as exc:
                _log(f"POST BRIDGE CROSSPOST ERROR [{args.slot}]: {type(exc).__name__}: {exc}")
        else:
            reason = getattr(youtube, "last_upload_error", "unknown (no exception captured)")
            _log(f"UPLOAD FAILED [{args.slot}]: {reason}")
            _log("Video saved locally for manual upload — see scripts/upload_brand_short.py")
            sys.exit(1)
    else:
        youtube.close_browser()
        _log("Upload blocked by review gate")


if __name__ == "__main__":
    try:
        _run_with_status()
    except Exception as exc:
        import traceback

        _log(f"FATAL: {type(exc).__name__}: {exc}")
        for line in traceback.format_exc().splitlines():
            _log(line)
        sys.exit(1)
