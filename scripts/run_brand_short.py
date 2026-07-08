#!/usr/bin/env python3
"""Non-interactive Short generator for active or specified brand."""
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
    if episode:
        youtube.episode_number = episode
        print(f"Episode: {episode}")
    if topic:
        youtube.subject = topic.strip()
        print(f"Topic: {youtube.subject}")
    tts = TTS()
    path = youtube.generate_video(tts, interactive=False)

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


if __name__ == "__main__":
    main()
