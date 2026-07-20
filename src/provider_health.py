"""External provider readiness checks (API keys, quotas, credits)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import requests

from config import (
    get_elevenlabs_api_key,
    get_fal_api_key,
    get_gemini_api_key,
    get_nanobanana2_api_key,
    get_tts_provider,
)
from brand_switcher import get_production_setting, load_brand

# One Short narration is roughly 600–900 characters; block automation below this.
MIN_ELEVENLABS_CHARS_FOR_ONE_SHORT = 1000
# Pilot automation at 2 Shorts/day needs headroom for ~20 runs/month.
MIN_ELEVENLABS_CHARS_FOR_PILOT_AUTOMATION = 15000

YOUTUBE_AUDIO_LIBRARY_API = (
    "https://thibaultjanbeyer.github.io/YouTube-Free-Audio-Library-API/api.json"
)

PREFERRED_SONG_KEYWORDS = (
    "mysterious",
    "documentary",
    "ambient",
    "cinematic",
    "orchestral",
    "classical",
    "piano",
    "strings",
    "tension",
    "solemn",
    "histor",
    "archive",
    "enigma",
    "epic",
    "medieval",
    "ancient",
    "curious",
)

AVOID_SONG_KEYWORDS = (
    "dub",
    "dubstep",
    "step",
    "rock",
    "dance",
    "party",
    "hiphop",
    "hip_hop",
    "techno",
    "house",
    "metal",
    "trailer",
    "horror",
    "synthwave",
    "retrowave",
    "lofi",
    "chill_lofi",
)


def score_song_filename(name: str) -> int:
    """Score a track filename for weird_history / documentary mood."""
    lower = name.lower()
    score = 0
    for kw in PREFERRED_SONG_KEYWORDS:
        if kw in lower:
            score += 3
    for kw in AVOID_SONG_KEYWORDS:
        if kw in lower:
            score -= 8
    if lower.endswith(".mp3"):
        score += 1
    return score


@dataclass
class HealthIssue:
    level: str  # "fail" | "warn"
    message: str
    next_action: str = ""


def _gemini_key() -> str:
    return (
        get_gemini_api_key()
        or get_nanobanana2_api_key()
        or os.environ.get("GEMINI_API_KEY", "")
    )


def check_elevenlabs_quota(
    *,
    min_chars: int = MIN_ELEVENLABS_CHARS_FOR_ONE_SHORT,
) -> tuple[Optional[int], Optional[int], list[HealthIssue]]:
    """Return (remaining, limit, issues). remaining/limit are None if unknown."""
    issues: list[HealthIssue] = []
    api_key = get_elevenlabs_api_key()
    if not api_key:
        issues.append(
            HealthIssue(
                "fail",
                "ElevenLabs API key is not configured.",
                "Add elevenlabs_api_key to config.json or set ELEVENLABS_API_KEY.",
            )
        )
        return None, None, issues

    try:
        response = requests.get(
            "https://api.elevenlabs.io/v1/user/subscription",
            headers={"xi-api-key": api_key},
            timeout=8,
        )
        response.raise_for_status()
        sub = response.json()
    except Exception as exc:
        issues.append(
            HealthIssue(
                "warn",
                f"Could not check ElevenLabs subscription: {exc}",
                "Verify the API key at elevenlabs.io and retry.",
            )
        )
        return None, None, issues

    used = sub.get("character_count")
    limit = sub.get("character_limit")
    if used is None or limit is None:
        issues.append(
            HealthIssue(
                "warn",
                "Could not parse ElevenLabs quota from subscription response.",
            )
        )
        return None, None, issues

    remaining = int(limit) - int(used)
    if remaining < min_chars:
        issues.append(
            HealthIssue(
                "fail",
                f"ElevenLabs quota too low: {remaining} of {limit} character(s) remaining.",
                "Upgrade your ElevenLabs plan, wait for the monthly reset, or switch "
                "tts_provider to fishaudio with a cloned Archivist voice. Scheduled "
                "pilot runs will abort rather than fall back to KittenTTS.",
            )
        )
    elif remaining < MIN_ELEVENLABS_CHARS_FOR_PILOT_AUTOMATION:
        issues.append(
            HealthIssue(
                "warn",
                f"ElevenLabs quota is tight for daily automation: {remaining} of "
                f"{limit} character(s) remaining.",
                "Consider upgrading before running 2 Shorts/day on autopilot.",
            )
        )
    return remaining, int(limit), issues


def check_fal_credits(*, min_balance_usd: float = 5.0) -> list[HealthIssue]:
    issues: list[HealthIssue] = []
    api_key = get_fal_api_key()
    if not api_key:
        issues.append(
            HealthIssue(
                "warn",
                "fal.ai API key is not configured.",
                "Standard-tier images will fall back to Gemini when fal is selected.",
            )
        )
        return issues

    try:
        response = requests.get(
            "https://api.fal.ai/v1/account/billing",
            headers={"Authorization": f"Key {api_key}", "Accept": "application/json"},
            params={"expand": "credits"},
            timeout=8,
        )
        response.raise_for_status()
        body = response.json()
    except Exception as exc:
        issues.append(
            HealthIssue(
                "warn",
                f"Could not check fal.ai billing: {exc}",
                "Verify the key at fal.ai/dashboard/billing.",
            )
        )
        return issues

    credits = body.get("credits") or {}
    balance = credits.get("current_balance")
    currency = credits.get("currency") or "USD"
    if balance is None:
        issues.append(
            HealthIssue(
                "warn",
                "fal.ai billing response did not include a credit balance.",
            )
        )
        return issues

    balance = float(balance)
    if balance < min_balance_usd:
        issues.append(
            HealthIssue(
                "fail",
                f"fal.ai credit balance is low: {balance:.2f} {currency}.",
                "Add credits at fal.ai/dashboard/billing before daily automation.",
            )
        )
    return issues


def check_gemini_reachable() -> list[HealthIssue]:
    issues: list[HealthIssue] = []
    api_key = _gemini_key()
    if not api_key:
        issues.append(
            HealthIssue(
                "fail",
                "No Gemini API key configured for quality LLM / image fallback.",
                "Set gemini_api_key or nanobanana2_api_key in config.json.",
            )
        )
        return issues
    return issues


def count_songs(root_dir: str) -> int:
    songs_dir = os.path.join(root_dir, "Songs")
    if not os.path.isdir(songs_dir):
        return 0
    return len(
        [
            name
            for name in os.listdir(songs_dir)
            if os.path.isfile(os.path.join(songs_dir, name))
            and name.lower().endswith((".mp3", ".wav", ".m4a", ".aac", ".ogg"))
        ]
    )


def check_songs_library(
    root_dir: str,
    *,
    min_tracks: int = 15,
) -> list[HealthIssue]:
    issues: list[HealthIssue] = []
    songs_dir = os.path.join(root_dir, "Songs")
    if not os.path.isdir(songs_dir):
        issues.append(
            HealthIssue(
                "fail",
                "Songs/ directory does not exist.",
                "Run scripts/download_songs_library.py to seed licensed tracks.",
            )
        )
        return issues

    audio_files = [
        name
        for name in os.listdir(songs_dir)
        if os.path.isfile(os.path.join(songs_dir, name))
        and name.lower().endswith((".mp3", ".wav", ".m4a", ".aac", ".ogg"))
    ]
    if len(audio_files) < min_tracks:
        issues.append(
            HealthIssue(
                "fail",
                f"Songs/ has only {len(audio_files)} track(s) — need at least {min_tracks}.",
                "Run scripts/download_songs_library.py or add licensed tracks manually.",
            )
        )

    for name in audio_files:
        lower = name.lower()
        if any(kw in lower for kw in AVOID_SONG_KEYWORDS):
            issues.append(
                HealthIssue(
                    "warn",
                    f"Off-brand track filename in Songs/: {name}",
                    "Move it to Songs/_archived/ or replace with documentary/ambient tracks.",
                )
            )
    return issues


def check_firefox_profile_lock(profile_path: str) -> list[HealthIssue]:
    """Fail only when a running Firefox actually holds the profile lock.

    On Windows, parent.lock persists after Firefox exits — the lock is the
    exclusive file handle, not the file's existence. Removing the file is the
    real test: it succeeds for a stale leftover and raises PermissionError
    while Firefox holds it open.
    """
    issues: list[HealthIssue] = []
    if not profile_path:
        return issues
    lock_path = os.path.join(profile_path, "parent.lock")
    if not os.path.isfile(lock_path):
        return issues
    try:
        os.remove(lock_path)
    except FileNotFoundError:
        pass
    except PermissionError:
        issues.append(
            HealthIssue(
                "fail",
                "Firefox is currently running with the automation profile "
                "(parent.lock is held open).",
                "Close all Firefox windows using the mpv2 profile before automated upload.",
            )
        )
    except OSError as exc:
        issues.append(
            HealthIssue(
                "warn",
                f"Could not probe the automation profile's parent.lock: {exc}",
                "If Firefox fails to start during upload, delete the file manually.",
            )
        )
    return issues


def assert_pilot_providers_ready(
    brand_id: str,
    root_dir: str,
    *,
    skip_elevenlabs: bool = False,
    skip_songs: bool = False,
    skip_fal: bool = False,
    skip_firefox_lock: bool = False,
) -> None:
    """Raise RuntimeError when a pilot-brand scheduled run should not proceed."""
    brand = load_brand(brand_id) or {}
    production = brand.get("production") or {}
    if not production.get("pilot_mode"):
        return

    failures: list[HealthIssue] = []
    warnings: list[HealthIssue] = []

    tts_provider = get_tts_provider().lower()
    if tts_provider == "elevenlabs" and not skip_elevenlabs:
        min_chars = MIN_ELEVENLABS_CHARS_FOR_PILOT_AUTOMATION
        _, _, el_issues = check_elevenlabs_quota(min_chars=min_chars)
        for issue in el_issues:
            (failures if issue.level == "fail" else warnings).append(issue)
    elif tts_provider == "fishaudio":
        from config import get_fishaudio_api_key, get_fishaudio_voice_id

        if not get_fishaudio_api_key() or not get_fishaudio_voice_id():
            voice_id = get_production_setting("fishaudio_voice_id", "") or get_fishaudio_voice_id()
            if not get_fishaudio_api_key() or not voice_id:
                failures.append(
                    HealthIssue(
                        "fail",
                        "tts_provider=fishaudio but API key or voice id is missing.",
                        "Complete Fish Audio setup — see brands/the_strange_archive/FISH_AUDIO_SETUP.md.",
                    )
                )

    if not skip_fal:
        for issue in check_fal_credits():
            (failures if issue.level == "fail" else warnings).append(issue)

    for issue in check_gemini_reachable():
        (failures if issue.level == "fail" else warnings).append(issue)

    if not skip_songs:
        for issue in check_songs_library(root_dir, min_tracks=15):
            (failures if issue.level == "fail" else warnings).append(issue)

    if not skip_firefox_lock:
        profile = brand.get("firefox_profile") or ""
        for issue in check_firefox_profile_lock(profile):
            (failures if issue.level == "fail" else warnings).append(issue)

    for issue in warnings:
        from status import warning

        warning(issue.message)
        if issue.next_action:
            warning(issue.next_action)

    if failures:
        lines = [issue.message for issue in failures]
        actions = [issue.next_action for issue in failures if issue.next_action]
        detail = "; ".join(lines)
        if actions:
            detail += " Next: " + " | ".join(actions)
        raise RuntimeError(detail)


def collect_provider_health(root_dir: str, *, brand_id: str = "the_strange_archive") -> dict:
    """Aggregate health snapshot for CLI / preflight."""
    brand = load_brand(brand_id) or {}
    remaining, limit, el_issues = check_elevenlabs_quota(
        min_chars=MIN_ELEVENLABS_CHARS_FOR_PILOT_AUTOMATION
    )
    issues = list(el_issues)
    issues.extend(check_fal_credits())
    issues.extend(check_gemini_reachable())
    issues.extend(check_songs_library(root_dir, min_tracks=15))
    issues.extend(check_firefox_profile_lock(brand.get("firefox_profile") or ""))

    return {
        "elevenlabs_remaining": remaining,
        "elevenlabs_limit": limit,
        "songs_count": count_songs(root_dir),
        "issues": issues,
        "blocking_failures": [i for i in issues if i.level == "fail"],
        "warnings": [i for i in issues if i.level == "warn"],
    }
