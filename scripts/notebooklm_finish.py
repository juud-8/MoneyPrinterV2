#!/usr/bin/env python3
"""Finish a downloaded NotebookLM (Gemini Notebook) video for a brand:
strip the provider watermark from the bottom edge and append the brand
outro — the automated replacement for the manual Canva de-branding pass.

This script only writes a new local file next to the input (or --output).
It NEVER uploads or posts anywhere.

Typical flow after scripts/notebooklm_short.py stages an episode:
    python scripts/notebooklm_finish.py output/<brand>/notebooklm/<ep>/notebooklm_short.mp4

First time on a new provider/format, calibrate the crop:
    python scripts/notebooklm_finish.py <video.mp4> --inspect
    (writes watermark_strip.png next to the input; adjust --crop-bottom or
    set production.notebooklm_crop_bottom_frac in the brand manifest)
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import video_postprocess
from archived_brands import is_brand_archived
from brand_switcher import load_brand


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="De-brand a NotebookLM video and append the brand outro (local only, no upload)."
    )
    parser.add_argument("input", help="downloaded NotebookLM video (mp4)")
    parser.add_argument("brand_id", nargs="?", default="the_strange_archive")
    parser.add_argument("--output", help="default: <input stem>_final.mp4")
    parser.add_argument(
        "--crop-bottom",
        type=float,
        default=None,
        help="fraction of frame height to remove from the bottom "
        "(default: manifest production.notebooklm_crop_bottom_frac, else "
        f"{video_postprocess.DEFAULT_CROP_BOTTOM_FRAC})",
    )
    parser.add_argument(
        "--mode",
        choices=["crop", "cover"],
        default="crop",
        help="crop = cut strip + slight center zoom; cover = paint a brand-color bar over it",
    )
    parser.add_argument("--cover-color", help="hex color for cover mode (default: brand palette secondary)")
    parser.add_argument("--outro", help="outro clip override (default: manifest production.outro_clip)")
    parser.add_argument("--no-outro", action="store_true", help="skip appending the outro")
    parser.add_argument("--target", help="WxH override, e.g. 1080x1920 (default: auto from input aspect)")
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="write watermark_strip.png (bottom 15%% of a late frame) for crop calibration, then exit",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the ffmpeg command and exit")
    return parser


def inspect_strip(input_path: str) -> str:
    """Save the bottom 15% of a frame near the end so the watermark height
    can be measured by eye before choosing a crop fraction."""
    out_png = os.path.join(os.path.dirname(os.path.abspath(input_path)), "watermark_strip.png")
    cmd = [
        "ffmpeg", "-sseof", "-2", "-i", input_path, "-frames:v", "1",
        "-vf", "crop=iw:ih*0.15:0:ih*0.85", "-y", out_png,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg inspect failed: {result.stderr[-800:]}")
    return out_png


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not os.path.isfile(args.input):
        print(f"ERROR: input not found: {args.input}")
        return 2

    if args.inspect:
        png = inspect_strip(args.input)
        print(f"Wrote {png}")
        print("Measure the watermark height vs the strip (strip = 15% of frame height),")
        print("then pass --crop-bottom or set production.notebooklm_crop_bottom_frac.")
        return 0

    if is_brand_archived(args.brand_id):
        print(f"ERROR: {args.brand_id} is archived.")
        return 2
    brand = load_brand(args.brand_id)
    if not brand:
        print(f"ERROR: unknown brand: {args.brand_id}")
        return 2

    production = brand.get("production", {})
    crop_bottom = (
        args.crop_bottom
        if args.crop_bottom is not None
        else production.get(
            "notebooklm_crop_bottom_frac", video_postprocess.DEFAULT_CROP_BOTTOM_FRAC
        )
    )
    cover_color = (
        args.cover_color
        or brand.get("color_palette", {}).get("secondary")
        or "#000000"
    )

    outro_path = None
    if not args.no_outro:
        outro_path = args.outro or production.get("outro_clip")
        if outro_path and not os.path.isabs(outro_path):
            outro_path = os.path.join(ROOT, outro_path)
        if not outro_path:
            print("NOTE: brand has no production.outro_clip; finishing without outro.")

    target = None
    if args.target:
        try:
            w, h = args.target.lower().split("x")
            target = (int(w), int(h))
        except ValueError:
            print(f"ERROR: --target must look like 1080x1920, got {args.target}")
            return 2

    output = args.output or f"{os.path.splitext(args.input)[0]}_final.mp4"

    if args.dry_run:
        src = video_postprocess.probe_media(args.input)
        target_w, target_h = target or video_postprocess.default_target(
            src["width"], src["height"]
        )
        outro = video_postprocess.probe_media(outro_path) if outro_path else None
        cmd = video_postprocess.build_finish_command(
            args.input, output,
            src_h=src["height"], target_w=target_w, target_h=target_h,
            crop_bottom_frac=crop_bottom, mode=args.mode, cover_color=cover_color,
            outro_path=outro_path,
            outro_has_audio=outro["has_audio"] if outro else True,
            outro_duration=outro["duration"] if outro else 0.0,
        )
        print("Would run:")
        print("  " + " ".join(cmd))
        return 0

    print(f"Finishing {os.path.basename(args.input)} [{args.brand_id}]")
    print(f"  de-brand: {args.mode}, bottom {crop_bottom:.1%}")
    print(f"  outro:    {outro_path or '(none)'}")
    finished = video_postprocess.run_finish(
        args.input, output,
        crop_bottom_frac=crop_bottom, mode=args.mode, cover_color=cover_color,
        outro_path=outro_path, target=target,
    )
    print(
        f"Done: {output}\n"
        f"  {finished['width']}x{finished['height']}, "
        f"{finished['duration']:.2f}s. Nothing was uploaded."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
