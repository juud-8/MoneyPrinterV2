#!/usr/bin/env python3
"""Non-interactive Short generator for active or specified brand."""
import argparse
import os
import sys
import uuid
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

from llm_provider import select_model
from config import get_ollama_model
from brand_switcher import switch_brand, resolve_youtube_account, load_active_brand
from classes.Tts import TTS
from classes.YouTube import YouTube
from archive_song import (
    ArchiveSongError,
    AwaitingSongAudio,
    normalize_audio_mode,
)
from pipeline_stage import emit_stage
from trend_models import ValidationError


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _handle_trend_generation_failure(
    store, seed, claim_id: str, error: Exception, failed_at: str, *, stage: str = "pre_production",
) -> str:
    """Release proven local failures; quarantine failures with uncertain side effects."""
    classification = str(getattr(error, "trend_failure_class", "")).lower()
    retryable_local = stage == "pre_production" and (
        classification == "pre_production" or isinstance(
            error, (ValidationError, FileNotFoundError, ModuleNotFoundError, ImportError)
        )
    )
    if retryable_local:
        reason = f"retryable_pre_production: {type(error).__name__}"
        if not store.release_topic_seed(seed.seed_id, claim_id, failed_at, reason):
            raise RuntimeError("Trend seed claim was lost before retryable release") from error
        return "released_retryable"
    if classification == "terminal":
        reason = f"terminal: {type(error).__name__}"
    else:
        reason = f"uncertain_external_side_effect: {type(error).__name__}"
    if not store.fail_topic_seed(seed.seed_id, claim_id, failed_at, reason):
        raise RuntimeError("Trend seed claim was lost before failure quarantine") from error
    return "failed_terminal" if classification == "terminal" else "failed_uncertain"


def _fail_trend_claim(store, seed, claim_id, error, youtube) -> None:
    """Hand a claimed seed back when generation ends without consuming it."""
    if seed is None or store is None or not claim_id:
        return
    _handle_trend_generation_failure(
        store,
        seed,
        claim_id,
        error,
        _utc_now(),
        stage=str(getattr(youtube, "trend_generation_stage", "pre_production")),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a branded YouTube Short. Archive Song mode creates a manual "
            "Suno package, pauses, and resumes after operator-supplied audio."
        )
    )
    parser.add_argument("brand_id", nargs="?", default="the_strange_archive")
    parser.add_argument("--upload", action="store_true", help="upload after review gates")
    parser.add_argument(
        "--publish-at",
        metavar="WHEN",
        help=(
            "schedule the upload to go public at this local time "
            "(e.g. 2026-07-21T18:30). Implies --upload; requires "
            'upload_backend: "api" in config.json'
        ),
    )
    parser.add_argument("--episode", help="stable episode id/number (recommended for resume)")
    parser.add_argument("--topic", help="operator-selected historical topic")
    parser.add_argument(
        "--trend-seed",
        metavar="SEED_ID",
        help="generate from an approved trend seed (mutually exclusive with --topic)",
    )
    parser.add_argument(
        "--audio-mode",
        default="narration",
        metavar="MODE",
        help="narration (default) or archive-song",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="resume a checkpointed Archive Song episode after adding audio",
    )
    parser.add_argument(
        "--song-audio",
        help="explicit WAV/MP3 to import into the Archive Song episode directory",
    )
    parser.add_argument(
        "--regenerate-song-package",
        action="store_true",
        help="regenerate package from checkpointed approved research/script",
    )
    parser.add_argument(
        "--skip-song-validation",
        action="store_true",
        help="allow duration warnings only; format and decode checks still apply",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    brand_id = args.brand_id
    do_upload = args.upload or bool(args.publish_at)
    episode = args.episode
    topic = args.topic
    trend_seed_id = args.trend_seed

    if trend_seed_id and topic:
        print("ERROR: --trend-seed and --topic are mutually exclusive")
        return 2

    publish_at = ""
    if args.publish_at:
        from config import get_upload_backend
        from youtube_api_upload import normalize_publish_at

        try:
            publish_at = normalize_publish_at(args.publish_at)
        except ValueError as exc:
            build_parser().error(str(exc))
        if get_upload_backend() != "api":
            print(
                'ERROR: --publish-at requires upload_backend: "api" in config.json '
                "(the Selenium Studio wizard cannot schedule)."
            )
            return 2
        print(f"Scheduled publish time: {args.publish_at} (UTC: {publish_at})")
    try:
        audio_mode = normalize_audio_mode(args.audio_mode)
    except ValueError as exc:
        build_parser().error(str(exc))

    from archived_brands import assert_brand_runnable, is_brand_archived

    if is_brand_archived(brand_id):
        print(f"ERROR: {brand_id} is archived and cannot generate or upload.")
        print("See brands/_archived/sixty_second_thrillers/README.md to resurrect.")
        return 2
    assert_brand_runnable(brand_id)

    if do_upload:
        os.environ.setdefault("MPV2_PILOT_UPLOAD_CONFIRMED", "1")

    model = get_ollama_model()
    if not model:
        print("ERROR: ollama_model not set in config.json")
        return 1
    select_model(model)

    summary = switch_brand(brand_id)
    print(f"Switched to: {summary['channel_name']}")
    for w in summary.get("warnings", []):
        print(f"  WARN: {w}")

    brand = load_active_brand()
    account = resolve_youtube_account(brand, create=True)
    if not account:
        print("ERROR: Could not resolve YouTube account for brand")
        return 1

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
    trend_claim_id = None
    if trend_seed_id:
        from trend_store import TrendStore

        trend_store = TrendStore()
        trend_seed = trend_store.get_topic_seed(trend_seed_id)
        if trend_seed is None:
            print(f"ERROR: Unknown trend seed: {trend_seed_id}")
            return 2
        youtube.use_topic_seed(trend_seed)
        trend_claim_id = f"generation-{uuid.uuid4().hex}"
        if not trend_store.claim_topic_seed(trend_seed.seed_id, trend_claim_id, _utc_now()):
            print(f"ERROR: Trend seed is already claimed, completed, or failed: {trend_seed_id}")
            return 2
        print(f"Trend seed: {trend_seed.seed_id} ({trend_seed.historical_event})")

    if episode:
        youtube.episode_number = episode
        youtube.archive_song_episode_id = episode
        print(f"Episode: {episode}")
    if topic:
        youtube.subject = topic.strip()
        print(f"Topic: {youtube.subject}")
    youtube.publish_at = publish_at
    youtube.audio_mode = audio_mode
    youtube.archive_song_resume = args.resume
    youtube.archive_song_audio_path = args.song_audio or ""
    youtube.regenerate_song_package = args.regenerate_song_package
    youtube.skip_song_validation = args.skip_song_validation
    tts = TTS()
    try:
        path = youtube.generate_video(tts, interactive=False)
    except AwaitingSongAudio as pause:
        # A pause, not a failure: nothing rendered or published, so the seed is
        # provably untouched and goes straight back on the queue for the resume.
        if trend_seed is not None and trend_store is not None and trend_claim_id:
            if not trend_store.release_topic_seed(
                trend_seed.seed_id, trend_claim_id, _utc_now(), "paused_awaiting_song_audio"
            ):
                raise RuntimeError("Trend seed claim was lost before pause release") from pause
        print("\n=== ARCHIVE SONG PAUSED ===")
        print("STATUS: awaiting_song_audio")
        print(f"EPISODE_DIR: {pause.episode_dir}")
        print("Place song.wav, song.mp3, archive_song.wav, or archive_song.mp3 there.")
        print(f"RESUME: {pause.resume_command}")
        youtube.close_browser()
        return 0
    except ArchiveSongError as exc:
        _fail_trend_claim(trend_store, trend_seed, trend_claim_id, exc, youtube)
        print(f"ERROR: {exc}")
        emit_stage("done", status="failed")
        youtube.close_browser()
        return 2
    except Exception as error:
        _fail_trend_claim(trend_store, trend_seed, trend_claim_id, error, youtube)
        raise

    if trend_seed is not None and trend_store is not None:
        if not trend_store.complete_topic_seed(
            trend_seed.seed_id, trend_claim_id, _utc_now(), run_id=youtube.run_id
        ):
            raise RuntimeError("Trend seed claim was lost before generation completion")
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
            if publish_at:
                print(f"UPLOAD: {'scheduled' if ok else 'failed'}"
                      + (f" (goes public at {publish_at} UTC)" if ok else ""))
            else:
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
            if ok:
                try:
                    from post_bridge_integration import maybe_crosspost_youtube_short

                    crosspost_result = maybe_crosspost_youtube_short(
                        video_path=youtube.video_path,
                        title=youtube.metadata.get("title", ""),
                        interactive=False,
                        youtube_privacy_status=getattr(
                            youtube, "uploaded_privacy_status", ""
                        ),
                    )
                    if crosspost_result is True:
                        print("POST BRIDGE: cross-posted")
                    elif crosspost_result is False:
                        print("POST BRIDGE: cross-post failed (see warnings above)")
                except Exception as exc:
                    print(f"POST BRIDGE: error ({type(exc).__name__}: {exc})")
            emit_stage("done", status="success" if ok else "failed")
        else:
            print("UPLOAD: skipped")
            emit_stage("done", status="skipped")
    else:
        youtube.close_browser()
        print("(Upload skipped — pass --upload to upload automatically)")
        emit_stage("done", status="success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
