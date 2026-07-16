#!/usr/bin/env python3
"""Non-interactive Short generator for active or specified brand."""
import argparse
import os
import sys

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a branded YouTube Short. Archive Song mode creates a manual "
            "Suno package, pauses, and resumes after operator-supplied audio."
        )
    )
    parser.add_argument("brand_id", nargs="?", default="the_strange_archive")
    parser.add_argument("--upload", action="store_true", help="upload after review gates")
    parser.add_argument("--episode", help="stable episode id/number (recommended for resume)")
    parser.add_argument("--topic", help="operator-selected historical topic")
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
    do_upload = args.upload
    episode = args.episode
    topic = args.topic
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
    if episode:
        youtube.episode_number = episode
        youtube.archive_song_episode_id = episode
        print(f"Episode: {episode}")
    if topic:
        youtube.subject = topic.strip()
        print(f"Topic: {youtube.subject}")
    youtube.audio_mode = audio_mode
    youtube.archive_song_resume = args.resume
    youtube.archive_song_audio_path = args.song_audio or ""
    youtube.regenerate_song_package = args.regenerate_song_package
    youtube.skip_song_validation = args.skip_song_validation
    tts = TTS()
    try:
        path = youtube.generate_video(tts, interactive=False)
    except AwaitingSongAudio as pause:
        print("\n=== ARCHIVE SONG PAUSED ===")
        print("STATUS: awaiting_song_audio")
        print(f"EPISODE_DIR: {pause.episode_dir}")
        print("Place song.wav, song.mp3, archive_song.wav, or archive_song.mp3 there.")
        print(f"RESUME: {pause.resume_command}")
        youtube.close_browser()
        return 0
    except ArchiveSongError as exc:
        print(f"ERROR: {exc}")
        youtube.close_browser()
        return 2

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
        else:
            print("UPLOAD: skipped")
    else:
        youtube.close_browser()
        print("(Upload skipped — pass --upload to upload automatically)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
