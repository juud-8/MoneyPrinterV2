#!/usr/bin/env python3
"""Non-interactive long-form generator for active or specified brand."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

from llm_provider import select_model
from config import get_ollama_model, get_longform_enabled
from brand_switcher import (
    switch_brand,
    resolve_youtube_account,
    load_active_brand,
    get_active_brand_id,
)
from classes.Tts import TTS
from classes.YouTube import YouTube
from run_lock import RunLockBusy, run_lock

# Shared with any other generation job — see run_lock for why overlapping runs
# corrupt each other through the .mp/ scratch directory.
LOCK_DIR = os.path.join(ROOT, ".mp", "locks")
LOCK_NAME = "generation"


def build_theme_preset(niche: str) -> dict | None:
    """Themed compilation subject from the back catalogue (see longform_theme)."""
    import json

    from longform_theme import build_theme_subject

    analytics_path = os.path.join(ROOT, ".mp", "analytics.json")
    if not os.path.isfile(analytics_path):
        print("ERROR: .mp/analytics.json not found — cannot build a theme")
        return None
    with open(analytics_path, encoding="utf-8") as handle:
        analytics = json.load(handle)
    used = {
        str(entry.get("longform_theme") or "")
        for entry in (analytics.get("videos") or [])
        if isinstance(entry, dict) and entry.get("longform_theme")
    }
    niche_key = "history" if "history" in (niche or "").lower() else (niche or "").split()[0]
    return build_theme_subject(analytics, niche_key, used_themes=used)


def build_theme_title(theme: dict) -> str:
    """A title describing the whole compilation, not one of its chapters."""
    from llm_provider import generate_text
    from longform_theme import fallback_theme_title

    chapters = "\n".join(f"- {title}" for title in theme["chapters"])
    prompt = (
        f"Write ONE YouTube title for a documentary compilation episode.\n"
        f"It covers {len(theme['chapters'])} separate true historical cases "
        f"linked by the theme '{theme['theme']}':\n{chapters}\n\n"
        "Rules: describe the COLLECTION, never a single case. Include the number "
        f"{len(theme['chapters'])}. Under 70 characters. No quotes, no emoji, no "
        "hashtags, no clickbait punctuation. Output only the title."
    )
    try:
        title = (generate_text(prompt, quality=True) or "").strip().strip('"').splitlines()[0]
    except Exception as error:  # noqa: BLE001 - a title must never fail the run
        print(f"  WARN: theme title generation failed ({error}); using fallback")
        return fallback_theme_title(theme)
    if not title or len(title) > 100:
        return fallback_theme_title(theme)
    return title


def main():
    # No brand argument falls back to whichever brand is active rather than a
    # hardcoded id — scheduled runs should pass their brand explicitly.
    brand_id = (
        sys.argv[1]
        if len(sys.argv) > 1 and not sys.argv[1].startswith("-")
        else get_active_brand_id()
    )
    if not brand_id:
        print("ERROR: no brand specified and no active brand set")
        sys.exit(1)
    do_upload = "--upload" in sys.argv
    # The shorts topic generator hunts for one novel incident and saturates once
    # the niche is well covered. --theme instead compiles already-researched
    # episodes into a chaptered subject, fed in as a preset topic.
    use_theme = "--theme" in sys.argv
    # Set by the scheduler wrapper. Mirrors cron.py: it stages a pilot brand's
    # upload as private for human review instead of the review gate refusing
    # to upload at all because nobody is at the keyboard to approve it.
    unattended = "--unattended" in sys.argv
    if unattended:
        os.environ["MPV2_UNATTENDED_UPLOAD"] = "1"
        os.environ["MPV2_RUN_TASK"] = "longform"

    # Exit 75 (EX_TEMPFAIL) so the wrapper can report "skipped, already
    # running" rather than treating a deliberate no-op as a crash.
    try:
        with run_lock(LOCK_NAME, LOCK_DIR):
            run(brand_id, do_upload, use_theme)
    except RunLockBusy as busy:
        print(f"SKIPPED: {busy}")
        sys.exit(75)


def run(brand_id: str, do_upload: bool, use_theme: bool):
    model = get_ollama_model()
    if not model:
        print("ERROR: ollama_model not set in config.json")
        sys.exit(1)
    select_model(model)

    summary = switch_brand(brand_id)
    print(f"Switched to: {summary['channel_name']}")
    for w in summary.get("warnings", []):
        print(f"  WARN: {w}")

    if not get_longform_enabled():
        print("ERROR: longform_enabled is false for this brand")
        sys.exit(1)

    brand = load_active_brand()
    account = resolve_youtube_account(brand, create=True)
    if not account:
        print("ERROR: Could not resolve YouTube account for brand")
        sys.exit(1)

    print(f"Account: {account['nickname']} ({account['id']})")
    print(f"Voice: {brand.get('production', {}).get('elevenlabs_voice_id', 'global')}")
    print("Starting long-form generation (this may take 30-60+ minutes)...")

    youtube = YouTube(
        account["id"],
        account["nickname"],
        account["firefox_profile"],
        account["niche"],
        account["language"],
    )
    if use_theme:
        theme = build_theme_preset(account["niche"])
        if not theme:
            # Exit 66 (EX_NOINPUT), not 1: on a schedule this is "no material
            # this week", which the wrapper logs as a skip. Every unused
            # cluster having been made already is a normal state, not a fault.
            print("SKIPPED: no unused theme with enough published episodes yet")
            sys.exit(66)
        print(f"Theme: {theme['theme']} ({len(theme['chapters'])} chapters)")
        for index, chapter in enumerate(theme["chapters"], 1):
            print(f"  {index}. {chapter}")
        # Preset subject: skips topic generation and the duplicate guard, but
        # generate_research() still runs, so the material stays grounded.
        youtube.subject = theme["subject"]
        # Recorded on the analytics row so build_theme_preset() can exclude this
        # cluster next time. Without it every --theme run re-picks the same
        # top-ranked theme and rebuilds the compilation it just made.
        youtube.longform_theme = theme["theme"]
        # Without this the title generator names the episode after whichever
        # single chapter it liked best, which both misdescribes a compilation
        # and collides with the short that chapter came from.
        title = build_theme_title(theme)
        if title:
            youtube.preset_title = title
            print(f"Title: {title}")

    tts = TTS()
    path = youtube.generate_longform_video(tts, interactive=False)

    print("\n=== LONG-FORM GENERATION COMPLETE ===")
    saved = getattr(youtube, "output_video_path", None) or path
    print(f"VIDEO: {saved}")
    if saved != path:
        print(f"TEMP:  {path}")
    thumb = getattr(youtube, "thumbnail_path", None)
    if thumb:
        print(f"THUMBNAIL: {thumb}")
    print(f"TITLE: {youtube.metadata.get('title', '')}")
    print(f"DESCRIPTION (first 500 chars):\n{youtube.metadata.get('description', '')[:500]}")

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
