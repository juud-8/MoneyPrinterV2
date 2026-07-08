#!/usr/bin/env python3
import json
import os
import sys
from typing import Tuple

import requests


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT_DIR, "config.json")


def ok(msg: str) -> None:
    print(f"[PASS] {msg}")


def warn(msg: str, next_action: str = None) -> None:
    print(f"[WARN] {msg}")
    if next_action:
        print(f"       Next action: {next_action}")


def fail(msg: str, next_action: str = None) -> None:
    print(f"[FAIL] {msg}")
    if next_action:
        print(f"       Next action: {next_action}")


def check_url(url: str, timeout: int = 3) -> Tuple[bool, str]:
    try:
        response = requests.get(url, timeout=timeout)
        return True, f"HTTP {response.status_code}"
    except Exception as exc:
        return False, str(exc)


def _find_default_install_profile_path(profiles_ini_text: str) -> str:
    """Return the relative profile Path pinned as the OS-level default for this
    Firefox install (the ``Default=`` line inside an ``[InstallXXXX]`` section
    of profiles.ini), or "" if none is set.

    When a profile is pinned this way, *any* plain Firefox launch (a desktop
    shortcut, Windows autostart, double-click, etc.) opens that exact profile.
    If that profile is also one Selenium drives via ``-profile <path>``, the
    two will fight over the same profile lock and every automated upload will
    fail with a WebDriverException ("unexpectedly closed with status 0").
    """
    current_section = None
    for line in profiles_ini_text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            current_section = line
            continue
        if current_section and current_section.startswith("[Install") and line.startswith("Default="):
            return line.split("=", 1)[1].strip()
    return ""


def main() -> int:
    if not os.path.exists(CONFIG_PATH):
        fail(f"Missing config file: {CONFIG_PATH}")
        return 1

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    failures = 0

    stt_provider = str(cfg.get("stt_provider", "local_whisper")).lower()

    ok(f"stt_provider={stt_provider}")

    imagemagick_path = cfg.get("imagemagick_path", "")
    if imagemagick_path and os.path.exists(imagemagick_path):
        ok(f"imagemagick_path exists: {imagemagick_path}")
    else:
        warn(
            "imagemagick_path is not set to a valid executable path. "
            "MoviePy subtitle rendering may fail."
        )

    firefox_profile = cfg.get("firefox_profile", "")
    if firefox_profile:
        if os.path.isdir(firefox_profile):
            ok(f"firefox_profile exists: {firefox_profile}")
        else:
            warn(f"firefox_profile does not exist: {firefox_profile}")
    else:
        warn("firefox_profile is empty. Twitter/YouTube automation requires this.")

    # Ollama (LLM)
    base = str(cfg.get("ollama_base_url", "http://127.0.0.1:11434")).rstrip("/")
    reachable, detail = check_url(f"{base}/api/tags")
    if not reachable:
        fail(f"Ollama is not reachable at {base}: {detail}")
        failures += 1
    else:
        ok(f"Ollama reachable at {base}")
        try:
            tags = requests.get(f"{base}/api/tags", timeout=5).json()
            models = [m.get("name") for m in tags.get("models", [])]
            if models:
                ok(f"Ollama models available: {', '.join(models[:10])}")
            else:
                warn("No models found on Ollama. Pull a model first (e.g. 'ollama pull llama3.2:3b').")
        except Exception as exc:
            warn(f"Could not validate Ollama model list: {exc}")

    # Nano Banana 2 (image generation)
    api_key = cfg.get("nanobanana2_api_key", "") or os.environ.get("GEMINI_API_KEY", "")
    nb2_base = str(
        cfg.get(
            "nanobanana2_api_base_url",
            "https://generativelanguage.googleapis.com/v1beta",
        )
    ).rstrip("/")
    if api_key:
        ok("nanobanana2_api_key is set")
    else:
        fail("nanobanana2_api_key is empty (and GEMINI_API_KEY is not set)")
        failures += 1

    reachable, detail = check_url(nb2_base, timeout=8)
    if not reachable:
        warn(f"Nano Banana 2 base URL could not be reached: {detail}")
    else:
        ok(f"Nano Banana 2 base URL reachable: {nb2_base}")

    if stt_provider == "local_whisper":
        try:
            import faster_whisper  # noqa: F401

            ok("faster-whisper is installed")
        except Exception as exc:
            fail(f"faster-whisper is not importable: {exc}")
            failures += 1

    if failures:
        print("")
        print(f"Preflight completed with {failures} blocking issue(s).")
        return 1

    tts_provider = str(cfg.get("tts_provider", "kittentts")).lower()
    if tts_provider == "elevenlabs":
        el_key = cfg.get("elevenlabs_api_key", "") or os.environ.get("ELEVENLABS_API_KEY", "")
        voice_id = cfg.get("elevenlabs_voice_id", "")
        if el_key and voice_id:
            ok("elevenlabs_api_key and voice_id are set")
        else:
            warn("tts_provider=elevenlabs but api key or voice_id missing (falls back to KittenTTS)")

        # A script-worth of narration is roughly 600-900 characters. ElevenLabs
        # returns quota-exhaustion as a plain 401 (indistinguishable from a bad
        # key/voice in the logs) once the monthly character allowance runs out,
        # so surface remaining quota here instead of discovering it mid-run.
        if el_key:
            MIN_CHARS_FOR_ONE_SCRIPT = 1000
            try:
                sub = requests.get(
                    "https://api.elevenlabs.io/v1/user/subscription",
                    headers={"xi-api-key": el_key},
                    timeout=8,
                ).json()
                used = sub.get("character_count")
                limit = sub.get("character_limit")
                if used is not None and limit is not None:
                    remaining = limit - used
                    if remaining < MIN_CHARS_FOR_ONE_SCRIPT:
                        warn(
                            f"ElevenLabs quota is nearly exhausted: {remaining} of "
                            f"{limit} character(s) remaining this cycle.",
                            "Every synthesis call will 401 and silently fall back "
                            "to KittenTTS until the monthly reset, or upgrade the "
                            "ElevenLabs plan for daily-automation volume.",
                        )
                    else:
                        ok(f"ElevenLabs quota: {remaining} of {limit} character(s) remaining")
                else:
                    warn(f"Could not parse ElevenLabs subscription response: {sub}")
            except Exception as exc:
                warn(f"Could not check ElevenLabs quota: {exc}")

    quality_llm = str(cfg.get("quality_llm_provider", "gemini")).lower()
    if quality_llm == "gemini":
        gemini_key = (
            cfg.get("gemini_api_key", "")
            or cfg.get("nanobanana2_api_key", "")
            or os.environ.get("GEMINI_API_KEY", "")
        )
        if gemini_key:
            ok("Gemini key available for quality LLM")
        else:
            warn("quality_llm_provider=gemini but no Gemini API key configured")

    # Songs/ background music library — shared across brands, not brand-specific.
    songs_dir = os.path.join(ROOT_DIR, "Songs")
    AUDIO_EXTENSIONS = (".mp3", ".wav", ".m4a", ".aac", ".ogg")
    UNSAFE_FILENAME_KEYWORDS = (
        "royalty_free",
        "free_music",
        "zip",
        "horror",
        "synthwave",
        "trailer",
    )
    if not os.path.isdir(songs_dir):
        warn(
            "Songs/ directory does not exist yet.",
            "It will be auto-created on the next run — populate it with 15+ "
            "licensed tracks before relying on daily automation.",
        )
    else:
        audio_files = [
            name
            for name in os.listdir(songs_dir)
            if os.path.isfile(os.path.join(songs_dir, name))
            and name.lower().endswith(AUDIO_EXTENSIONS)
        ]
        if len(audio_files) >= 15:
            ok(f"Songs/ has {len(audio_files)} licensed track(s) (>= 15 minimum)")
        else:
            warn(
                f"Songs/ has only {len(audio_files)} track(s) — below the "
                "15-track pilot minimum.",
                "Add more licensed tracks (YouTube Audio Library or a "
                "channel-safelisted paid library) to Songs/ — see "
                "brands/the_strange_archive/ASSETS_CHECKLIST.md.",
            )

        flagged = [
            name
            for name in audio_files
            if any(kw in name.lower() for kw in UNSAFE_FILENAME_KEYWORDS)
        ]
        if flagged:
            warn(
                f"{len(flagged)} track filename(s) look generic/unsafe: {', '.join(flagged)}",
                "Verify licensing and rename/remove — avoid bulk 'royalty-free' "
                "zips or mismatched-mood filenames (e.g. horror/synthwave/trailer "
                "tracks on a documentary-history channel).",
            )
        elif audio_files:
            ok("No generic/unsafe-looking track filenames detected in Songs/")

    zip_url = cfg.get("zip_url", "")
    if not zip_url:
        ok('zip_url is disabled ("")')
    else:
        warn(
            f"zip_url is set to a value: {zip_url}",
            "Pilot brands should curate Songs/ manually — clear zip_url unless "
            "the bulk-download fallback is intentional.",
        )

    if cfg.get("ai_disclosure_default", False) is True:
        ok("ai_disclosure_default is true")
    else:
        warn(
            "ai_disclosure_default is not true in config.json.",
            'Set "ai_disclosure_default": true unless you have a specific reason not to.',
        )

    channel_cfg = cfg.get("channel_config_file", "brands/the_strange_archive/manifest.json")
    channel_path = channel_cfg if os.path.isabs(channel_cfg) else os.path.join(ROOT_DIR, channel_cfg)
    if os.path.isfile(channel_path):
        ok(f"default brand manifest found: {channel_cfg}")
    else:
        warn(f"default brand manifest not found: {channel_cfg}")

    sys.path.insert(0, os.path.join(ROOT_DIR, "src"))
    try:
        from brand_switcher import get_active_brand_summary, list_brands

        ok(f"Active brand: {get_active_brand_summary()}")
        print("")
        print("Brand manifests:")
        brands = list_brands()
        for b in brands:
            is_healthy = b["profile_exists"] and b["account_linked"]
            voice_note = "" if b["voice_configured"] else ", voice: global fallback"
            active = " [ACTIVE]" if b["is_active"] else ""
            line = (
                f"{b['channel_name']} ({b['brand_id']}){active} — "
                f"profile={'yes' if b['profile_exists'] else 'MISSING'}, "
                f"account={'linked' if b['account_linked'] else 'not linked'}{voice_note}"
            )
            if is_healthy:
                ok(line)
            else:
                warn(line)

        print("")
        print("Firefox automation-profile safety:")
        if sys.platform.startswith("win"):
            profiles_ini_path = os.path.join(
                os.environ.get("APPDATA", ""), "Mozilla", "Firefox", "profiles.ini"
            )
            default_install_profile = ""
            if os.path.isfile(profiles_ini_path):
                try:
                    with open(profiles_ini_path, "r", encoding="utf-8") as f:
                        default_install_profile = _find_default_install_profile_path(f.read())
                except Exception as exc:
                    warn(f"Could not read Firefox profiles.ini: {exc}")
            else:
                warn(f"Firefox profiles.ini not found at {profiles_ini_path}")

            if default_install_profile:
                default_profile_name = os.path.basename(
                    default_install_profile.rstrip("/\\")
                )
                matching = [
                    b
                    for b in brands
                    if default_profile_name
                    and (
                        b["manifest"].get("firefox_profile_name") == default_profile_name
                        or os.path.basename((b.get("profile_path") or "").rstrip("/\\"))
                        == default_profile_name
                    )
                ]
                if matching:
                    names = ", ".join(
                        f"{b['channel_name']} ({b['brand_id']})" for b in matching
                    )
                    fail(
                        f"Firefox's OS-level default profile is an automation "
                        f"profile ('{default_profile_name}'), used by: {names}",
                        "Open Firefox -> about:profiles -> click 'Set as default "
                        "profile' on a normal/personal profile instead. Otherwise "
                        "Windows autostart or any plain Firefox launch will lock "
                        "this profile, and automated uploads will fail with "
                        "WebDriverException: 'unexpectedly closed with status 0'.",
                    )
                    failures += 1
                else:
                    ok(
                        "Firefox's OS-level default profile "
                        f"('{default_profile_name}') is not an mpv2 automation profile"
                    )
            else:
                ok("No Firefox install-level default profile override detected")

            for b in brands:
                profile_path = b.get("profile_path") or ""
                if profile_path and os.path.isdir(profile_path):
                    lock_path = os.path.join(profile_path, "parent.lock")
                    if os.path.isfile(lock_path):
                        warn(
                            f"{b['channel_name']} ({b['brand_id']}): a Firefox "
                            "'parent.lock' file is present in its profile.",
                            "Firefox may currently be open with this profile — "
                            "close all Firefox windows using it before running "
                            "an automated upload, or the run will fail with a "
                            "WebDriverException.",
                        )
        else:
            ok("Skipping Windows-specific Firefox profile-lock checks (non-Windows OS)")

        print("")
        print("Pilot-mode brand readiness:")
        any_pilot = False
        for b in brands:
            manifest = b.get("manifest", {}) or {}
            production = manifest.get("production", {}) or {}
            if not production.get("pilot_mode"):
                continue
            any_pilot = True
            label = f"{b['channel_name']} ({b['brand_id']})"

            if production.get("ai_disclosure") is True:
                ok(f"{label}: production.ai_disclosure is true")
            else:
                warn(
                    f"{label}: production.ai_disclosure is not true",
                    "Set production.ai_disclosure: true in the brand manifest.",
                )

            publishing = manifest.get("publishing", {}) or {}
            brand_review = publishing.get("review_before_upload", True)
            global_review = bool(cfg.get("review_before_upload", True))
            if brand_review and global_review:
                ok(f"{label}: review_before_upload is true (config.json and manifest)")
            else:
                fail(
                    f"{label}: pilot_mode is true but review_before_upload is not "
                    "true everywhere (config.json and/or manifest.publishing)",
                    "Set review_before_upload: true in both config.json and this "
                    "brand's manifest.publishing block before running any "
                    "-Upload/--upload path.",
                )
                failures += 1

            if b["profile_exists"]:
                ok(f"{label}: firefox_profile exists")
            else:
                warn(
                    f"{label}: firefox_profile is missing or not found "
                    f"({manifest.get('firefox_profile') or '(empty)'})",
                    "Create/verify the dedicated Firefox profile for this brand.",
                )

            if production.get("elevenlabs_voice_id"):
                ok(f"{label}: elevenlabs_voice_id is set")
            else:
                warn(
                    f"{label}: production.elevenlabs_voice_id is empty",
                    "Set a dedicated ElevenLabs voice_id for this brand's persona.",
                )

            font_name = cfg.get("font", "")
            font_path = os.path.join(ROOT_DIR, "fonts", font_name) if font_name else ""
            if font_name and os.path.isfile(font_path):
                ok(f"{label}: caption font exists (fonts/{font_name})")
            elif font_name:
                warn(
                    f"{label}: configured font not found: fonts/{font_name}",
                    'Add the .ttf to fonts/ or update config.json\'s "font" value.',
                )
            else:
                warn(f"{label}: config.json has no font configured")

            # Branded asset pack (all warn-only; assets are optional overlays/
            # templates, and the outro is opt-in via production.outro_clip).
            assets_dir = os.path.join(ROOT_DIR, "brands", b["brand_id"], "assets")
            ASSET_PACK_FILES = (
                "file_stamp_overlay.png",
                "hook_card_template.png",
                "thumbnail_template.png",
                "end_screen_card.png",
            )
            if os.path.isdir(assets_dir):
                missing = [
                    name
                    for name in ASSET_PACK_FILES
                    if not os.path.isfile(os.path.join(assets_dir, name))
                ]
                if not missing:
                    ok(f"{label}: branded asset pack present (brands/{b['brand_id']}/assets/)")
                else:
                    warn(
                        f"{label}: asset pack incomplete — missing: {', '.join(missing)}",
                        "Regenerate with scripts/create_strange_archive_assets.py "
                        "(or add replacements) — see the assets/ README.md.",
                    )
                outro_file = os.path.join(assets_dir, "outro.mp4")
                if os.path.isfile(outro_file):
                    ok(f"{label}: outro.mp4 exists in assets/")
                else:
                    warn(
                        f"{label}: brands/{b['brand_id']}/assets/outro.mp4 is missing",
                        "Generate it with scripts/create_strange_archive_outro.py "
                        "(optional — videos render fine without an outro).",
                    )
            else:
                warn(
                    f"{label}: no assets/ directory at brands/{b['brand_id']}/assets/",
                    "Create it and generate the asset pack with "
                    "scripts/create_strange_archive_assets.py.",
                )

            outro_clip = production.get("outro_clip", "") or ""
            if not outro_clip:
                warn(
                    f"{label}: no outro configured (optional)",
                    "Optional — add brands/<brand_id>/assets/outro.mp4 and set "
                    "production.outro_clip/outro_duration_seconds when ready.",
                )
            else:
                outro_path = (
                    outro_clip
                    if os.path.isabs(outro_clip)
                    else os.path.join(ROOT_DIR, outro_clip)
                )
                if os.path.isfile(outro_path):
                    ok(f"{label}: outro configured and file exists ({outro_clip})")
                else:
                    warn(
                        f"{label}: outro_clip is set but file not found: {outro_clip}",
                        "Add the outro file, or clear outro_clip/outro_duration_seconds.",
                    )

        if not any_pilot:
            print("(No brands currently have pilot_mode enabled.)")
    except Exception as exc:
        warn(f"Brand switcher check failed: {exc}")

    print("")
    if failures:
        print(f"Preflight completed with {failures} blocking issue(s).")
        return 1
    print("Preflight passed. Local setup looks ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
