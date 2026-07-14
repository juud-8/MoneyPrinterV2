#!/usr/bin/env python3
"""Generate YouTube channel art PNGs from the active brand manifest prompts."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

from brand_switcher import load_brand, switch_brand  # noqa: E402
from asset_gen import generate_image  # noqa: E402


def main() -> int:
    brand_id = sys.argv[1] if len(sys.argv) > 1 else "the_strange_archive"
    switch_brand(brand_id)
    brand = load_brand(brand_id) or {}
    prompts = brand.get("image_gen_prompts") or {}
    channel_name = brand.get("channel_name", brand_id)

    out_dir = os.path.join(ROOT, "output", brand_id, "channel_art")
    os.makedirs(out_dir, exist_ok=True)

    jobs = [
        ("profile_pic.png", prompts.get("profile_pic", ""), "1:1", True),
        ("banner.png", prompts.get("banner", ""), "16:9", True),
        ("thumbnail_template.png", prompts.get("thumbnail_template", ""), "16:9", False),
    ]

    missing = [name for name, prompt, _, _ in jobs if not prompt.strip()]
    if missing:
        print(f"ERROR: missing image_gen_prompts for: {', '.join(missing)}")
        return 1

    print(f"Generating channel art for {channel_name} -> {out_dir}")
    for filename, prompt, aspect, premium in jobs:
        print(f"  {filename} ({aspect}, premium={premium}) ...")
        result = generate_image(prompt, aspect_ratio=aspect, use_premium=premium)
        if not result or not os.path.isfile(result.path):
            print(f"ERROR: generation failed for {filename}")
            return 1
        dest = os.path.join(out_dir, filename)
        with open(result.path, "rb") as src, open(dest, "wb") as dst:
            dst.write(src.read())
        print(f"    -> {dest}")

    print("\nUpload these in YouTube Studio -> Customization:")
    print(f"  Profile picture: {os.path.join(out_dir, 'profile_pic.png')}")
    print(f"  Banner:          {os.path.join(out_dir, 'banner.png')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
