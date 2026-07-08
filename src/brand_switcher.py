"""Brand switcher — multi-channel manifests with locked-in production settings."""

import glob
import json
import os
from uuid import uuid4

from cache import add_account, get_accounts, get_youtube_cache_path
from config import ROOT_DIR

BRANDS_DIR = os.path.join(ROOT_DIR, "brands")
ACTIVE_BRAND_PATH = os.path.join(ROOT_DIR, ".mp", "active_brand.json")
DEFAULT_BRAND_ID = "the_strange_archive"


def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _brand_files() -> list[str]:
    """
    Each brand lives in its own folder: brands/<brand_id>/manifest.json
    (plus any brand-specific assets/scripts alongside it).
    """
    return sorted(glob.glob(os.path.join(BRANDS_DIR, "*", "manifest.json")))


def _derive_brand_id(manifest: dict, filepath: str) -> str:
    if manifest.get("brand_id"):
        return manifest["brand_id"]
    return os.path.basename(os.path.dirname(filepath))


def load_brand(brand_id: str) -> dict | None:
    """Load a brand manifest by brand_id."""
    for path in _brand_files():
        manifest = _read_json(path)
        if _derive_brand_id(manifest, path) == brand_id:
            manifest["brand_id"] = _derive_brand_id(manifest, path)
            manifest["_config_path"] = path
            return manifest
    return None


def list_brands() -> list[dict]:
    """Return all brand manifests with validation status."""
    active_id = get_active_brand_id()
    results = []

    for path in _brand_files():
        manifest = _read_json(path)
        brand_id = _derive_brand_id(manifest, path)
        manifest["brand_id"] = brand_id

        profile = manifest.get("firefox_profile", "")
        production = manifest.get("production", {})
        voice_id = production.get("elevenlabs_voice_id", "")
        account = resolve_youtube_account(manifest, create=False)

        results.append(
            {
                "brand_id": brand_id,
                "channel_name": manifest.get("channel_name", brand_id),
                "channel_id": manifest.get("channel_id", ""),
                "niche": manifest.get("niche", ""),
                "is_active": brand_id == active_id,
                "profile_exists": bool(profile and os.path.isdir(profile)),
                "profile_path": profile,
                "voice_configured": bool(voice_id),
                "account_linked": account is not None,
                "account_id": account.get("id") if account else None,
                "manifest": manifest,
            }
        )

    return results


def get_active_brand_id() -> str:
    """Return the currently active brand_id."""
    if os.path.isfile(ACTIVE_BRAND_PATH):
        try:
            data = _read_json(ACTIVE_BRAND_PATH)
            brand_id = data.get("active_brand_id", "")
            if brand_id and load_brand(brand_id):
                return brand_id
        except Exception:
            pass

    try:
        from config import get_channel_config_file

        cfg_file = get_channel_config_file()
        if cfg_file:
            # New layout: brands/<brand_id>/manifest.json -> use the folder name.
            # Legacy layout: channel/<brand_id>.json -> use the file stem.
            if os.path.basename(cfg_file) == "manifest.json":
                candidate_id = os.path.basename(os.path.dirname(cfg_file))
            else:
                candidate_id = os.path.splitext(os.path.basename(cfg_file))[0]
            if load_brand(candidate_id):
                set_active_brand(candidate_id)
                return candidate_id
    except Exception:
        pass

    if load_brand(DEFAULT_BRAND_ID):
        return DEFAULT_BRAND_ID

    brands = _brand_files()
    if brands:
        manifest = _read_json(brands[0])
        return _derive_brand_id(manifest, brands[0])

    return DEFAULT_BRAND_ID


def set_active_brand(brand_id: str) -> None:
    """Persist active brand selection."""
    if not load_brand(brand_id):
        raise ValueError(f"Unknown brand: {brand_id}")
    _write_json(ACTIVE_BRAND_PATH, {"active_brand_id": brand_id})


def load_active_brand() -> dict:
    """Load the full manifest for the active brand."""
    brand_id = get_active_brand_id()
    brand = load_brand(brand_id)
    if not brand:
        raise RuntimeError(f"Active brand '{brand_id}' manifest not found.")
    return brand


def get_production_setting(key: str, default=None):
    """Read a production override from the active brand."""
    brand = load_active_brand()
    production = brand.get("production", {})
    if key in production and production[key] is not None:
        if production[key] != "" or key == "title_suffix":
            return production[key]
    return default


def get_effective_setting(key: str, default=None):
    """Brand production override with config.json fallback."""
    from config import get_script_sentence_length as cfg_script_len

    value = get_production_setting(key, None)
    if value is not None and value != "":
        return value

    if key == "elevenlabs_voice_id":
        with open(os.path.join(ROOT_DIR, "config.json"), "r", encoding="utf-8") as f:
            return json.load(f).get("elevenlabs_voice_id", default or "")
    if key == "script_sentence_length":
        return cfg_script_len()
    if key == "longform_enabled":
        return True
    if key in ("image_style_suffix", "title_suffix"):
        return default or ""

    return default


def is_longform_enabled(brand: dict | None = None) -> bool:
    brand = brand or load_active_brand()
    production = brand.get("production", {})
    if "longform_enabled" in production:
        return bool(production["longform_enabled"])
    return True


def _save_youtube_accounts(accounts: list) -> None:
    with open(get_youtube_cache_path(), "w", encoding="utf-8") as f:
        json.dump({"accounts": accounts}, f, indent=4)


def resolve_youtube_account(brand: dict, create: bool = True) -> dict | None:
    """Find YouTube cache account linked to this brand."""
    brand_id = brand.get("brand_id")
    channel_name = brand.get("channel_name", "")

    for account in get_accounts("youtube"):
        if account.get("brand_id") == brand_id:
            return account
        if channel_name and account.get("nickname") == channel_name:
            return account

    if create:
        return bootstrap_brand(brand_id)
    return None


def bootstrap_brand(brand_id: str) -> dict | None:
    """
    Link or create a YouTube account entry from the brand manifest.
    Syncs niche, profile, and language from manifest.
    """
    brand = load_brand(brand_id)
    if not brand:
        return None

    accounts = get_accounts("youtube")
    existing = None
    for account in accounts:
        if account.get("brand_id") == brand_id:
            existing = account
            break
        if account.get("nickname") == brand.get("channel_name"):
            existing = account
            break

    profile = brand.get("firefox_profile", "")
    payload = {
        "nickname": brand.get("channel_name", brand_id),
        "firefox_profile": profile,
        "niche": brand.get("niche", ""),
        "language": brand.get("language", "English"),
        "brand_id": brand_id,
    }

    if existing:
        existing.update(payload)
        _save_youtube_accounts(accounts)
        return existing

    new_account = {
        "id": str(uuid4()),
        "videos": [],
        **payload,
    }
    add_account("youtube", new_account)
    return new_account


def validate_brand(brand_id: str) -> list[str]:
    """Return list of warning messages for a brand."""
    brand = load_brand(brand_id)
    if not brand:
        return [f"Brand manifest not found: {brand_id}"]

    warnings = []
    profile = brand.get("firefox_profile", "")
    if not profile or not os.path.isdir(profile):
        warnings.append(f"Firefox profile missing or not found: {profile or '(empty)'}")

    voice = brand.get("production", {}).get("elevenlabs_voice_id", "")
    if not voice:
        warnings.append("ElevenLabs voice_id not set in production (falls back to global config)")

    if not resolve_youtube_account(brand, create=False):
        warnings.append("No linked YouTube account in cache (will bootstrap on switch)")

    return warnings


def switch_brand(brand_id: str) -> dict:
    """
    Switch active brand, bootstrap account link, return summary dict.
    """
    brand = load_brand(brand_id)
    if not brand:
        raise ValueError(f"Unknown brand: {brand_id}")

    set_active_brand(brand_id)
    account = bootstrap_brand(brand_id)
    warnings = validate_brand(brand_id)

    production = brand.get("production", {})
    return {
        "brand_id": brand_id,
        "channel_name": brand.get("channel_name", ""),
        "niche": brand.get("niche", ""),
        "firefox_profile": brand.get("firefox_profile", ""),
        "voice_id": production.get("elevenlabs_voice_id", "") or "(global fallback)",
        "account_id": account.get("id") if account else None,
        "warnings": warnings,
    }


def get_active_brand_summary() -> str:
    """One-line summary for startup banner."""
    brand = load_active_brand()
    return f"{brand.get('channel_name', brand.get('brand_id'))} ({brand.get('brand_id')})"
