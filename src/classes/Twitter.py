import re
import sys
import time
import os
import json

from cache import *
from config import *
from status import *
from llm_provider import generate_text
from typing import List, Optional
from datetime import datetime
from termcolor import colored
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException


class Twitter:
    """
    Class for the Bot, that grows a Twitter account.
    """

    def __init__(
        self, account_uuid: str, account_nickname: str, fp_profile_path: str, topic: str
    ) -> None:
        """
        Initializes the Twitter Bot.

        Args:
            account_uuid (str): The account UUID
            account_nickname (str): The account nickname
            fp_profile_path (str): The path to the Firefox profile

        Returns:
            None
        """
        self.account_uuid: str = account_uuid
        self.account_nickname: str = account_nickname
        self.fp_profile_path: str = fp_profile_path
        self.topic: str = topic

        # Initialize the Firefox profile
        self.options: Options = Options()

        # Set headless state of browser
        if get_headless():
            self.options.add_argument("--headless")

        if not os.path.isdir(fp_profile_path):
            raise ValueError(
                f"Firefox profile path does not exist or is not a directory: {fp_profile_path}"
            )

        # Set the profile path
        self.options.add_argument("-profile")
        self.options.add_argument(fp_profile_path)

        # Set the service
        self.service: Service = Service(GeckoDriverManager().install())

        # Initialize the browser
        self.browser: webdriver.Firefox = webdriver.Firefox(
            service=self.service, options=self.options
        )
        self.wait: WebDriverWait = WebDriverWait(self.browser, 30)

    def close_browser(self) -> None:
        if self.browser is not None:
            try:
                self.browser.quit()
            except Exception:
                pass
            self.browser = None

    def post(self, text: Optional[str] = None) -> None:
        """
        Starts the Twitter Bot.

        Args:
            text (str): The text to post

        Returns:
            None
        """
        bot: webdriver.Firefox = self.browser
        verbose: bool = get_verbose()

        bot.get("https://x.com/compose/post")

        post_content: str = text if text is not None else self.generate_post()
        now: datetime = datetime.now()

        print(colored(" => Posting to Twitter:", "blue"), post_content[:30] + "...")
        body = post_content

        text_box = None
        text_box_selectors = [
            (By.CSS_SELECTOR, "div[data-testid='tweetTextarea_0'][role='textbox']"),
            (By.XPATH, "//div[@data-testid='tweetTextarea_0']//div[@role='textbox']"),
            (By.XPATH, "//div[@role='textbox']"),
        ]

        for selector in text_box_selectors:
            try:
                text_box = self.wait.until(EC.element_to_be_clickable(selector))
                text_box.click()
                text_box.send_keys(body)
                break
            except Exception:
                continue

        if text_box is None:
            raise RuntimeError(
                "Could not find tweet text box. Ensure you are logged into X in this Firefox profile."
            )


        post_button = None
        post_button_selectors = [
            (By.XPATH, "//button[@data-testid='tweetButtonInline']"),
            (By.XPATH, "//button[@data-testid='tweetButton']"),
            (By.XPATH, "//span[text()='Post']/ancestor::button"),
        ]

        for selector in post_button_selectors:
            try:
                post_button = self.wait.until(EC.element_to_be_clickable(selector))
                post_button.click()
                break
            except Exception:
                continue

        if post_button is None:
            raise RuntimeError("Could not find the Post button on X compose screen.")

        if verbose:
            print(colored(" => Pressed [ENTER] Button on Twitter..", "blue"))
        time.sleep(2)

        # Add the post to the cache
        self.add_post({"content": body, "date": now.strftime("%m/%d/%Y, %H:%M:%S")})

        success("Posted to Twitter successfully!")

    def post_video(self, video_path: str, text: Optional[str] = None) -> None:
        """
        Posts a video (e.g. a Short) to X, with an optional caption.

        NOTE: unlike post(), this depends on X's media-upload DOM (the hidden
        file input + video-processing preview), which is not covered by the
        existing post() selectors and has not been verified against a live
        upload — same caveat as the YouTube Studio upload flow in
        classes/YouTube.py: X can change this DOM without notice, so if this
        silently fails, check the selectors here first before assuming
        something else broke.

        Args:
            video_path (str): Absolute path to the video file to attach.
            text (str | None): Caption text; falls back to generate_post().

        Returns:
            None
        """
        if not os.path.isfile(video_path):
            raise ValueError(f"Video file does not exist: {video_path}")

        bot: webdriver.Firefox = self.browser
        verbose: bool = get_verbose()

        bot.get("https://x.com/compose/post")

        post_content: str = text if text is not None else self.generate_post()
        now: datetime = datetime.now()

        print(colored(" => Posting video to Twitter:", "blue"), post_content[:30] + "...")

        # 1. Attach the video via the hidden file input — Selenium can't
        # drive the native OS file-picker dialog, so send_keys() the
        # absolute path directly to the <input type="file"> element instead.
        file_input = None
        file_input_selectors = [
            (By.CSS_SELECTOR, "input[data-testid='fileInput']"),
            (By.XPATH, "//input[@type='file']"),
        ]
        for selector in file_input_selectors:
            try:
                file_input = self.wait.until(EC.presence_of_element_located(selector))
                break
            except Exception:
                continue

        if file_input is None:
            raise RuntimeError(
                "Could not find the media upload input on X compose screen. "
                "X may have changed its DOM — this selector needs updating."
            )

        # send_keys() on a file input base64-encodes the entire file and
        # ships it to geckodriver over local HTTP as a single command — for
        # a real video (tens of MB) that single request can exceed
        # Selenium's default 120s read timeout on its own, well before X
        # even starts processing the upload. Temporarily raise the
        # WebDriver HTTP client's timeout for this one call, then restore
        # it so later waits still fail fast on genuinely stuck pages.
        original_timeout = bot.command_executor.client_config.timeout
        try:
            bot.command_executor.client_config.timeout = 300
            file_input.send_keys(os.path.abspath(video_path))
        finally:
            bot.command_executor.client_config.timeout = original_timeout

        # 2. Wait for X to finish uploading/processing the video. This takes
        # noticeably longer than an image, so use a generous, separate
        # timeout rather than the default 30s self.wait.
        video_ready_selectors = [
            (By.CSS_SELECTOR, "div[data-testid='videoPlayer']"),
            (By.CSS_SELECTOR, "div[data-testid='attachments'] video"),
        ]
        video_ready = False
        for selector in video_ready_selectors:
            try:
                WebDriverWait(bot, 180).until(EC.presence_of_element_located(selector))
                video_ready = True
                break
            except Exception:
                continue

        if not video_ready:
            raise RuntimeError(
                "Video did not visibly finish processing on X within 180s "
                "(or the readiness selector is stale). Check the account "
                "manually — this may have posted anyway with a still-"
                "processing video, or may not have attached at all."
            )

        # Small settle delay — the preview can appear slightly before X is
        # actually ready to accept caption text / the Post click.
        time.sleep(3)

        # 3. Type the caption.
        text_box = None
        text_box_selectors = [
            (By.CSS_SELECTOR, "div[data-testid='tweetTextarea_0'][role='textbox']"),
            (By.XPATH, "//div[@data-testid='tweetTextarea_0']//div[@role='textbox']"),
            (By.XPATH, "//div[@role='textbox']"),
        ]
        for selector in text_box_selectors:
            try:
                text_box = self.wait.until(EC.element_to_be_clickable(selector))
                text_box.click()
                text_box.send_keys(post_content)
                break
            except Exception:
                continue

        if text_box is None:
            raise RuntimeError("Could not find tweet text box after attaching video.")

        # 4. Wait for the Post button to be truly ready, then click it.
        #
        # The video preview can render client-side before X finishes
        # processing the upload server-side — during that gap the button is
        # still disabled via aria-disabled="true" rather than the native
        # HTML disabled attribute, which Selenium's element_to_be_clickable
        # does not check. A click in that window is silently swallowed by
        # the app: no exception, nothing posted. Poll aria-disabled directly
        # and re-locate the button fresh each time rather than clicking on
        # a possibly-stale reference.
        post_button_selectors = [
            (By.XPATH, "//button[@data-testid='tweetButtonInline']"),
            (By.XPATH, "//button[@data-testid='tweetButton']"),
            (By.XPATH, "//span[text()='Post']/ancestor::button"),
        ]

        def _find_post_button():
            for selector in post_button_selectors:
                try:
                    return bot.find_element(*selector)
                except Exception:
                    continue
            return None

        post_button = None
        ready_deadline = time.time() + 90
        while time.time() < ready_deadline:
            candidate = _find_post_button()
            if candidate is not None:
                aria_disabled = (candidate.get_attribute("aria-disabled") or "").lower()
                if aria_disabled != "true" and candidate.is_enabled():
                    post_button = candidate
                    break
            time.sleep(1)

        if post_button is None:
            raise RuntimeError(
                "Post button never became enabled within 90s — the video "
                "upload likely never finished processing server-side even "
                "though a preview appeared. Check the account manually; do "
                "NOT mark this episode as posted in state."
            )

        post_button.click()

        if verbose:
            print(colored(" => Pressed [Post] with video attached..", "blue"))

        # Confirm the post actually submitted rather than assuming success —
        # a click that lands on a disabled/decoy button, or a post that gets
        # silently rejected (still-processing media, rate limit, etc.),
        # leaves the compose box exactly where it was with no exception
        # raised. On real success X either clears the textarea or tears down
        # the compose box entirely (element goes stale). Treat neither
        # happening within the timeout as a failure, not a success.
        confirmed = False
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                current_text = text_box.text
                if not current_text.strip():
                    confirmed = True
                    break
            except StaleElementReferenceException:
                confirmed = True
                break
            time.sleep(1)

        if not confirmed:
            raise RuntimeError(
                "Clicked Post but could not confirm the tweet actually "
                "submitted (compose box still shows the original text after "
                "20s). Check the account manually before assuming this "
                "posted — do NOT mark this episode as posted in state."
            )

        self.add_post(
            {
                "content": post_content,
                "date": now.strftime("%m/%d/%Y, %H:%M:%S"),
                "video_path": video_path,
            }
        )

        success("Posted video to Twitter successfully!")

    def get_posts(self) -> List[dict]:
        """
        Gets the posts from the cache.

        Returns:
            posts (List[dict]): The posts
        """
        if not os.path.exists(get_twitter_cache_path()):
            # Create the cache file
            with open(get_twitter_cache_path(), "w") as file:
                json.dump({"accounts": []}, file, indent=4)

        with open(get_twitter_cache_path(), "r") as file:
            parsed = json.load(file)

            # Find our account
            accounts = parsed["accounts"]
            for account in accounts:
                if account["id"] == self.account_uuid:
                    posts = account["posts"]

                    if posts is None:
                        return []

                    # Return the posts
                    return posts

        return []

    def add_post(self, post: dict) -> None:
        """
        Adds a post to the cache.

        Args:
            post (dict): The post to add

        Returns:
            None
        """
        with open(get_twitter_cache_path(), "r") as file:
            previous_json = json.loads(file.read())

            # Find our account
            accounts = previous_json["accounts"]
            for account in accounts:
                if account["id"] == self.account_uuid:
                    account["posts"].append(post)

            # Commit changes
            with open(get_twitter_cache_path(), "w") as f:
                f.write(json.dumps(previous_json))

    def generate_post(self) -> str:
        """
        Generates a post for the Twitter account based on the topic.

        Returns:
            post (str): The post
        """
        completion = generate_text(
            f"Generate a Twitter post about: {self.topic} in {get_twitter_language()}. "
            "The Limit is 2 sentences. Choose a specific sub-topic of the provided topic."
        )

        if get_verbose():
            info("Generating a post...")

        if completion is None:
            error("Failed to generate a post. Please try again.")
            sys.exit(1)

        # Apply Regex to remove all *
        completion = re.sub(r"\*", "", completion).replace('"', "")

        if get_verbose():
            info(f"Length of post: {len(completion)}")
        if len(completion) >= 260:
            return completion[:257].rsplit(" ", 1)[0] + "..."

        return completion
