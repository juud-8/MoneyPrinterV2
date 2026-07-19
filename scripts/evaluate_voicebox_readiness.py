"""Offline Voicebox comparison readiness check (no paid APIs, no publish).

Runs before / instead of a live ``test_voicebox_narration.py`` call when the
local Voicebox service is not yet installed. Prints a machine-readable
summary so the Voicebox eval todo can complete without inventing audio.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def _check_config() -> dict:
    from config import get_audio_provider_settings

    try:
        settings = get_audio_provider_settings()
    except Exception as exc:
        return {
            "ok": False,
            "provider": None,
            "allow_fallback": None,
            "profile_set": False,
            "error": str(exc),
        }
    return {
        "ok": True,
        "provider": settings.provider,
        "allow_fallback": settings.allow_fallback,
        "profile_set": bool(settings.voicebox.profile.strip()),
        "base_url": settings.voicebox.base_url,
        "error": None,
    }


def _check_health(base_url: str) -> dict:
    url = base_url.rstrip("/") + "/health"
    try:
        with urlopen(url, timeout=2.0) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {"reachable": True, "status_code": response.status, "body": body[:500]}
    except URLError as exc:
        return {"reachable": False, "error": str(exc.reason if hasattr(exc, "reason") else exc)}
    except Exception as exc:
        return {"reachable": False, "error": str(exc)}


def main() -> int:
    cfg = _check_config()
    report = {
        "comparison_script": "scripts/test_voicebox_narration.py",
        "config": cfg,
        "ready_for_live_comparison": False,
        "blocking_reasons": [],
        "next_operator_steps": [],
    }
    if not cfg.get("ok"):
        report["blocking_reasons"].append(f"config_error: {cfg.get('error')}")
    else:
        if cfg["provider"] != "voicebox":
            report["blocking_reasons"].append(
                "Set audio.provider to 'voicebox' in config.json for comparison."
            )
        if cfg.get("allow_fallback"):
            report["blocking_reasons"].append(
                "Set audio.allow_fallback to false so comparison cannot call paid TTS."
            )
        if not cfg.get("profile_set"):
            report["blocking_reasons"].append(
                "Set audio.voicebox.profile to a local Voicebox profile name/id."
            )
        health = _check_health(cfg.get("base_url") or "http://127.0.0.1:17493")
        report["health"] = health
        if not health.get("reachable"):
            report["blocking_reasons"].append(
                "Voicebox /health not reachable — install/start Voicebox 0.5.x locally."
            )

    report["ready_for_live_comparison"] = not report["blocking_reasons"]
    if report["ready_for_live_comparison"]:
        report["next_operator_steps"] = [
            (
                'python scripts/test_voicebox_narration.py --seed 42 '
                '--output-anchor .mp/voicebox_comparison.wav'
            ),
            "Compare production_audio against an ElevenLabs sample of the same text.",
            "Decide whether voicebox becomes the brand default narration provider.",
        ]
    else:
        report["next_operator_steps"] = [
            "Install Voicebox 0.5.x and download a model (see docs/VOICEBOX_INTEGRATION.md).",
            "Configure audio.provider=voicebox, allow_fallback=false, voicebox.profile=...",
            "Re-run: python scripts/evaluate_voicebox_readiness.py",
            "When ready: python scripts/test_voicebox_narration.py",
        ]

    print(json.dumps(report, indent=2))
    return 0 if report["ready_for_live_comparison"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
