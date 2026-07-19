"""Generate one local Voicebox narration without rendering or publishing.

This operator-only comparison tool refuses legacy/remote fallback providers.
It is not invoked by automated validation because it performs local inference.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from config import get_audio_provider_settings
from media_providers.contracts import GenerationRequest
from media_providers.voicebox_provider import build_voicebox_provider


DEFAULT_TEXT = (
    "In 1518, records from Strasbourg described a dancing outbreak that lasted "
    "for weeks, though later retellings often exaggerate what the sources prove."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one non-publishing narration through the configured local Voicebox service."
        )
    )
    text_source = parser.add_mutually_exclusive_group()
    text_source.add_argument("--text", default=None, help="UTF-8 narration text")
    text_source.add_argument(
        "--text-file", help="UTF-8 text file containing the narration sample"
    )
    parser.add_argument(
        "--output-anchor",
        default=str(ROOT_DIR / ".mp" / "voicebox_comparison.wav"),
        help="Anchor path; artifacts are written under its sibling narration directory",
    )
    parser.add_argument("--seed", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_audio_provider_settings()
    if settings.provider != "voicebox":
        raise SystemExit(
            "Refusing comparison: set audio.provider to 'voicebox' in config.json first."
        )
    if settings.allow_fallback:
        raise SystemExit(
            "Refusing comparison while audio.allow_fallback is true. Disable fallback so "
            "this command cannot call ElevenLabs or Fish Audio."
        )
    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8")
    else:
        text = args.text if args.text is not None else DEFAULT_TEXT
    provider = build_voicebox_provider(settings.voicebox)
    result = provider.generate(
        GenerationRequest(
            content=text,
            output_path=os.path.abspath(args.output_anchor),
            seed=args.seed,
            fallback_behavior="disabled",
            metadata={"operator_comparison": True, "publishing": False},
        )
    )
    print(f"production_audio={result.output_path}")
    print(f"request_hash={result.provenance.request_hash}")
    print(f"source_sha256={result.provenance.source_artifact_hash}")
    print(f"production_sha256={result.provenance.derived_artifact_hash}")
    print("publishing=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
