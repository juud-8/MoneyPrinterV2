import os
import sys
import json

from termcolor import colored

ROOT_DIR = os.path.dirname(sys.path[0])

def assert_folder_structure() -> None:
    """
    Make sure that the nessecary folder structure is present.

    Returns:
        None
    """
    # Create the .mp folder
    if not os.path.exists(os.path.join(ROOT_DIR, ".mp")):
        if get_verbose():
            print(colored(f"=> Creating .mp folder at {os.path.join(ROOT_DIR, '.mp')}", "green"))
        os.makedirs(os.path.join(ROOT_DIR, ".mp"))

def get_first_time_running() -> bool:
    """
    Checks if the program is running for the first time by checking if .mp folder exists.

    Returns:
        exists (bool): True if the program is running for the first time, False otherwise
    """
    return not os.path.exists(os.path.join(ROOT_DIR, ".mp"))

def get_email_credentials() -> dict:
    """
    Gets the email credentials from the config file.

    Returns:
        credentials (dict): The email credentials
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file)["email"]

def get_verbose() -> bool:
    """
    Gets the verbose flag from the config file.

    Returns:
        verbose (bool): The verbose flag
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file)["verbose"]

def get_firefox_profile_path() -> str:
    """
    Gets the path to the Firefox profile.

    Returns:
        path (str): The path to the Firefox profile
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file)["firefox_profile"]

def get_headless() -> bool:
    """
    Gets the headless flag from the config file.

    Returns:
        headless (bool): The headless flag
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file)["headless"]

def get_ollama_base_url() -> str:
    """
    Gets the Ollama base URL.

    Returns:
        url (str): The Ollama base URL
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("ollama_base_url", "http://127.0.0.1:11434")

def get_ollama_model() -> str:
    """
    Gets the Ollama model name from the config file.

    Returns:
        model (str): The Ollama model name, or empty string if not set.
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("ollama_model", "")

def get_twitter_language() -> str:
    """
    Gets the Twitter language from the config file.

    Returns:
        language (str): The Twitter language
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file)["twitter_language"]

def get_nanobanana2_api_base_url() -> str:
    """
    Gets the Nano Banana 2 (Gemini image) API base URL.

    Returns:
        url (str): API base URL
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get(
            "nanobanana2_api_base_url",
            "https://generativelanguage.googleapis.com/v1beta",
        )

def get_nanobanana2_api_key() -> str:
    """
    Gets the Nano Banana 2 API key.

    Returns:
        key (str): API key
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        configured = json.load(file).get("nanobanana2_api_key", "")
        return configured or os.environ.get("GEMINI_API_KEY", "")

def get_nanobanana2_model() -> str:
    """
    Gets the Nano Banana 2 model name.

    Returns:
        model (str): Model name
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("nanobanana2_model", "gemini-3.1-flash-image-preview")

def get_nanobanana2_aspect_ratio() -> str:
    """
    Gets the aspect ratio for Nano Banana 2 image generation.

    Returns:
        ratio (str): Aspect ratio
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("nanobanana2_aspect_ratio", "9:16")

def get_threads() -> int:
    """
    Gets the amount of threads to use for example when writing to a file with MoviePy.

    Returns:
        threads (int): Amount of threads
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file)["threads"]
    
def get_zip_url() -> str:
    """
    Gets the URL to the zip file containing the songs.

    Returns:
        url (str): The URL to the zip file
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file)["zip_url"]

def get_is_for_kids() -> bool:
    """
    Gets the is for kids flag from the config file.

    Returns:
        is_for_kids (bool): The is for kids flag
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file)["is_for_kids"]

def get_google_maps_scraper_zip_url() -> str:
    """
    Gets the URL to the zip file containing the Google Maps scraper.

    Returns:
        url (str): The URL to the zip file
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file)["google_maps_scraper"]

def get_google_maps_scraper_niche() -> str:
    """
    Gets the niche for the Google Maps scraper.

    Returns:
        niche (str): The niche
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file)["google_maps_scraper_niche"]

def get_scraper_timeout() -> int:
    """
    Gets the timeout for the scraper.

    Returns:
        timeout (int): The timeout
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file)["scraper_timeout"] or 300

def get_outreach_message_subject() -> str:
    """
    Gets the outreach message subject.

    Returns:
        subject (str): The outreach message subject
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file)["outreach_message_subject"]
    
def get_outreach_message_body_file() -> str:
    """
    Gets the outreach message body file.

    Returns:
        file (str): The outreach message body file
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file)["outreach_message_body_file"]

def get_tts_voice() -> str:
    """
    Gets the TTS voice from the config file.

    Returns:
        voice (str): The TTS voice
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("tts_voice", "Jasper")

def get_assemblyai_api_key() -> str:
    """
    Gets the AssemblyAI API key.

    Returns:
        key (str): The AssemblyAI API key
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file)["assembly_ai_api_key"]

def get_stt_provider() -> str:
    """
    Gets the configured STT provider.

    Returns:
        provider (str): The STT provider
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("stt_provider", "local_whisper")

def get_whisper_model() -> str:
    """
    Gets the local Whisper model name.

    Returns:
        model (str): Whisper model name
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("whisper_model", "base")

def get_whisper_device() -> str:
    """
    Gets the target device for Whisper inference.

    Returns:
        device (str): Whisper device
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("whisper_device", "auto")

def get_whisper_compute_type() -> str:
    """
    Gets the compute type for Whisper inference.

    Returns:
        compute_type (str): Whisper compute type
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("whisper_compute_type", "int8")
    
def equalize_subtitles(srt_path: str, max_chars: int = 10) -> None:
    """
    Equalizes the subtitles in a SRT file.

    Args:
        srt_path (str): The path to the SRT file
        max_chars (int): The maximum amount of characters in a subtitle

    Returns:
        None
    """
    import srt_equalizer

    srt_equalizer.equalize_srt_file(srt_path, srt_path, max_chars)
    
def get_font() -> str:
    """
    Gets the font from the config file.

    Returns:
        font (str): The font
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file)["font"]

def get_fonts_dir() -> str:
    """
    Gets the fonts directory.

    Returns:
        dir (str): The fonts directory
    """
    return os.path.join(ROOT_DIR, "fonts")

def get_imagemagick_path() -> str:
    """
    Gets the path to ImageMagick.

    Returns:
        path (str): The path to ImageMagick
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file)["imagemagick_path"]

def get_script_sentence_length() -> int:
    """
    Gets the forced script's sentence length (brand override, then config).
    """
    try:
        from brand_switcher import get_production_setting

        val = get_production_setting("script_sentence_length", None)
        if val is not None:
            return int(val)
    except Exception:
        pass

    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        config_json = json.load(file)
        if config_json.get("script_sentence_length") is not None:
            return config_json["script_sentence_length"]
        return 4

def get_llm_provider() -> str:
    """Default LLM provider: ollama or gemini."""
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("llm_provider", "ollama").lower()


def get_quality_llm_provider() -> str:
    """LLM for hooks/scripts/titles — usually gemini for quality."""
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("quality_llm_provider", "gemini").lower()


def get_gemini_api_key() -> str:
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        cfg = json.load(file)
        return cfg.get("gemini_api_key", "") or cfg.get("nanobanana2_api_key", "") or os.environ.get("GEMINI_API_KEY", "")


def get_gemini_model() -> str:
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("gemini_model", "gemini-2.0-flash")


def get_youtube_api_key() -> str:
    """Google API key with YouTube Data API v3 enabled (public video stats).

    Falls back to the Gemini key since both are Google API keys — enabling
    the YouTube Data API on the existing key is the zero-extra-setup path.
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        cfg = json.load(file)
        return (
            cfg.get("youtube_api_key", "")
            or os.environ.get("YOUTUBE_API_KEY", "")
            or cfg.get("gemini_api_key", "")
            or cfg.get("nanobanana2_api_key", "")
            or os.environ.get("GEMINI_API_KEY", "")
        )


def get_audio_provider_settings(
    episode_audio: dict | None = None,
    cli_audio: dict | None = None,
):
    """Resolve narration provider settings with explicit, lossless precedence.

    Precedence is legacy/default <- global audio <- brand production.audio <-
    episode <- CLI. Existing callers pass no episode/CLI layer and retain the
    historical ``tts_provider`` default.
    """

    from media_providers.voicebox_settings import resolve_audio_provider_settings

    with open(os.path.join(ROOT_DIR, "config.json"), "r", encoding="utf-8") as file:
        config_json = json.load(file)
    brand_audio = None
    try:
        from brand_switcher import load_active_brand

        production = (load_active_brand() or {}).get("production", {})
        if isinstance(production, dict):
            brand_audio = production.get("audio")
    except Exception:
        # Standalone config tests and first-run setup may not have a brand yet.
        brand_audio = None
    return resolve_audio_provider_settings(
        legacy_provider=config_json.get("tts_provider", "kittentts"),
        global_audio=config_json.get("audio"),
        brand_audio=brand_audio,
        episode_audio=episode_audio,
        cli_audio=cli_audio,
    )


def get_tts_provider() -> str:
    return get_audio_provider_settings().provider


def get_elevenlabs_api_key() -> str:
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("elevenlabs_api_key", "") or os.environ.get("ELEVENLABS_API_KEY", "")


def get_elevenlabs_voice_id() -> str:
    try:
        from brand_switcher import get_production_setting

        val = get_production_setting("elevenlabs_voice_id", None)
        if val:
            return val
    except Exception:
        pass

    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("elevenlabs_voice_id", "")


def get_elevenlabs_model() -> str:
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("elevenlabs_model", "eleven_multilingual_v2")


def get_fishaudio_api_key() -> str:
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("fishaudio_api_key", "") or os.environ.get("FISH_AUDIO_API_KEY", "")


def get_fishaudio_voice_id() -> str:
    """Fish Audio voice model reference id (brand override, then config)."""
    try:
        from brand_switcher import get_production_setting

        val = get_production_setting("fishaudio_voice_id", None)
        if val:
            return val
    except Exception:
        pass

    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("fishaudio_voice_id", "")


def get_fishaudio_model() -> str:
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("fishaudio_model", "s2-pro")


def get_images_per_second() -> float:
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return float(json.load(file).get("images_per_second", 0.28))


def get_ken_burns_enabled() -> bool:
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return bool(json.load(file).get("ken_burns_enabled", True))


def get_crossfade_duration() -> float:
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return float(json.load(file).get("crossfade_duration", 0.4))


def get_word_captions_enabled() -> bool:
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return bool(json.load(file).get("word_captions_enabled", True))


def get_review_before_upload() -> bool:
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return bool(json.load(file).get("review_before_upload", True))


def get_channel_config_file() -> str:
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get(
            "channel_config_file", "brands/the_strange_archive/manifest.json"
        )


def get_channel_funnel_config() -> dict:
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("channel_funnel", {})


def get_premium_image_model() -> str:
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("premium_image_model", "gemini-3.1-flash-image-preview")


def get_longform_target_minutes() -> int:
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return int(json.load(file).get("longform_target_minutes", 8))


def get_longform_enabled() -> bool:
    try:
        from brand_switcher import is_longform_enabled

        return is_longform_enabled()
    except Exception:
        return True


def get_post_bridge_config() -> dict:
    """
    Gets the Post Bridge configuration with safe defaults.

    Returns:
        config (dict): Sanitized Post Bridge configuration
    """
    defaults = {
        "enabled": False,
        "api_key": "",
        "platforms": ["tiktok", "instagram"],
        "account_ids": [],
        "auto_crosspost": False,
    }
    supported_platforms = {"tiktok", "instagram"}

    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        config_json = json.load(file)

    raw_config = config_json.get("post_bridge", {})
    if not isinstance(raw_config, dict):
        raw_config = {}

    raw_platforms = raw_config.get("platforms")
    normalized_platforms = []
    seen_platforms = set()

    if raw_platforms is None:
        normalized_platforms = defaults["platforms"].copy()
    elif isinstance(raw_platforms, list):
        for platform in raw_platforms:
            normalized_platform = str(platform).strip().lower()
            if (
                normalized_platform in supported_platforms
                and normalized_platform not in seen_platforms
            ):
                normalized_platforms.append(normalized_platform)
                seen_platforms.add(normalized_platform)
    else:
        normalized_platforms = []

    raw_account_ids = raw_config.get("account_ids", defaults["account_ids"])
    normalized_account_ids = []
    if isinstance(raw_account_ids, list):
        for account_id in raw_account_ids:
            try:
                normalized_account_ids.append(int(account_id))
            except (TypeError, ValueError):
                continue

    api_key = str(raw_config.get("api_key", "")).strip()
    if not api_key:
        api_key = os.environ.get("POST_BRIDGE_API_KEY", "").strip()

    return {
        "enabled": bool(raw_config.get("enabled", defaults["enabled"])),
        "api_key": api_key,
        "platforms": normalized_platforms,
        "account_ids": normalized_account_ids,
        "auto_crosspost": bool(
            raw_config.get("auto_crosspost", defaults["auto_crosspost"])
        ),
    }


def get_fal_api_key() -> str:
    """
    Gets the fal.ai API key (used for premium video clip generation).

    Returns:
        key (str): API key, falling back to the FAL_KEY env var (fal's
            own SDK convention).
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        configured = json.load(file).get("fal_api_key", "")
        return configured or os.environ.get("FAL_KEY", "")


def get_standard_image_provider() -> str:
    """
    Provider for standard-tier still images: "gemini" (default) or "fal".

    Brands can override via `production.standard_image_provider`. "fal" routes
    standard shots to the cheaper fal.ai image model (`fal_image_model`) and
    falls back to Gemini on failure; premium_image always stays on Gemini.
    """
    try:
        from brand_switcher import get_production_setting

        val = get_production_setting("standard_image_provider", None)
        if val:
            return str(val).lower()
    except Exception:
        pass

    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("standard_image_provider", "gemini").lower()


def get_fal_image_model() -> str:
    """
    Gets the fal.ai model id used for standard-tier still images.

    Returns:
        model_id (str): e.g. "fal-ai/flux/schnell". Verify against fal.ai's
            current model catalog/pricing before changing.
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("fal_image_model", "fal-ai/flux/schnell")


def get_fal_video_model() -> str:
    """
    Gets the fal.ai model id used for premium video clip generation.

    Returns:
        model_id (str): e.g. "fal-ai/veo3.1". Verify against fal.ai's
            current model catalog/pricing before changing.
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("fal_video_model", "fal-ai/veo3.1")


def get_fal_video_resolution() -> str:
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return json.load(file).get("fal_video_resolution", "1080p")


def get_fal_video_poll_timeout() -> float:
    """Max seconds to wait for a fal.ai video generation job to complete."""
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return float(json.load(file).get("fal_video_poll_timeout_seconds", 240))


def get_premium_video_max_duration_seconds() -> float:
    """Cap on a single premium video clip's duration (cost control)."""
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return float(json.load(file).get("premium_video_max_duration_seconds", 6))


def get_ai_disclosure_default() -> bool:
    """
    Default for whether `upload_video()` should attempt to mark YouTube's
    'Altered or synthetic content' disclosure as Yes. Brands can override via
    `production.ai_disclosure`.

    Default is True: YouTube's own help docs state disclosing AI content has
    no monetization/reach downside, and AI-image/voice providers increasingly
    embed detectable provenance metadata (SynthID/C2PA) that YouTube's
    auto-detection can flag anyway — so proactively disclosing is the safer
    default for any brand built on this engine's AI pipeline.
    """
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return bool(json.load(file).get("ai_disclosure_default", True))


def get_asset_spend_alert_threshold_usd() -> float:
    """Weekly premium-asset spend (USD) above which the weekly review should
    surface a warning. Purely informational — does not block generation."""
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        return float(json.load(file).get("asset_spend_alert_threshold_usd", 25))


def get_archive_song_config() -> dict:
    """Return local/manual Archive Song settings with conservative defaults."""
    with open(os.path.join(ROOT_DIR, "config.json"), "r") as file:
        value = json.load(file).get("archive_song", {})
    return value if isinstance(value, dict) else {}


def get_archive_song_target_duration_seconds() -> float:
    return float(get_archive_song_config().get("target_duration_seconds", 60))


def get_archive_song_min_duration_seconds() -> float:
    return float(get_archive_song_config().get("min_duration_seconds", 55))


def get_archive_song_max_duration_seconds() -> float:
    return float(get_archive_song_config().get("max_duration_seconds", 65))
