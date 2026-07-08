"""Asset generation — stills and short video clips, across quality tiers.

Tiers:
  - "standard": today's default — a still image from Nano Banana 2 (Gemini)
    or, when `standard_image_provider` is "fal", a cheaper fal.ai image model
    (FLUX schnell by default) with Gemini as the failure fallback.
  - "premium_image": a stronger still-image call (same provider, premium
    model — e.g. for thumbnails or a hero frame).
  - "premium_video": a short AI-generated video clip via fal.ai (defaults to
    Google Veo 3.1). Meant to be used selectively on high-leverage shots
    (e.g. a Short's opening hook), not on every shot in a video — both for
    cost reasons and because most shots don't need motion to land.

Every generator returns an `AssetResult` (path, modality, tier, cost
estimate, provider) so callers can log spend and degrade gracefully:
`generate_asset_with_fallback()` tries the requested tier and falls back
down the chain (premium_video -> premium_image -> standard) on failure or
timeout, so a slow/flaky premium provider can never block a whole run.
"""

import base64
import os
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import requests

from config import (
    ROOT_DIR,
    get_fal_api_key,
    get_fal_image_model,
    get_fal_video_model,
    get_fal_video_poll_timeout,
    get_fal_video_resolution,
    get_nanobanana2_api_base_url,
    get_nanobanana2_api_key,
    get_nanobanana2_aspect_ratio,
    get_nanobanana2_model,
    get_premium_image_model,
    get_premium_video_max_duration_seconds,
    get_standard_image_provider,
    get_verbose,
)
from status import info, warning

# Planning-only cost estimates for budget/analytics visibility — these are
# not a billing source of truth. Verify against fal.ai's current pricing
# page before relying on them for anything financial.
FAL_VIDEO_PRICE_PER_SECOND_USD = {
    "fal-ai/veo3.1": 0.20,
    "fal-ai/veo3.1/fast": 0.10,
}
DEFAULT_FAL_VIDEO_PRICE_PER_SECOND_USD = 0.20

FAL_IMAGE_PRICE_PER_IMAGE_USD = {
    "fal-ai/flux/schnell": 0.003,
    "fal-ai/flux/dev": 0.025,
}
DEFAULT_FAL_IMAGE_PRICE_PER_IMAGE_USD = 0.01

# fal FLUX models take explicit pixel sizes, not raw ratios like Gemini does.
# Request full output resolution (fal rounds to multiples of 16) — the preset
# names ("portrait_16_9" etc.) only return ~576x1024, which would get
# upscaled ~2x in the final 1080x1920 composite.
FAL_IMAGE_SIZE_BY_ASPECT_RATIO = {
    "9:16": {"width": 1080, "height": 1920},
    "16:9": {"width": 1920, "height": 1080},
    "1:1": {"width": 1080, "height": 1080},
    "3:4": {"width": 1080, "height": 1440},
    "4:3": {"width": 1440, "height": 1080},
}
DEFAULT_FAL_IMAGE_SIZE = {"width": 1080, "height": 1920}


@dataclass
class AssetResult:
    path: str
    modality: str  # "image" | "video_clip"
    tier: str  # "standard" | "premium_image" | "premium_video"
    provider: str = ""
    cost_usd: float = 0.0


def _persist_bytes(data: bytes, suffix: str) -> str:
    path = os.path.join(ROOT_DIR, ".mp", f"{uuid.uuid4()}{suffix}")
    with open(path, "wb") as f:
        f.write(data)
    return path


# --- Still images (Gemini / "Nano Banana 2") -------------------------------


def _generate_via_gemini(
    prompt: str,
    model: str,
    aspect_ratio: str,
    *,
    max_retries: int = 6,
) -> Optional[bytes]:
    api_key = get_nanobanana2_api_key()
    if not api_key:
        return None

    base_url = get_nanobanana2_api_base_url().rstrip("/")
    endpoint = f"{base_url}/models/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": aspect_ratio},
        },
    }

    for attempt in range(max_retries):
        try:
            response = requests.post(
                endpoint,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=payload,
                timeout=300,
            )
            if response.status_code == 429:
                wait = min(90, 10 * (2**attempt))
                warning(
                    f"Gemini image rate limited (429, {model}); "
                    f"retry {attempt + 1}/{max_retries} in {wait}s."
                )
                time.sleep(wait)
                continue
            response.raise_for_status()
            body = response.json()

            for candidate in body.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    inline = part.get("inlineData") or part.get("inline_data")
                    if not inline:
                        continue
                    data = inline.get("data")
                    mime = inline.get("mimeType") or inline.get("mime_type", "")
                    if data and str(mime).startswith("image/"):
                        return base64.b64decode(data)
            return None
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 429 and attempt < max_retries - 1:
                wait = min(90, 10 * (2**attempt))
                warning(
                    f"Gemini image rate limited (429, {model}); "
                    f"retry {attempt + 1}/{max_retries} in {wait}s."
                )
                time.sleep(wait)
                continue
            raise
    return None


def _generate_via_fal_image(prompt: str, model: str, aspect_ratio: str) -> Optional[bytes]:
    api_key = get_fal_api_key()
    if not api_key:
        return None

    payload = {
        "prompt": prompt,
        "image_size": FAL_IMAGE_SIZE_BY_ASPECT_RATIO.get(aspect_ratio, DEFAULT_FAL_IMAGE_SIZE),
        "num_images": 1,
    }
    response = requests.post(
        f"https://fal.run/{model}",
        headers={"Authorization": f"Key {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    images = response.json().get("images") or []
    image_url = images[0].get("url") if images else None
    if not image_url:
        return None

    image_response = requests.get(image_url, timeout=120)
    image_response.raise_for_status()
    return image_response.content


def generate_image(
    prompt: str,
    aspect_ratio: Optional[str] = None,
    use_premium: bool = False,
) -> Optional[AssetResult]:
    """Generate a still image; use the premium image model when flagged.

    Standard tier honors `standard_image_provider`: "fal" tries the cheap
    fal.ai image model first and falls back to Gemini on failure. Premium
    always uses the Gemini premium model.
    """
    ratio = aspect_ratio or get_nanobanana2_aspect_ratio()
    tier = "premium_image" if use_premium else "standard"

    if not use_premium and get_standard_image_provider() == "fal":
        fal_model = get_fal_image_model()
        try:
            image_bytes = _generate_via_fal_image(prompt, fal_model, ratio)
            if image_bytes:
                path = _persist_bytes(image_bytes, ".png")
                if get_verbose():
                    info(f' => Wrote {tier} image ({fal_model}) to "{path}"')
                cost = FAL_IMAGE_PRICE_PER_IMAGE_USD.get(
                    fal_model, DEFAULT_FAL_IMAGE_PRICE_PER_IMAGE_USD
                )
                return AssetResult(
                    path=path,
                    modality="image",
                    tier=tier,
                    provider=f"fal:{fal_model}",
                    cost_usd=cost,
                )
            warning(f"fal image generation returned nothing ({fal_model}); falling back to Gemini.")
        except Exception as e:
            warning(f"fal image generation failed ({fal_model}): {e}; falling back to Gemini.")

    model = get_premium_image_model() if use_premium else get_nanobanana2_model()
    # Premium has a guaranteed fallback (standard tier), so don't burn the
    # full 429-backoff budget on it — when Gemini quota is exhausted, each
    # throttled request can take minutes to even return, and 6 attempts can
    # stall a run for half an hour before the fallback kicks in.
    retries = 2 if use_premium else 6
    try:
        image_bytes = _generate_via_gemini(prompt, model, ratio, max_retries=retries)
        if image_bytes:
            path = _persist_bytes(image_bytes, ".png")
            if get_verbose():
                info(f' => Wrote {tier} image ({model}) to "{path}"')
            return AssetResult(path=path, modality="image", tier=tier, provider=f"gemini:{model}")
    except Exception as e:
        warning(f"Image generation failed ({model}): {e}")
    return None


# --- Video clips (fal.ai) ---------------------------------------------------


def estimate_fal_video_cost(model: str, duration_seconds: float) -> float:
    """Rough per-call cost estimate for budget/analytics logging only."""
    rate = FAL_VIDEO_PRICE_PER_SECOND_USD.get(model, DEFAULT_FAL_VIDEO_PRICE_PER_SECOND_USD)
    return round(rate * duration_seconds, 2)


def _fal_headers(api_key: str) -> dict:
    return {"Authorization": f"Key {api_key}", "Content-Type": "application/json"}


def _fal_submit(model_id: str, payload: dict, api_key: str) -> dict:
    response = requests.post(
        f"https://queue.fal.run/{model_id}",
        headers=_fal_headers(api_key),
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _fal_poll(status_url: str, api_key: str, timeout: float, poll_interval: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    last_status: dict = {}
    while time.monotonic() < deadline:
        response = requests.get(status_url, headers=_fal_headers(api_key), timeout=30)
        response.raise_for_status()
        last_status = response.json()
        status = last_status.get("status")
        if status in ("COMPLETED", "FAILED", "CANCELLED", "ERROR"):
            return last_status
        time.sleep(poll_interval)
    last_status["status"] = last_status.get("status", "TIMEOUT")
    return last_status


def _fal_fetch_result(response_url: str, api_key: str) -> dict:
    response = requests.get(response_url, headers=_fal_headers(api_key), timeout=60)
    response.raise_for_status()
    return response.json()


def generate_video_clip(
    prompt: str,
    duration_seconds: float = 5.0,
    aspect_ratio: Optional[str] = None,
    model: Optional[str] = None,
) -> Optional[AssetResult]:
    """
    Generate a short video clip via fal.ai (defaults to Google Veo 3.1).

    Returns None on any failure/timeout — callers should fall back to a
    cheaper tier rather than treat this as fatal.
    """
    api_key = get_fal_api_key()
    if not api_key:
        warning("fal_api_key (or FAL_KEY env var) is not configured; skipping premium video.")
        return None

    model = model or get_fal_video_model()
    duration_seconds = min(float(duration_seconds), float(get_premium_video_max_duration_seconds()))
    ratio = aspect_ratio or get_nanobanana2_aspect_ratio()

    payload = {
        "prompt": prompt,
        "aspect_ratio": ratio,
        "duration": f"{int(round(duration_seconds))}s",
        "resolution": get_fal_video_resolution(),
        "generate_audio": False,  # our own pipeline supplies voiceover + music
    }

    try:
        submission = _fal_submit(model, payload, api_key)
        status_url = submission.get("status_url")
        response_url = submission.get("response_url")
        if not status_url or not response_url:
            warning(f"fal.ai submission missing status/response URL: {submission}")
            return None

        if get_verbose():
            info(f" => Submitted premium video clip to fal.ai ({model}): {submission.get('request_id')}")

        status = _fal_poll(status_url, api_key, timeout=get_fal_video_poll_timeout())
        if status.get("status") != "COMPLETED":
            warning(f"fal.ai video generation did not complete in time: {status.get('status')}")
            return None

        result = _fal_fetch_result(response_url, api_key)
        video_url = (result.get("video") or {}).get("url")
        if not video_url:
            warning(f"fal.ai result missing a video URL: {result}")
            return None

        video_response = requests.get(video_url, timeout=120)
        video_response.raise_for_status()
        path = _persist_bytes(video_response.content, ".mp4")
        cost = estimate_fal_video_cost(model, duration_seconds)

        if get_verbose():
            info(f' => Wrote premium video clip ({model}, ~${cost:.2f}) to "{path}"')

        return AssetResult(
            path=path,
            modality="video_clip",
            tier="premium_video",
            provider=f"fal:{model}",
            cost_usd=cost,
        )
    except Exception as e:
        warning(f"Premium video generation failed ({model}): {e}")
        return None


# --- Tiered generation with automatic fallback ------------------------------


def generate_asset_with_fallback(
    prompt: str,
    tier: str,
    *,
    aspect_ratio: Optional[str] = None,
    video_duration_seconds: float = 5.0,
) -> AssetResult:
    """
    Try the requested tier; fall back down the chain
    (premium_video -> premium_image -> standard) on failure so a slow or
    flaky premium provider never blocks a whole video.

    Raises RuntimeError only if every tier (including standard) fails.
    """
    if tier == "premium_video":
        result = generate_video_clip(
            prompt, duration_seconds=video_duration_seconds, aspect_ratio=aspect_ratio
        )
        if result:
            return result
        warning("Premium video unavailable/failed — falling back to premium image.")
        tier = "premium_image"

    if tier == "premium_image":
        result = generate_image(prompt, aspect_ratio=aspect_ratio, use_premium=True)
        if result:
            return result
        warning("Premium image failed — falling back to standard image.")
        tier = "standard"

    result = generate_image(prompt, aspect_ratio=aspect_ratio, use_premium=False)
    if not result:
        raise RuntimeError(f"All asset generation tiers failed for prompt: {prompt[:80]!r}")
    return result
