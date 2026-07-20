#!/usr/bin/env python3
"""Generate a two-host radio-show long-form episode and stage it for review.

Stages into output/<brand_id>/radio/<date>_<slug>/:
    script.md   - the generated dialogue
    show.wav    - multi-speaker Gemini TTS audio
    show.mp4    - 1080p video bed (brand card + waveform) with the audio
    NOTES.md    - review checklist

This script NEVER uploads. Long-form publishing stays a manual decision
(the brand manifest's longform_enabled / longform_per_week govern cadence).
"""
import argparse
import datetime
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import radio_show
from archived_brands import is_brand_archived
from brand_switcher import load_brand
from llm_provider import generate_text


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:60] or "episode"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a radio-show longform episode for review only (no upload)."
    )
    parser.add_argument("brand_id", nargs="?", default="the_strange_archive")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--minutes", type=int, default=15)
    parser.add_argument(
        "--source",
        help="path to research/source text the script must stay faithful to "
        "(e.g. a NotebookLM report export)",
    )
    parser.add_argument("--script", help="reuse an existing script.md (skip LLM)")
    parser.add_argument("--tts-model", default="", help="override Gemini TTS model id")
    parser.add_argument("--bed", help="bed art override (default: brand outro clip frame)")
    parser.add_argument("--audio-only", action="store_true", help="skip the video bed")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if is_brand_archived(args.brand_id):
        print(f"ERROR: {args.brand_id} is archived.")
        return 2
    brand = load_brand(args.brand_id)
    if not brand:
        print(f"ERROR: unknown brand: {args.brand_id}")
        return 2
    production = brand.get("production", {})

    episode_dir = os.path.join(
        ROOT, "output", args.brand_id, "radio",
        f"{datetime.date.today().isoformat()}_{slugify(args.topic)}",
    )
    os.makedirs(episode_dir, exist_ok=True)
    print(f"Radio show: '{args.topic}' [{args.brand_id}] ~{args.minutes} min - review-only.")

    script_path = os.path.join(episode_dir, "script.md")
    if args.script:
        with open(args.script, encoding="utf-8") as f:
            script = f.read()
    else:
        source_text = ""
        if args.source:
            with open(args.source, encoding="utf-8") as f:
                source_text = f.read()[:30_000]
        print(" => Writing script (quality LLM)...")
        script = generate_text(
            radio_show.build_show_prompt(
                args.topic,
                brand.get("persona", {}),
                args.minutes,
                source_text=source_text,
                sign_off=brand.get("persona", {}).get("sign_off", ""),
            ),
            quality=True,
        )
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script)
    line_count = len(radio_show.parse_dialogue(script))
    if line_count < 6:
        print(f"ERROR: script only has {line_count} dialogue lines; aborting before TTS.")
        return 1
    print(f"    {line_count} dialogue lines.")

    print(" => Synthesizing multi-speaker audio...")
    voices = production.get("radio_voices") or radio_show.DEFAULT_VOICES
    wav_path, duration = radio_show.synthesize_show(
        script,
        voices=voices,
        model=args.tts_model or production.get("gemini_tts_model", ""),
        wav_path=os.path.join(episode_dir, "show.wav"),
    )
    print(f"    show.wav: {duration / 60:.1f} min")

    video_path = None
    if not args.audio_only:
        bed = args.bed or production.get("radio_bed") or production.get("outro_clip")
        if bed and not os.path.isabs(bed):
            bed = os.path.join(ROOT, bed)
        if not bed or not os.path.isfile(bed):
            print("    (no bed art found; skipping video bed)")
        else:
            print(" => Rendering video bed (brand card + waveform)...")
            video_path = os.path.join(episode_dir, "show.mp4")
            cmd = radio_show.build_bed_command(
                bed, wav_path, video_path,
                waveform_color=brand.get("color_palette", {}).get("accent", "#C9A66B"),
            )
            result = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
            )
            if result.returncode != 0:
                print(f"    bed render failed (audio still staged): {result.stderr[-400:]}")
                video_path = None

    with open(os.path.join(episode_dir, "NOTES.md"), "w", encoding="utf-8") as f:
        f.write(
            f"# Radio show: {args.topic}\n\n"
            f"- Brand: {args.brand_id}\n"
            f"- Duration: {duration / 60:.1f} min\n"
            f"- Voices: {voices}\n"
            f"- Generated: {datetime.datetime.now().isoformat(timespec='seconds')}\n\n"
            "## Review checklist (manual)\n\n"
            "- [ ] Listen for TTS glitches / mispronunciations (regenerate a chunk via --script)\n"
            "- [ ] Fact-check any claim that sounds off\n"
            "- [ ] Upload manually as long-form; set AI-disclosure toggle\n"
            "- [ ] Add to analytics tracker\n"
        )
    print(f"\nDone. Staged for review at:\n  {episode_dir}")
    print("Nothing was uploaded or posted.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
