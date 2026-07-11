# RUN THIS N AMOUNT OF TIMES
import sys

from status import *
from cache import get_accounts
from config import get_verbose
from classes.Tts import TTS
from classes.Twitter import Twitter
from classes.YouTube import YouTube
from llm_provider import select_model
from post_bridge_integration import maybe_crosspost_youtube_short
from review_gate import should_proceed_with_upload
from archived_brands import assert_brand_runnable, is_brand_archived
from brand_switcher import (
    bootstrap_brand,
    get_active_brand_id,
    load_active_brand,
    resolve_youtube_account,
    set_active_brand,
)

def main():
    """Main function to post content to Twitter or upload videos to YouTube.

    Command-line arguments:
        sys.argv[1]: purpose — "twitter" or "youtube"
        sys.argv[2]: account UUID (youtube) or account UUID (twitter)
        sys.argv[3]: Ollama model name
        sys.argv[4]: optional brand_id override
    """
    purpose = str(sys.argv[1])
    account_id = str(sys.argv[2])
    model = str(sys.argv[3]) if len(sys.argv) > 3 else None
    brand_id = str(sys.argv[4]) if len(sys.argv) > 4 else None

    if brand_id:
        if is_brand_archived(brand_id):
            error(
                f"Brand '{brand_id}' is archived and cannot run via cron. "
                "Remove it from ARCHIVED_BRANDS to resurrect."
            )
            sys.exit(2)
        set_active_brand(brand_id)
        bootstrap_brand(brand_id)
    else:
        bootstrap_brand(get_active_brand_id())

    if model:
        select_model(model)
    else:
        error("No Ollama model specified. Pass model name as third argument.")
        sys.exit(1)

    verbose = get_verbose()

    if purpose == "twitter":
        accounts = get_accounts("twitter")

        if not account_id:
            error("Account UUID cannot be empty.")

        for acc in accounts:
            if acc["id"] == account_id:
                if verbose:
                    info("Initializing Twitter...")
                twitter = Twitter(
                    acc["id"],
                    acc["nickname"],
                    acc["firefox_profile"],
                    acc["topic"]
                )
                twitter.post()
                if verbose:
                    success("Done posting.")
                break
    elif purpose == "youtube":
        tts = TTS()

        accounts = get_accounts("youtube")

        if not account_id:
            error("Account UUID cannot be empty.")

        # Prefer account linked to active brand
        brand = load_active_brand()
        brand_account = resolve_youtube_account(brand, create=False)
        if brand_account and brand_account.get("id") != account_id:
            if verbose:
                warning(
                    f"Cron account {account_id} differs from active brand account "
                    f"{brand_account.get('id')}; using cron account id."
                )

        for acc in accounts:
            if acc["id"] == account_id:
                if verbose:
                    info(f"Initializing YouTube ({load_active_brand().get('channel_name')})...")
                youtube = YouTube(
                    acc["id"],
                    acc["nickname"],
                    acc["firefox_profile"],
                    acc["niche"],
                    acc["language"]
                )
                youtube.generate_video(tts, interactive=False)
                if should_proceed_with_upload(
                    youtube.video_path,
                    youtube.metadata.get("title", ""),
                    youtube.metadata.get("description", ""),
                    interactive=False,
                ):
                    upload_success = youtube.upload_video()
                    if upload_success:
                        if verbose:
                            success("Uploaded Short.")
                        maybe_crosspost_youtube_short(
                            video_path=youtube.video_path,
                            title=youtube.metadata.get("title", ""),
                            interactive=False,
                        )
                    else:
                        warning("YouTube upload failed. Skipping Post Bridge cross-post.")
                else:
                    warning("Upload skipped by review gate.")
                break
    else:
        error("Invalid Purpose, exiting...")
        sys.exit(1)

if __name__ == "__main__":
    main()
