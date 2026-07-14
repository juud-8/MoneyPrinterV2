#!/usr/bin/env python3
"""Non-interactive Short generator for active or specified brand."""
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

from llm_provider import select_model
from config import get_ollama_model
from brand_switcher import switch_brand, resolve_youtube_account, load_active_brand
from classes.Tts import TTS
from classes.YouTube import YouTube


def _parse_flag(argv: list[str], flag: str) -> str | None:
    for i, arg in enumerate(argv):
        if arg == flag and i + 1 < len(argv):
            return argv[i + 1]
        prefix = f"{flag}="
        if arg.startswith(prefix):
            return arg.split("=", 1)[1]
    return None


def _parse_episode(argv: list[str]) -> str | None:
    return _parse_flag(argv, "--episode")


def main():
    brand_id = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "the_strange_archive"
    do_upload = "--upload" in sys.argv
    episode = _parse_episode(sys.argv)
    topic = _parse_flag(sys.argv, "--topic")
    trend_seed_id = _parse_flag(sys.argv, "--trend-seed")
    if trend_seed_id and topic:
        print("ERROR: --trend-seed and --topic are mutually exclusive")
        sys.exit(2)

    from archived_brands import assert_brand_runnable, is_brand_archived

    if is_brand_archived(brand_id):
        print(f"ERROR: {brand_id} is archived and cannot generate or upload.")
        print("See brands/_archived/sixty_second_thrillers/README.md to resurrect.")
        sys.exit(2)
    assert_brand_runnable(brand_id)

    if do_upload:
        os.environ.setdefault("MPV2_PILOT_UPLOAD_CONFIRMED", "1")

    model = get_ollama_model()
    if not model:
        print("ERROR: ollama_model not set in config.json")
        sys.exit(1)
    select_model(model)

    summary = switch_brand(brand_id)
    print(f"Switched to: {summary['channel_name']}")
    for w in summary.get("warnings", []):
        print(f"  WARN: {w}")

    brand = load_active_brand()
    account = resolve_youtube_account(brand, create=True)
    if not account:
        print("ERROR: Could not resolve YouTube account for brand")
        sys.exit(1)

    print(f"Account: {account['nickname']} ({account['id']})")
    print(f"Voice: {brand.get('production', {}).get('elevenlabs_voice_id', 'global')}")
    print("Starting generation...")

    youtube = YouTube(
        account["id"],
        account["nickname"],
        account["firefox_profile"],
        account["niche"],
        account["language"],
    )
    trend_store = None
    trend_seed = None
    if trend_seed_id:
        from trend_store import TrendStore

        trend_store = TrendStore()
        trend_seed = trend_store.get_topic_seed(trend_seed_id)
        if trend_seed is None:
            print(f"ERROR: Unknown trend seed: {trend_seed_id}")
            sys.exit(2)
        youtube.use_topic_seed(trend_seed)
        print(f"Trend seed: {trend_seed.seed_id} ({trend_seed.historical_event})")
    if episode:
        youtube.episode_number = episode
        print(f"Episode: {episode}")
    if topic:
        youtube.subject = topic.strip()
        print(f"Topic: {youtube.subject}")
    tts = TTS()
    path = youtube.generate_video(tts, interactive=False)
    if trend_seed is not None and trend_store is not None:
        consumed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        trend_store.mark_seed_consumed(trend_seed.seed_id, youtube.run_id, consumed_at)
        attribution = dict(youtube.production_metadata.get("trend_attribution") or {})
        trend_store.save_attribution(
            seed_id=trend_seed.seed_id,
            opportunity_id=trend_seed.approval_record.opportunity_id,
            brand_id=trend_seed.brand_id,
            run_id=youtube.run_id,
            detected_at=trend_seed.detected_at,
            approved_at=trend_seed.approval_record.decided_at,
            status="generated",
            payload=attribution,
        )

    print("\n=== GENERATION COMPLETE ===")
    saved = getattr(youtube, "output_video_path", None) or path
    print(f"VIDEO: {saved}")
    if saved != path:
        print(f"TEMP:  {path}")
    print(f"TITLE: {youtube.metadata.get('title', '')}")
    print(f"DESCRIPTION (first 300 chars):\n{youtube.metadata.get('description', '')[:300]}")

    if sys.platform == "win32" and os.path.isfile(saved):
        print(f"\nOpen in your default player: start \"\" \"{saved}\"")

    if do_upload:
        from review_gate import should_proceed_with_upload

        if should_proceed_with_upload(
            youtube.video_path,
            youtube.metadata.get("title", ""),
            youtube.metadata.get("description", ""),
            interactive=False,
        ):
            ok = youtube.upload_video()
            print(f"UPLOAD: {'success' if ok else 'failed'}")
            if ok and getattr(youtube, "uploaded_video_url", None):
                print(f"URL: {youtube.uploaded_video_url}")
            if ok and trend_seed is not None and trend_store is not None:
                attribution = dict(youtube.production_metadata.get("trend_attribution") or {})
                trend_store.save_attribution(
                    seed_id=trend_seed.seed_id,
                    opportunity_id=trend_seed.approval_record.opportunity_id,
                    brand_id=trend_seed.brand_id,
                    run_id=youtube.run_id,
                    youtube_video_id=attribution.get("youtube_video_id", ""),
                    detected_at=trend_seed.detected_at,
                    approved_at=trend_seed.approval_record.decided_at,
                    publication_time=attribution.get("publication_time", ""),
                    status="uploaded",
                    payload=attribution,
                )
        else:
            print("UPLOAD: skipped")
    else:
        youtube.close_browser()
        print("(Upload skipped — pass --upload to upload automatically)")


if __name__ == "__main__":
    main()
