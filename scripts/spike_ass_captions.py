"""Operator spike: SRT → ASS karaoke → optional FFmpeg burn-in.

Does not touch the production MoviePy caption path.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from caption_ass import AssStyle, burn_captions, ffmpeg_available, write_ass_from_srt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ASS caption spike (not production-wired)")
    parser.add_argument("--srt", required=True, help="Input SRT path")
    parser.add_argument(
        "--ass-out",
        default="",
        help="Output ASS path (default: beside SRT with .ass)",
    )
    parser.add_argument("--video", default="", help="Optional video to burn captions into")
    parser.add_argument("--out", default="", help="Burn-in MP4 output path")
    parser.add_argument("--fonts-dir", default="", help="Optional fonts directory for FFmpeg")
    parser.add_argument("--words-per-cue", type=int, default=4)
    args = parser.parse_args(argv)

    srt_path = Path(args.srt)
    ass_path = Path(args.ass_out) if args.ass_out else srt_path.with_suffix(".ass")
    write_ass_from_srt(
        str(srt_path),
        str(ass_path),
        style=AssStyle(),
        max_words_per_cue=args.words_per_cue,
    )
    print(f"ass={ass_path}")

    if args.video:
        if not args.out:
            raise SystemExit("--out is required when --video is set")
        if not ffmpeg_available():
            raise SystemExit("ffmpeg not on PATH; wrote ASS only")
        burn_captions(
            args.video,
            str(ass_path),
            args.out,
            fonts_dir=args.fonts_dir or None,
        )
        print(f"video={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
