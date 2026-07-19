"""Evaluate edge-tts as a cheapest TTS fallback (offline-safe by default).

Without ``--live``, only checks import + voice config. With ``--live``,
synthesizes a short sample (network call to Microsoft Edge TTS; no publish).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

SAMPLE = (
    "In 1518, records from Strasbourg described a dancing outbreak that lasted "
    "for weeks, though later retellings often exaggerate what the sources prove."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate edge-tts fallback rung")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Actually call Edge TTS (network). Default is import/config only.",
    )
    parser.add_argument("--voice", default="", help="Override edge_tts voice id")
    args = parser.parse_args(argv)

    report: dict = {
        "provider": "edge_tts",
        "role": "cheapest best-effort fallback (not brand primary)",
        "tos_risk": "unofficial Microsoft Edge protocol",
        "import_ok": False,
        "voice": None,
        "live_ran": False,
        "output_path": None,
        "errors": [],
    }
    try:
        import edge_tts  # noqa: F401

        report["import_ok"] = True
    except ImportError as exc:
        report["errors"].append(f"pip install edge-tts required: {exc}")
        print(json.dumps(report, indent=2))
        return 2

    from config import get_edge_tts_voice

    voice = args.voice.strip() or get_edge_tts_voice()
    report["voice"] = voice

    if not args.live:
        report["recommendation"] = (
            "Wire as audio.provider=edge_tts or fallback_provider=edge_tts after "
            "a --live sample sounds acceptable for non-primary drafts."
        )
        print(json.dumps(report, indent=2))
        return 0

    try:
        from classes.Tts import TTS
        from media_providers.voicebox_settings import resolve_audio_provider_settings

        # Build TTS with explicit edge_tts without rewriting config.json.
        tts = TTS(cli_audio={"provider": "edge_tts", "allow_fallback": False})
        # Force provider in case legacy config wins oddly
        tts._provider = "edge_tts"
        tts._audio_settings = resolve_audio_provider_settings(
            legacy_provider="edge_tts",
            cli_audio={"provider": "edge_tts", "allow_fallback": False},
        )
        out = Path(tempfile.gettempdir()) / "mpv2_edge_tts_eval.mp3"
        path = tts._synthesize_edge_tts(SAMPLE, str(out))
        report["live_ran"] = True
        report["output_path"] = path
        report["last_model_used"] = tts.last_model_used
    except Exception as exc:
        report["errors"].append(str(exc))
        print(json.dumps(report, indent=2))
        return 1

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
