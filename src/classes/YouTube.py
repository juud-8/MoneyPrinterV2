import re
import json
import time
import os
import assemblyai as aai

from utils import *
from cache import *
from .Tts import TTS
from llm_provider import generate_text
from config import *
from status import *
from content_funnel import build_description
from asset_gen import AssetResult, generate_image as gen_image, generate_asset_with_fallback
from asset_strategy import shot_role_for_index, tier_for_shot_role
from video_effects import apply_ken_burns, apply_crossfade
from video_captions import composite_captions_on_video
from analytics import (
    log_video,
    log_asset_spend,
    log_duration_rejection,
    log_topic_rejection,
)
from brand_switcher import get_production_setting, load_active_brand
from channel_branding import get_publishing_config
from content_styles import get_content_style, resolve_style_name, DEFAULT_SCRIPT_RULES
from youtube_upload_flow import (
    radio_matches_visibility,
    resolve_upload_visibility,
    visibility_radios_present,
)
from topic_scoring import pick_best
from content_strategy import (
    build_topic_strategy_block,
    recent_topic_labels,
    script_engagement_instruction,
)
from research_brief import (
    build_grounded_research_prompt,
    collect_sources,
    parse_research_brief,
    render_research_notes,
    research_quality_issues,
    save_research_brief,
)
from topic_similarity import find_near_duplicate
from uuid import uuid4
from constants import *
from typing import List, Optional
from moviepy import (
    AudioFileClip,
    ImageClip,
    TextClip,
    VideoFileClip,
    CompositeVideoClip,
    CompositeAudioClip,
    concatenate_videoclips,
    afx,
)
from termcolor import colored
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import ElementClickInterceptedException
from moviepy.video.tools.subtitles import SubtitlesClip
from webdriver_manager.firefox import GeckoDriverManager
from datetime import datetime

# MoviePy 2.x uses IMAGEMAGICK_BINARY env var (no change_settings API)
os.environ["IMAGEMAGICK_BINARY"] = get_imagemagick_path()


class YouTube:
    """
    Class for YouTube Automation.

    Steps to create a YouTube Short:
    1. Generate a topic [DONE]
    2. Generate a script [DONE]
    3. Generate metadata (Title, Description, Tags) [DONE]
    4. Generate AI Image Prompts [DONE]
    4. Generate Images based on generated Prompts [DONE]
    5. Convert Text-to-Speech [DONE]
    6. Show images each for n seconds, n: Duration of TTS / Amount of images [DONE]
    7. Combine Concatenated Images with the Text-to-Speech [DONE]
    """

    def __init__(
        self,
        account_uuid: str,
        account_nickname: str,
        fp_profile_path: str,
        niche: str,
        language: str,
    ) -> None:
        """
        Constructor for YouTube Class.

        Args:
            account_uuid (str): The unique identifier for the YouTube account.
            account_nickname (str): The nickname for the YouTube account.
            fp_profile_path (str): Path to the firefox profile that is logged into the specificed YouTube Account.
            niche (str): The niche of the provided YouTube Channel.
            language (str): The language of the Automation.

        Returns:
            None
        """
        self._account_uuid: str = account_uuid
        self._account_nickname: str = account_nickname
        self._fp_profile_path: str = fp_profile_path
        self._niche: str = niche
        self._language: str = language

        self.images = []
        self.asset_modalities = []  # parallel to self.images: "image" | "video_clip"
        self.asset_results = []
        self.format_type = "short"
        self.run_id = str(uuid4())
        self.research_notes = ""
        self.research_brief = {}
        self.research_brief_path = ""
        self.experiment_metadata = {}
        self.production_metadata = {}
        self.last_upload_error = None
        self.chapters = []

        # Initialize the Firefox profile
        self.options: Options = Options()

        # Set headless state of browser
        if get_headless():
            self.options.add_argument("--headless")

        if not os.path.isdir(self._fp_profile_path):
            raise ValueError(
                f"Firefox profile path does not exist or is not a directory: {self._fp_profile_path}"
            )

        self.options.add_argument("-profile")
        self.options.add_argument(self._fp_profile_path)
        self.service: Service = Service(GeckoDriverManager().install())
        self.browser: webdriver.Firefox | None = None

    def _ensure_browser(self) -> webdriver.Firefox:
        """Launch Firefox on first upload (not needed for video generation)."""
        if self.browser is None:
            self.browser = webdriver.Firefox(
                service=self.service, options=self.options
            )
        return self.browser

    def close_browser(self) -> None:
        if self.browser is not None:
            try:
                self.browser.quit()
            except Exception:
                pass
            self.browser = None

    @property
    def niche(self) -> str:
        """
        Getter Method for the niche.

        Returns:
            niche (str): The niche
        """
        return self._niche

    @property
    def language(self) -> str:
        """
        Getter Method for the language to use.

        Returns:
            language (str): The language
        """
        return self._language

    def generate_response(
        self, prompt: str, model_name: str = None, quality: bool = False
    ) -> str:
        """
        Generates an LLM Response based on a prompt and the user-provided model.

        Args:
            prompt (str): The prompt to use in the text generation.
            quality (bool): Use quality LLM (Gemini) for hooks/scripts/titles.

        Returns:
            response (str): The generated AI Repsonse.
        """
        return generate_text(prompt, model_name=model_name, quality=quality)

    def generate_research(self) -> str:
        """
        Add original value layer — key facts and angles for AI-policy compliance.

        Returns:
            research_notes (str): Brief research bullets for the scriptwriter.
        """
        active_brand = load_active_brand() or {}
        style_name = resolve_style_name(active_brand)
        requires_grounding = style_name in {"narrative_nonfiction", "weird_history"}

        if requires_grounding:
            topic = getattr(self, "subject", self.niche)
            sources = collect_sources(topic)
            if len(sources) < 2:
                raise RuntimeError(
                    f"Grounded research found only {len(sources)} usable source(s) for "
                    f"{topic!r}; refusing to generate an unverified nonfiction script."
                )
            prompt = build_grounded_research_prompt(topic, self.niche, sources)
            raw = self.generate_response(prompt, quality=True)
            brief = parse_research_brief(raw, topic, sources)
            issues = research_quality_issues(brief)
            if issues:
                raise RuntimeError("Research quality gate failed: " + "; ".join(issues))
            brief["brand_id"] = active_brand.get("brand_id", "")
            brief["content_style"] = style_name
            self.research_brief = brief
            self.research_brief_path = save_research_brief(
                brief, active_brand.get("brand_id", "unknown")
            )
            self.research_notes = render_research_notes(brief)
            info(
                f" => Grounded research: {len(brief['claims'])} claims across "
                f"{len(brief['cited_source_ids'])} cited sources."
            )
            return self.research_notes

        prompt = f"""
        You are researching a YouTube video for niche: {self.niche}.
        Topic idea: {getattr(self, 'subject', self.niche)}

        Provide 4-6 specific, factual bullet points a creator can use for an original
        explainer (real tool names, realistic workflows, concrete outcomes).
        No fluff. No markdown headers. One bullet per line starting with "-".
        """
        notes = self.generate_response(prompt, quality=True)
        self.research_notes = notes
        if get_verbose():
            info(f" => Research notes:\n{notes[:300]}...")
        return notes

    @staticmethod
    def _is_retryable_research_error(error: BaseException) -> bool:
        """True when a fresh topic may succeed (thin sources / quality gate)."""
        message = str(error)
        return (
            "Grounded research found only" in message
            or "Research quality gate failed" in message
        )

    def _generate_topic_and_research(self, max_attempts: int = 3) -> None:
        """Pick a topic and ground it; retry with a new topic if research fails.

        Preset subjects (self.subject already set) are attempted once — we never
        silently replace an operator-supplied topic.
        """
        preset = (getattr(self, "subject", None) or "").strip()
        attempts = 1 if preset else max(1, int(max_attempts))
        rejected: list[str] = list(getattr(self, "_research_rejected_topics", []) or [])
        last_error: BaseException | None = None

        for attempt in range(1, attempts + 1):
            try:
                if not preset:
                    # Clear so generate_topic() rolls a new candidate.
                    self.subject = ""
                self._research_rejected_topics = rejected
                self.generate_topic()
                self.generate_research()
                return
            except RuntimeError as error:
                last_error = error
                if preset or not self._is_retryable_research_error(error):
                    raise
                failed_topic = (getattr(self, "subject", None) or "").strip()
                if failed_topic and failed_topic not in rejected:
                    rejected.append(failed_topic)
                    active_brand = load_active_brand() or {}
                    log_topic_rejection(
                        candidate=failed_topic,
                        matched="research_gate",
                        similarity=0.0,
                        brand_id=active_brand.get("brand_id", ""),
                    )
                warning(
                    f"Topic research failed (attempt {attempt}/{attempts}): {error}"
                )
                if attempt < attempts:
                    info(" => Picking a different topic and retrying research...")
                    self.subject = ""
                    self.research_notes = ""
                    self.research_brief = {}
                    self.research_brief_path = ""

        assert last_error is not None
        raise RuntimeError(
            f"Exhausted {attempts} topic attempts without grounded research. "
            f"Last error: {last_error}"
        ) from last_error

    def generate_topic(self) -> str:
        """
        Generates a topic based on the YouTube Channel niche.

        Returns:
            topic (str): The generated topic.
        """
        preset = (getattr(self, "subject", None) or "").strip()
        if preset:
            self.subject = preset
            if get_verbose():
                info(f" => Using preset topic: {self.subject}")
            return self.subject

        style = get_content_style()

        episode_hint = ""
        if style["uses_episode_hint"]:
            ep = getattr(self, "episode_number", None)
            if ep:
                ep_label = str(ep).zfill(2) if str(ep).isdigit() else str(ep)
                episode_hint = (
                    f"\n- This is Episode {ep_label} — the series premiere. "
                    "Make it iconic, self-contained, and the kind of story viewers share."
                )

        prompt = style["topic_prompt"](self.niche, episode_hint)

        active_brand = load_active_brand() or {}
        strategy_block = build_topic_strategy_block(active_brand)
        if strategy_block:
            prompt += "\n\n" + strategy_block

        rejected = [
            t for t in (getattr(self, "_research_rejected_topics", None) or []) if t
        ]
        if rejected:
            blocked = "\n".join(f"- {t}" for t in rejected[-5:])
            prompt += (
                "\n\nDo NOT reuse any of these rejected topics (research could not "
                "verify them). Pick a completely different historical incident:\n"
                f"{blocked}"
            )

        # Steer topics toward what actually performed once the brand has
        # enough tracked view data (see performance_insights.py). Empty
        # string until then, so behavior is unchanged for new brands.
        try:
            from performance_insights import build_topic_insights_block

            insights = build_topic_insights_block(active_brand.get("brand_id", ""))
            if insights:
                prompt += "\n" + insights
                if get_verbose():
                    info(" => Topic prompt includes channel performance insights.")
        except Exception as e:
            warning(f"Performance insights skipped: {e}")

        candidate_count = max(1, int(style.get("topic_candidate_count", 1) or 1))

        candidates = []
        recent_labels = recent_topic_labels(active_brand)
        max_attempts = candidate_count + 2 if recent_labels else candidate_count
        for _ in range(max_attempts):
            completion = self.generate_response(prompt, quality=True)
            if completion:
                candidate = completion.strip().strip('"').strip("'")
                duplicate = find_near_duplicate(candidate, recent_labels)
                if duplicate:
                    warning(
                        f"Rejected near-duplicate topic ({duplicate[1]:.0%} similar "
                        f"to \"{duplicate[0][:80]}\"): {candidate}"
                    )
                    log_topic_rejection(
                        candidate=candidate,
                        matched=duplicate[0],
                        similarity=duplicate[1],
                        brand_id=active_brand.get("brand_id", ""),
                    )
                    continue
                candidates.append(candidate)
                if len(candidates) >= candidate_count:
                    break

        if not candidates:
            raise RuntimeError(
                "No novel topic candidate passed generation and duplicate checks."
            )

        if len(candidates) > 1:
            self.subject = pick_best(candidates)
            if get_verbose():
                info(f" => Picked best of {len(candidates)} topic candidates: {self.subject}")
        else:
            self.subject = candidates[0]

        return self.subject

    def _short_speech_wps(self) -> float:
        return 2.5

    def _get_outro_path(self) -> str:
        rel = get_production_setting("outro_clip", "") or ""
        if not rel:
            return ""
        path = rel if os.path.isabs(rel) else os.path.join(ROOT_DIR, rel)
        return path if os.path.isfile(path) else ""

    def _outro_duration(self) -> float:
        configured = get_production_setting("outro_duration_seconds", None)
        if configured:
            return float(configured)
        outro_path = self._get_outro_path()
        if not outro_path:
            return 0.0
        try:
            with VideoFileClip(outro_path) as clip:
                return float(clip.duration or 0.0)
        except Exception:
            return 0.0

    def _short_target_duration(self) -> float:
        if self.format_type == "longform":
            return 45.0  # unused for long-form pacing today; kept for signature symmetry

        style = get_content_style()
        default_seconds = style["default_target_seconds"]
        total = float(
            get_production_setting("target_duration_seconds", default_seconds)
            or default_seconds
        )

        if style["subtract_outro_from_target"]:
            outro = self._outro_duration()
            if outro > 0:
                return max(total - outro, style["min_target_floor_seconds"])

        return total

    def _short_target_words(self) -> int:
        return int(self._short_target_duration() * self._short_speech_wps())

    def _short_min_words(self) -> int:
        return int(self._short_target_duration() * 2.2)

    def _short_max_words(self) -> Optional[int]:
        """Word count corresponding to a style's hard length ceiling
        (e.g. ~95s), or None if the style doesn't set one."""
        style = get_content_style()
        ceiling_secs = style.get("max_target_ceiling_seconds")
        if not ceiling_secs:
            return None
        return int(ceiling_secs * self._short_speech_wps())

    def generate_script(self, _attempt: int = 0, shorten_note: str = "") -> str:
        """
        Generate a hook-first script with retention beats and CTA.

        Args:
            shorten_note: Extra instruction injected when a previous take's
                voiceover ran past the style's hard audio-duration gate.

        Returns:
            script (str): The script of the video.
        """
        sentence_length = get_script_sentence_length()
        research = getattr(self, "research_notes", "") or ""
        style = get_content_style()
        is_short = self.format_type != "longform"
        engagement_instruction = script_engagement_instruction(load_active_brand() or {})
        engagement_rule = (
            f"\n        - {engagement_instruction}"
            if is_short and engagement_instruction
            else ""
        )

        if is_short and style["short_script_rules"]:
            target_secs = int(self._short_target_duration())
            target_words = self._short_target_words()
            min_words = self._short_min_words()
            script_rules = style["short_script_rules"]
            length_instruction = style["short_length_instruction"](
                target_secs, target_words, min_words
            )
        else:
            script_rules = DEFAULT_SCRIPT_RULES
            if self.format_type == "longform":
                target_words = get_longform_target_minutes() * 130
                length_instruction = (
                    f"Write approximately {target_words} words ({get_longform_target_minutes()} minutes spoken). "
                    "Structure with clear sections/chapters. Include 3-5 retention hooks ('But here's the thing...', etc.)."
                )
            else:
                length_instruction = (
                    f"Exactly {sentence_length} short sentences. Total under 45 seconds when spoken."
                )

        shorten_rule = f"\n        - {shorten_note}" if shorten_note else ""

        prompt = f"""
        Write a YouTube {self.format_type} voiceover script.

        RULES:
        {script_rules}{engagement_rule}{shorten_rule}
        - Use short punchy sentences for Shorts; slightly longer for long-form
        - {length_instruction}
        - Language: {self.language}
        - Source markers such as [S1] are audit metadata; never include them in the spoken script
        - NO markdown, NO titles, NO stage directions, NO quotes around the script
        - Return ONLY the spoken script

        Topic: {self.subject}
        Research to incorporate:
        {research}
        """
        completion = self.generate_response(prompt, quality=True)

        completion = re.sub(r"\*", "", completion)
        completion = re.sub(r"^#+\s*", "", completion, flags=re.MULTILINE)
        completion = re.sub(r"\s*\[S\d+(?:\s*,\s*S\d+)*\]", "", completion)

        if not completion:
            error("The generated script is empty.")
            return

        max_len = 15000 if self.format_type == "longform" else 5000
        if len(completion) > max_len:
            if _attempt < 4:
                if get_verbose():
                    warning("Generated Script is too long. Retrying...")
                return self.generate_script(_attempt + 1, shorten_note=shorten_note)
            completion = completion[:max_len]

        self.script = completion.strip()

        if style["enforce_min_word_count"] and is_short:
            word_count = len(self.script.split())
            min_words = self._short_min_words()
            if word_count < min_words and _attempt < 3:
                warning(
                    f"Script too short ({word_count} words, need ≥{min_words}). Retrying..."
                )
                return self.generate_script(_attempt + 1, shorten_note=shorten_note)

        if style.get("enforce_max_word_count") and is_short:
            max_words = self._short_max_words()
            word_count = len(self.script.split())
            if max_words and word_count > max_words:
                if _attempt < 3:
                    warning(
                        f"Script too long ({word_count} words, cap ~{max_words}). Retrying..."
                    )
                    return self.generate_script(_attempt + 1, shorten_note=shorten_note)
                warning(
                    f"Script still over the ~{max_words}-word cap after retries "
                    f"({word_count} words) — proceeding with the longer script rather "
                    "than truncating mid-sentence."
                )

        return self.script

    def generate_metadata(self, _attempt: int = 0) -> dict:
        """
        Generates Video metadata for the to-be-uploaded YouTube video.

        Returns:
            metadata (dict): The generated metadata.
        """
        style = get_content_style()
        style_title_rules = (style.get("title_rules") or "").strip()
        extra_title_rules = f"\n{style_title_rules}" if style_title_rules else ""

        title_prompt = f"""Write a YouTube title for this video.

Topic: {self.subject}
Format: {self.format_type}

Rules:
- Under 70 characters
- Do NOT include hashtags — they belong in the description, not the title
- Use curiosity or specificity (numbers, real names, dates)
- Return ONLY the title{extra_title_rules}"""

        preset_title = (getattr(self, "preset_title", "") or "").strip()
        if preset_title:
            title = preset_title
            if get_verbose():
                info(f" => Using preset title: {title}")
        else:
            title_candidate_count = max(
                1, int(style.get("title_candidate_count", 1) or 1)
            )
            title_candidates = []
            for _ in range(title_candidate_count):
                candidate = self.generate_response(title_prompt, quality=True)
                if candidate:
                    cleaned = candidate.split("\n")[0].strip().strip('"').strip("'")
                    # Hashtags in titles get truncated into junk fragments ("#His")
                    # once suffixes/length limits apply — hard-strip them even if
                    # the LLM ignores the prompt rule. Description keeps hashtags.
                    cleaned = re.sub(r"\s*#\w+", "", cleaned).strip(" -|—")
                    if cleaned:
                        title_candidates.append(cleaned)

            if len(title_candidates) > 1:
                title = pick_best(title_candidates)
                if get_verbose():
                    info(f" => Picked best of {len(title_candidates)} title candidates: {title}")
            else:
                title = title_candidates[0] if title_candidates else ""

        ep = getattr(self, "episode_number", None)
        if ep and not re.match(r"^episode\s", title, re.IGNORECASE):
            ep_label = str(ep).zfill(2) if str(ep).isdigit() else str(ep)
            prefix = f"Episode {ep_label}: "
            max_base = 100 - len(prefix)
            if len(title) > max_base:
                title = title[:max_base].rstrip(" .,#")
            title = prefix + title

        if len(title) > 100:
            if _attempt < 4:
                if get_verbose():
                    warning(
                        f"Generated Title is too long ({len(title)} chars). Retrying..."
                    )
                return self.generate_metadata(_attempt + 1)
            title = title[:100].rstrip()

        title_suffix = get_production_setting("title_suffix", "") or ""
        if title_suffix and title_suffix.strip() not in title:
            candidate = f"{title} {title_suffix.strip()}".strip()
            if len(candidate) <= 100:
                title = candidate
            else:
                max_base = 100 - len(title_suffix.strip()) - 1
                title = f"{title[:max_base].rstrip()} {title_suffix.strip()}"

        raw_description = self.generate_response(
            f"""Write a YouTube description body (2-4 short paragraphs) for this script.
Include timestamps placeholder only if long-form.
Do NOT include affiliate links — those are added automatically.

Script:
{self.script[:3000]}""",
            quality=True,
        )

        description = build_description(
            raw_description,
            subject=self.subject,
            format_type=self.format_type,
            include_affiliate=True,
        )

        self.metadata = {"title": title, "description": description}

        return self.metadata

    def _calculate_image_count(self, estimated_duration: float = None) -> int:
        """Derive image count from script length / duration — not len(script)/3."""
        if estimated_duration is None:
            word_count = len(self.script.split())
            wps = 2.5 if self.format_type == "short" else 2.2
            estimated_duration = word_count / wps

        rate = get_images_per_second()
        if self.format_type == "longform":
            rate = min(rate, 0.12)

        count = max(3, int(estimated_duration * rate) + 1)
        cap = 50 if self.format_type == "longform" else 12
        return min(count, cap)

    def generate_prompts(self, _attempt: int = 0) -> List[str]:
        """
        Generates AI Image Prompts based on the provided Video Script.

        Returns:
            image_prompts (List[str]): Generated List of image prompts.
        """
        n_prompts = self._calculate_image_count()

        style_suffix = get_production_setting("image_style_suffix", "") or (
            "cinematic documentary illustration style, high contrast, dramatic lighting, "
            "no text in images, 9:16 vertical"
        )

        prompt = f"""
        Generate exactly {n_prompts} image prompts for AI image generation for a {self.format_type} video.
        Subject: {self.subject}
        Niche: {self.niche}

        Style: {style_suffix}

        Return ONLY a JSON array of strings, e.g. ["prompt 1", "prompt 2"]

        Script excerpt:
        {self.script[:2000]}
        """

        completion = (
            str(self.generate_response(prompt, quality=True))
            .replace("```json", "")
            .replace("```", "")
        )

        image_prompts = []

        if "image_prompts" in completion:
            image_prompts = json.loads(completion)["image_prompts"]
        else:
            try:
                image_prompts = json.loads(completion)
                if get_verbose():
                    info(f" => Generated Image Prompts: {image_prompts}")
            except Exception:
                if get_verbose():
                    warning(
                        "LLM returned an unformatted response. Attempting to clean..."
                    )

                # Get everything between [ and ], and turn it into a list
                r = re.compile(r"\[.*\]")
                image_prompts = r.findall(completion)
                if len(image_prompts) == 0:
                    if _attempt < 4:
                        if get_verbose():
                            warning("Failed to generate Image Prompts. Retrying...")
                        return self.generate_prompts(_attempt + 1)
                    if get_verbose():
                        warning("Using fallback image prompts after retries.")
                    image_prompts = [
                        f"Cinematic tech visual about {self.subject}, dramatic lighting, 9:16"
                    ] * max(1, int(n_prompts))

        n_prompts_int = int(n_prompts)
        if len(image_prompts) > n_prompts_int:
            image_prompts = image_prompts[:n_prompts_int]
        while len(image_prompts) < n_prompts_int:
            image_prompts.append(
                f"Professional AI automation scene related to {self.subject}, vertical 9:16"
            )

        self.image_prompts = image_prompts

        success(f"Generated {len(image_prompts)} Image Prompts.")

        return image_prompts

    def generate_image(self, prompt: str, use_premium: bool = False) -> str:
        """
        Generates an AI Image based on the given prompt using the configured
        asset provider (see `asset_gen.py`).

        Args:
            prompt (str): Reference for image generation
            use_premium (bool): Use premium image model

        Returns:
            path (str): The path to the generated image.
        """
        result = gen_image(prompt, use_premium=use_premium)
        if result:
            self.images.append(result.path)
            self.asset_modalities.append(result.modality)
            return result.path
        return None

    def generate_thumbnail(self) -> str:
        """
        Generate a 16:9 thumbnail image with bold topic text area.

        Returns:
            path (str): Path to thumbnail PNG
        """
        thumb_prompt = self.generate_response(
            f"""Write ONE image generation prompt for a YouTube thumbnail (16:9).
Topic: {self.subject}
Style: high contrast, dark navy background, teal accents, dramatic lighting,
split layout with space for bold text, no small unreadable text baked in.
Return ONLY the prompt sentence.""",
            quality=True,
        )
        thumb_result = gen_image(
            thumb_prompt,
            aspect_ratio="16:9",
            use_premium=True,
        )
        if not thumb_result:
            return None
        path = thumb_result.path

        # Overlay title text with Pillow
        try:
            from PIL import Image, ImageDraw, ImageFont

            img = Image.open(path).convert("RGB")
            draw = ImageDraw.Draw(img)
            font_path = os.path.join(get_fonts_dir(), get_font())
            try:
                font = ImageFont.truetype(font_path, 72)
            except Exception:
                font = ImageFont.load_default()

            title_short = self.metadata.get("title", self.subject)[:40].upper()
            # Shadow
            draw.text((42, img.height - 180), title_short, font=font, fill="black")
            draw.text((40, img.height - 182), title_short, font=font, fill="#FFD93D")

            thumb_path = os.path.join(ROOT_DIR, ".mp", str(uuid4()) + "_thumb.png")
            img.save(thumb_path)
            self.thumbnail_path = thumb_path
            success(f"Generated thumbnail: {thumb_path}")
            return thumb_path
        except Exception as e:
            warning(f"Thumbnail text overlay failed: {e}")
            self.thumbnail_path = path
            return path

    def generate_script_to_speech(self, tts_instance: TTS) -> str:
        """
        Converts the generated script into Speech using KittenTTS and returns the path to the wav file.

        Args:
            tts_instance (tts): Instance of TTS Class.

        Returns:
            path_to_wav (str): Path to generated audio (WAV Format).
        """
        path = os.path.join(ROOT_DIR, ".mp", str(uuid4()) + ".wav")

        # Clean script, remove every character that is not a word character, a space, a period, a question mark, or an exclamation mark.
        self.script = re.sub(r"[^\w\s.?!]", "", self.script)

        self.tts_path = tts_instance.synthesize(self.script, path)

        if get_verbose():
            info(f' => Wrote TTS to "{self.tts_path}"')

        return self.tts_path

    def add_video(self, video: dict) -> None:
        """
        Adds a video to the cache.

        Args:
            video (dict): The video to add

        Returns:
            None
        """
        videos = self.get_videos()
        videos.append(video)

        cache = get_youtube_cache_path()

        with open(cache, "r") as file:
            previous_json = json.loads(file.read())

            # Find our account
            accounts = previous_json["accounts"]
            for account in accounts:
                if account["id"] == self._account_uuid:
                    account["videos"].append(video)

            # Commit changes
            with open(cache, "w") as f:
                f.write(json.dumps(previous_json))

    def generate_subtitles(self, audio_path: str) -> str:
        """
        Generates subtitles for the audio using the configured STT provider.

        Args:
            audio_path (str): The path to the audio file.

        Returns:
            path (str): The path to the generated SRT File.
        """
        provider = str(get_stt_provider() or "local_whisper").lower()

        if provider == "local_whisper":
            return self.generate_subtitles_local_whisper(audio_path)

        if provider == "third_party_assemblyai":
            return self.generate_subtitles_assemblyai(audio_path)

        warning(f"Unknown stt_provider '{provider}'. Falling back to local_whisper.")
        return self.generate_subtitles_local_whisper(audio_path)

    def generate_subtitles_assemblyai(self, audio_path: str) -> str:
        """
        Generates subtitles using AssemblyAI.

        Args:
            audio_path (str): Audio file path

        Returns:
            path (str): Path to SRT file
        """
        aai.settings.api_key = get_assemblyai_api_key()
        config = aai.TranscriptionConfig()
        transcriber = aai.Transcriber(config=config)
        transcript = transcriber.transcribe(audio_path)
        subtitles = transcript.export_subtitles_srt()

        srt_path = os.path.join(ROOT_DIR, ".mp", str(uuid4()) + ".srt")

        with open(srt_path, "w") as file:
            file.write(subtitles)

        return srt_path

    def _format_srt_timestamp(self, seconds: float) -> str:
        """
        Formats a timestamp in seconds to SRT format.

        Args:
            seconds (float): Seconds

        Returns:
            ts (str): HH:MM:SS,mmm
        """
        total_millis = max(0, int(round(seconds * 1000)))
        hours = total_millis // 3600000
        minutes = (total_millis % 3600000) // 60000
        secs = (total_millis % 60000) // 1000
        millis = total_millis % 1000
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def generate_subtitles_local_whisper(self, audio_path: str) -> str:
        """
        Generates subtitles using local Whisper (faster-whisper).

        Args:
            audio_path (str): Audio file path

        Returns:
            path (str): Path to SRT file
        """
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            error(
                "Local STT selected but 'faster-whisper' is not installed. "
                "Install it or switch stt_provider to third_party_assemblyai."
            )
            raise

        model = WhisperModel(
            get_whisper_model(),
            device=get_whisper_device(),
            compute_type=get_whisper_compute_type(),
        )
        segments, _ = model.transcribe(audio_path, vad_filter=True)

        lines = []
        for idx, segment in enumerate(segments, start=1):
            start = self._format_srt_timestamp(segment.start)
            end = self._format_srt_timestamp(segment.end)
            text = str(segment.text).strip()

            if not text:
                continue

            lines.append(str(idx))
            lines.append(f"{start} --> {end}")
            lines.append(text)
            lines.append("")

        subtitles = "\n".join(lines)
        srt_path = os.path.join(ROOT_DIR, ".mp", str(uuid4()) + ".srt")
        with open(srt_path, "w", encoding="utf-8") as file:
            file.write(subtitles)

        return srt_path

    def _build_video_clip_shot(self, video_path: str, target_duration: float):
        """
        Load a premium-generated video clip shot, normalize it to 9:16, and
        fit it to its allotted slot duration — trimmed if longer, held on
        its last frame if shorter. No Ken Burns/crossfade treatment since
        the clip already has its own motion.
        """
        clip = VideoFileClip(video_path).with_fps(30)

        if round((clip.w / clip.h), 4) < 0.5625:
            clip = clip.cropped(
                width=clip.w,
                height=round(clip.w / 0.5625),
                x_center=clip.w / 2,
                y_center=clip.h / 2,
            )
        else:
            clip = clip.cropped(
                width=round(0.5625 * clip.h),
                height=clip.h,
                x_center=clip.w / 2,
                y_center=clip.h / 2,
            )
        clip = clip.resized(new_size=(1080, 1920))

        if clip.duration > target_duration:
            clip = clip.subclipped(0, target_duration)
        elif clip.duration < target_duration:
            freeze = clip.to_ImageClip(
                t=max(clip.duration - 0.04, 0),
                duration=target_duration - clip.duration,
            ).with_fps(30)
            clip = concatenate_videoclips([clip, freeze], method="compose")

        return clip.with_duration(target_duration)

    def combine(self) -> str:
        """
        Combines everything into the final video.

        Returns:
            path (str): The path to the generated MP4 File.
        """
        combined_image_path = os.path.join(ROOT_DIR, ".mp", str(uuid4()) + ".mp4")
        threads = get_threads()
        tts_clip = AudioFileClip(self.tts_path)
        max_duration = tts_clip.duration
        req_dur = max_duration / len(self.images)

        # Make a generator that returns a TextClip when called with consecutive
        generator = lambda txt: TextClip(
            text=txt,
            font=os.path.join(get_fonts_dir(), get_font()),
            font_size=100,
            color="#FFFF00",
            stroke_color="black",
            stroke_width=5,
            size=(1080, 1920),
            method="caption",
        )

        print(colored("[+] Combining images...", "blue"))

        clips = []
        tot_dur = 0
        ken_burns = get_ken_burns_enabled()
        idx = 0
        while tot_dur < max_duration:
            for slot, image_path in enumerate(self.images):
                modality = (
                    self.asset_modalities[slot]
                    if slot < len(self.asset_modalities)
                    else "image"
                )

                if modality == "video_clip":
                    clip = self._build_video_clip_shot(image_path, req_dur)
                else:
                    clip = ImageClip(image_path, duration=req_dur).with_fps(30)

                    if round((clip.w / clip.h), 4) < 0.5625:
                        if get_verbose():
                            info(f" => Resizing Image: {image_path} to 1080x1920")
                        clip = clip.cropped(
                            width=clip.w,
                            height=round(clip.w / 0.5625),
                            x_center=clip.w / 2,
                            y_center=clip.h / 2,
                        )
                    else:
                        if get_verbose():
                            info(f" => Resizing Image: {image_path} to 1920x1080")
                        clip = clip.cropped(
                            width=round(0.5625 * clip.h),
                            height=clip.h,
                            x_center=clip.w / 2,
                            y_center=clip.h / 2,
                        )
                    clip = clip.resized(new_size=(1080, 1920))

                    if ken_burns:
                        clip = apply_ken_burns(clip, req_dur, index=idx)
                        idx += 1

                clips.append(clip)
                tot_dur += clip.duration

        if get_crossfade_duration() > 0 and len(clips) > 1:
            clips = apply_crossfade(clips, fade_duration=get_crossfade_duration())

        final_clip = concatenate_videoclips(clips, method="compose").with_fps(30)
        random_song = choose_random_song(
            prefer_keywords=get_content_style()["music_keywords"]
        )

        subtitles = None
        subtitles_path = None
        try:
            subtitles_path = self.generate_subtitles(self.tts_path)
            equalize_subtitles(subtitles_path, 8)
        except Exception as e:
            warning(f"Failed to generate subtitles: {e}")

        random_song_clip = AudioFileClip(random_song).with_fps(44100)

        # Turn down volume
        random_song_clip = random_song_clip.with_effects([afx.MultiplyVolume(0.1)])
        comp_audio = CompositeAudioClip([tts_clip.with_fps(44100), random_song_clip])

        final_clip = final_clip.with_audio(comp_audio)
        final_clip = final_clip.with_duration(tts_clip.duration)

        if subtitles_path and get_word_captions_enabled():
            try:
                final_clip = composite_captions_on_video(final_clip, subtitles_path)
            except Exception as e:
                warning(f"Word captions failed, falling back to block subtitles: {e}")
                subtitles = SubtitlesClip(subtitles_path, make_textclip=generator)
                subtitles = subtitles.with_position(("center", "center"))
                final_clip = CompositeVideoClip([final_clip, subtitles])
        elif subtitles_path:
            subtitles = SubtitlesClip(subtitles_path, make_textclip=generator)
            subtitles = subtitles.with_position(("center", "center"))
            final_clip = CompositeVideoClip([final_clip, subtitles])

        outro_path = self._get_outro_path()
        if outro_path:
            info(f" => Appending brand outro ({self._outro_duration():.1f}s)...")
            outro_clip = VideoFileClip(outro_path).with_fps(30)
            if outro_clip.w != 1080 or outro_clip.h != 1920:
                outro_clip = outro_clip.resized(new_size=(1080, 1920))
            final_clip = concatenate_videoclips(
                [final_clip, outro_clip], method="compose"
            )
            final_clip.write_videofile(combined_image_path, threads=threads)
            outro_clip.close()
        else:
            final_clip.write_videofile(combined_image_path, threads=threads)

        success(f'Wrote Video to "{combined_image_path}"')

        return combined_image_path

    def _generate_shot_asset(
        self, prompt: str, tier: str, *, per_shot_seconds: float
    ) -> AssetResult:
        """Generate one shot asset; fall back to a safe prompt or prior frame on block."""
        kwargs = {
            "aspect_ratio": get_nanobanana2_aspect_ratio(),
            "video_duration_seconds": min(
                max(per_shot_seconds, 3.0), get_premium_video_max_duration_seconds()
            ),
        }
        try:
            return generate_asset_with_fallback(prompt, tier, **kwargs)
        except RuntimeError:
            style_suffix = get_production_setting("image_style_suffix", "") or (
                "cinematic documentary illustration style, high contrast, dramatic lighting, "
                "no text in images, 9:16 vertical"
            )
            safe_prompt = (
                f"Abstract symbolic vintage engraving evoking the theme of {self.subject}, "
                f"non-graphic, no corpses or gore, {style_suffix}"
            )
            warning(
                f"Asset generation failed for prompt {prompt[:60]!r}…; retrying with safe fallback."
            )
            try:
                return generate_asset_with_fallback(safe_prompt, "standard", **kwargs)
            except RuntimeError:
                if self.images:
                    warning("Safe fallback also failed; reusing previous shot image.")
                    return AssetResult(
                        path=self.images[-1],
                        modality="image",
                        tier="standard",
                        provider="reuse",
                    )
                raise

    def _build_experiment_metadata(self) -> dict:
        brand = load_active_brand() or {}
        production = brand.get("production") or {}
        configured = production.get("experiment") or {}
        if not isinstance(configured, dict):
            configured = {}
        return {
            "run_id": self.run_id,
            "experiment_id": os.environ.get(
                "MPV2_EXPERIMENT_ID", str(configured.get("id") or "baseline")
            ).strip(),
            "variant": os.environ.get(
                "MPV2_EXPERIMENT_VARIANT", str(configured.get("variant") or "control")
            ).strip(),
            "content_style": resolve_style_name(brand),
            "format": self.format_type,
        }

    def _research_metadata(self) -> dict:
        brief = self.research_brief or {}
        return {
            "grounded": bool(brief),
            "brief_path": self.research_brief_path,
            "claim_count": len(brief.get("claims") or []),
            "source_count": len(brief.get("sources") or []),
            "cited_source_count": len(brief.get("cited_source_ids") or []),
        }

    def _enforce_max_audio_duration(self, tts_instance: TTS, style: dict) -> None:
        """Hard duration gate on the real TTS voiceover.

        A voiceover past the style's `max_audio_duration_seconds` is
        rejected, regenerated with an explicit shorter-script instruction,
        and — if it STILL runs long — the whole generation is aborted via
        RuntimeError rather than passed through to upload. Every rejection
        is logged to analytics.json (duration_rejections) for review.
        """
        max_audio = style.get("max_audio_duration_seconds")
        if not max_audio or self.format_type == "longform":
            return

        brand_id = (load_active_brand() or {}).get("brand_id", "")
        audio_duration = AudioFileClip(self.tts_path).duration
        for attempt in range(1, 3):
            if audio_duration <= max_audio:
                return
            warning(
                f"Voiceover {audio_duration:.1f}s exceeds the {max_audio:.0f}s hard "
                f"cap — rejecting and regenerating shorter (attempt {attempt}/2)..."
            )
            log_duration_rejection(
                video_subject=getattr(self, "subject", ""),
                audio_seconds=audio_duration,
                cap_seconds=max_audio,
                attempt=attempt,
                action="retry",
                brand_id=brand_id,
            )
            target_words = self._short_target_words()
            self.generate_script(
                shorten_note=(
                    f"CRITICAL: the previous script produced {audio_duration:.0f} "
                    f"seconds of narration, over the hard {max_audio:.0f}-second "
                    f"limit. Write a SUBSTANTIALLY shorter script (~{target_words} "
                    "words): cut setup beats and adjectives, keep the punchline."
                )
            )
            self.generate_metadata()
            self.generate_script_to_speech(tts_instance)
            self.production_metadata["tts_provider"] = getattr(
                tts_instance, "last_provider_used", ""
            )
            self.production_metadata["tts_model"] = getattr(
                tts_instance, "last_model_used", ""
            )
            audio_duration = AudioFileClip(self.tts_path).duration

        if audio_duration > max_audio:
            log_duration_rejection(
                video_subject=getattr(self, "subject", ""),
                audio_seconds=audio_duration,
                cap_seconds=max_audio,
                attempt=3,
                action="abort",
                brand_id=brand_id,
            )
            raise RuntimeError(
                f"Voiceover still {audio_duration:.1f}s (cap {max_audio:.0f}s) after "
                "shorter-script retries — aborting this generation instead of "
                "uploading an over-length Short."
            )

    def _generate_pipeline(self, tts_instance: TTS, interactive: bool = True) -> str:
        """Shared generation pipeline for short and long-form."""
        self.run_id = str(uuid4())
        self.images = []
        self.asset_modalities = []
        self.asset_results = []
        self.research_notes = ""
        self.research_brief = {}
        self.research_brief_path = ""
        self.production_metadata = {}
        self._research_rejected_topics = []

        self._generate_topic_and_research(max_attempts=3)
        self.generate_script()
        self.generate_metadata()
        self.generate_prompts()

        # Per-shot asset tier (see asset_strategy.py): brand-configurable,
        # defaults to "standard" for every shot unless a brand manifest
        # opts in (e.g. production.asset_strategy.hook = "premium_video").
        per_shot_seconds = self._short_target_duration() / max(len(self.image_prompts), 1)
        for i, prompt in enumerate(self.image_prompts):
            role = shot_role_for_index(i)
            tier = tier_for_shot_role(role)
            result = self._generate_shot_asset(
                prompt,
                tier,
                per_shot_seconds=per_shot_seconds,
            )
            self.images.append(result.path)
            self.asset_modalities.append(result.modality)
            self.asset_results.append(result)
            if result.tier != "standard":
                active_brand = load_active_brand()
                log_asset_spend(
                    video_title=getattr(self, "subject", ""),
                    role=role,
                    tier=result.tier,
                    modality=result.modality,
                    provider=result.provider,
                    cost_usd=result.cost_usd,
                    brand_id=active_brand.get("brand_id", ""),
                )

        self.generate_script_to_speech(tts_instance)
        self.production_metadata["tts_provider"] = getattr(
            tts_instance, "last_provider_used", ""
        )
        self.production_metadata["tts_model"] = getattr(
            tts_instance, "last_model_used", ""
        )

        style = get_content_style()
        if style["enforce_min_audio_duration"] and self.format_type != "longform":
            min_duration = self._short_target_duration() * style["min_audio_duration_ratio"]
            for _ in range(2):
                audio_duration = AudioFileClip(self.tts_path).duration
                if audio_duration >= min_duration:
                    break
                warning(
                    f"Voiceover only {audio_duration:.1f}s "
                    f"(target {self._short_target_duration():.0f}s). Regenerating longer script..."
                )
                self.generate_script()
                self.generate_metadata()
                self.generate_script_to_speech(tts_instance)
                self.production_metadata["tts_provider"] = getattr(
                    tts_instance, "last_provider_used", ""
                )
                self.production_metadata["tts_model"] = getattr(
                    tts_instance, "last_model_used", ""
                )

        self._enforce_max_audio_duration(tts_instance, style)

        # Recalculate image timing now that we have real audio duration
        actual_count = self._calculate_image_count(
            estimated_duration=AudioFileClip(self.tts_path).duration
        )
        if actual_count < len(self.images):
            self.images = self.images[:actual_count]
            self.asset_modalities = self.asset_modalities[:actual_count]
        elif actual_count > len(self.images) and self.image_prompts:
            while len(self.images) < actual_count:
                self.generate_image(self.image_prompts[-1])

        path = self.combine()
        self.video_path = os.path.abspath(path)

        brand = load_active_brand()
        brand_id = brand.get("brand_id", "default")
        saved = save_video_output(
            self.video_path, brand_id, self.metadata.get("title", "")
        )
        if saved:
            self.output_video_path = saved
            success(f" => Saved copy: {saved}")

        if self.format_type == "longform":
            self.generate_thumbnail()

        self.production_metadata.update(
            {
                "asset_count": len(self.asset_results),
                "asset_modalities": [result.modality for result in self.asset_results],
                "asset_tiers": [result.tier for result in self.asset_results],
                "asset_providers": [result.provider for result in self.asset_results],
                "estimated_asset_cost_usd": round(
                    sum(float(result.cost_usd or 0.0) for result in self.asset_results), 2
                ),
                "target_duration_seconds": (
                    get_longform_target_minutes() * 60
                    if self.format_type == "longform"
                    else self._short_target_duration()
                ),
            }
        )

        log_video(
            title=self.metadata.get("title", ""),
            format_type=self.format_type,
            niche=self.niche,
            video_path=self.video_path,
            subject=self.subject,
            brand_id=brand_id,
            status="generated",
            experiment=self._build_experiment_metadata(),
            research=self._research_metadata(),
            production=self.production_metadata,
        )
        return path

    def generate_video(self, tts_instance: TTS, interactive: bool = True) -> str:
        """
        Generates a YouTube Short based on the provided niche and language.

        Args:
            tts_instance (TTS): Instance of TTS Class.
            interactive (bool): Allow premium hero prompt and review prompts.

        Returns:
            path (str): The path to the generated MP4 File.
        """
        self.format_type = "short"
        path = self._generate_pipeline(tts_instance, interactive=interactive)

        if get_verbose():
            info(f" => Generated Short: {path}")

        return path

    def generate_longform_video(self, tts_instance: TTS, interactive: bool = True) -> str:
        """
        Generates a long-form YouTube video (6-10 min target) with thumbnail.

        Returns:
            path (str): Path to generated MP4.
        """
        self.format_type = "longform"
        path = self._generate_pipeline(tts_instance, interactive=interactive)

        if get_verbose():
            info(f" => Generated long-form video: {path}")

        return path

    def get_channel_id(self) -> str:
        """
        Gets the Channel ID of the YouTube Account.

        Returns:
            channel_id (str): The Channel ID.
        """
        driver = self._ensure_browser()
        time.sleep(2)
        channel_id = driver.current_url.split("/")[-1]
        self.channel_id = channel_id

        return channel_id

    def _require_elements(
        self, driver, by, value, minimum: int = 1, context: str = ""
    ) -> list:
        """
        Find elements and fail loudly (with a clear, specific message) if
        YouTube Studio's DOM doesn't match what this upload flow expects —
        instead of a confusing IndexError/NoSuchElementException deep in
        Selenium internals when YT Studio's UI changes.
        """
        elements = driver.find_elements(by, value)
        if len(elements) < minimum:
            label = f" ({context})" if context else ""
            raise RuntimeError(
                f"YouTube Studio upload flow{label}: expected at least {minimum} "
                f"element(s) matching {by}={value!r}, found {len(elements)}. "
                "YouTube Studio's UI likely changed — this selector needs updating."
            )
        return elements

    def _set_ai_disclosure(self, driver, disclose: bool) -> None:
        """
        Best-effort: set YouTube Studio's AI-content disclosure ("Altered or
        synthetic content" Yes/No control, added to the upload flow's
        "Show more" section in 2025). This UI is much newer than the
        long-stable made-for-kids radios, so — unlike `_require_elements` —
        this NEVER raises or aborts the upload if it can't find/click the
        control. It only logs a clear warning so a human can check it
        manually before publishing (see `review_gate.py`'s pre-upload
        summary), because a wrong/missed disclosure is a compliance risk,
        not a crash-worthy one, and a fragile selector here should never be
        able to break uploads for every brand.
        """
        try:
            show_more = driver.find_elements(
                By.XPATH, "//*[self::button or self::div][contains(., 'Show more')]"
            )
            for el in show_more:
                try:
                    el.click()
                    time.sleep(0.5)
                    break
                except Exception:
                    continue

            target_text = "Yes" if disclose else "No"
            disclosure_section = driver.find_elements(
                By.XPATH,
                "//*[contains(translate(text(), 'ALTEREDSYNTHETIC', 'alteredsynthetic'), 'altered') "
                "or contains(translate(text(), 'ALTEREDSYNTHETIC', 'alteredsynthetic'), 'synthetic')]",
            )
            if not disclosure_section:
                warning(
                    "Could not find the 'Altered or synthetic content' disclosure "
                    "control in YouTube Studio (UI may have changed). Verify it "
                    f"manually before publishing — intended setting: {target_text}."
                )
                return

            option = driver.find_elements(
                By.XPATH, f"//*[@role='radio' or @type='radio'][.//text()='{target_text}' or @aria-label='{target_text}']"
            )
            if not option:
                warning(
                    "Found the AI-disclosure section but not a clickable "
                    f"'{target_text}' control. Verify and set it manually before publishing."
                )
                return

            option[0].click()
            if get_verbose():
                info(f" => Set AI-content disclosure to '{target_text}'.")
        except Exception as e:
            warning(
                f"AI-content disclosure step failed ({e}). Verify it manually "
                "before publishing — this never blocks the upload."
            )

    def _capture_upload_dialog_video_id(self, driver) -> str:
        """Read the video id from the upload dialog's "Video link" field.

        YouTube Studio assigns the final video id the moment the upload
        starts and shows it as a `https://youtu.be/<id>` link inside the
        dialog. Grabbing it here is the only reliable source — the video
        list can still show an OLDER video at the top while the new upload
        is processing, which previously caused stale URLs to be logged
        against new videos (breaking per-video metrics).

        Best-effort: returns "" if the link isn't found so the caller can
        fall back to the (title-verified) video list.
        """
        try:
            anchors = driver.find_elements(
                By.XPATH, "//a[contains(@href, 'youtu.be/')]"
            )
            for anchor in anchors:
                href = anchor.get_attribute("href") or ""
                video_id = href.rstrip("/").split("/")[-1].split("?")[0]
                if video_id:
                    return video_id
        except Exception as e:
            if get_verbose():
                warning(f"Could not read video link from upload dialog: {e}")
        return ""

    @staticmethod
    def _normalize_title_for_match(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").strip()).lower()

    def _find_uploaded_video_id_in_list(self, driver) -> str:
        """Fallback URL capture: scan the Studio video list for a row whose
        title matches this upload. Returns "" when no row matches — a wrong
        URL is worse than no URL (it corrupts per-video metrics)."""
        videos = self._require_elements(
            driver,
            By.TAG_NAME,
            "ytcp-video-row",
            minimum=1,
            context="video list after upload",
        )
        expected = self._normalize_title_for_match(self.metadata.get("title", ""))

        for row in videos:
            try:
                row_text = self._normalize_title_for_match(row.text)
                anchor = row.find_element(By.TAG_NAME, "a")
                href = anchor.get_attribute("href") or ""
            except Exception:
                continue
            # Studio truncates long titles in the list — match on a prefix.
            if expected and expected[:60] in row_text:
                return href.rstrip("/").split("/edit")[0].split("/")[-1]

        warning(
            "Could not find the uploaded video in the Studio list by title — "
            "it may still be processing. Logging the upload without a URL "
            "rather than risking a stale one; the next metrics refresh won't "
            "track this video until the URL is added to .mp/analytics.json."
        )
        return ""

    def _dismiss_youtube_overlays(self, driver) -> None:
        """Close hashtag/social suggestion dropdowns that block Studio textboxes."""
        try:
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            time.sleep(0.3)
        except Exception:
            pass

    def _set_textbox_value(self, element, text: str, driver=None) -> None:
        """Fill a YouTube Studio contenteditable textbox (clear() often fails on these)."""
        try:
            element.click()
        except ElementClickInterceptedException:
            if driver:
                self._dismiss_youtube_overlays(driver)
                driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});", element
                )
                time.sleep(0.2)
            try:
                element.click()
            except ElementClickInterceptedException:
                if driver:
                    driver.execute_script("arguments[0].focus();", element)
                else:
                    raise

        time.sleep(0.3)
        element.send_keys(Keys.CONTROL, "a")
        element.send_keys(Keys.BACKSPACE)
        element.send_keys(text)

    def _collect_radio_label_texts(self, driver) -> list[str]:
        labels = driver.find_elements(By.XPATH, YOUTUBE_RADIO_BUTTON_XPATH)
        texts = []
        for el in labels:
            text = (el.text or "").strip()
            if not text:
                text = (el.get_attribute("aria-label") or "").strip()
            texts.append(text)
        return texts

    def _on_visibility_step(self, driver) -> bool:
        return visibility_radios_present(self._collect_radio_label_texts(driver))

    def _advance_to_visibility_step(
        self, driver, wait: WebDriverWait, max_clicks: int = 8
    ) -> None:
        """Click Next until Private/Unlisted/Public radios are visible.

        Studio insert steps vary (Video elements / Checks). Blindly clicking
        Next three times often lands Done on the wrong step and saves a Draft.
        """
        for _ in range(max_clicks):
            if self._on_visibility_step(driver):
                return
            try:
                next_button = wait.until(
                    EC.presence_of_element_located((By.ID, YOUTUBE_NEXT_BUTTON_ID))
                )
            except Exception:
                time.sleep(2)
                continue
            aria_disabled = (next_button.get_attribute("aria-disabled") or "").lower()
            if aria_disabled == "true" or not next_button.is_enabled():
                # Checks still running — wait and retry rather than force Done.
                time.sleep(2.5)
                continue
            try:
                next_button.click()
            except ElementClickInterceptedException:
                self._dismiss_youtube_overlays(driver)
                time.sleep(0.5)
                next_button.click()
            time.sleep(1.5)

        if not self._on_visibility_step(driver):
            raise RuntimeError(
                "Could not reach YouTube Studio visibility step "
                "(Private/Unlisted/Public). Upload aborted to avoid leaving a Draft."
            )

    def _set_visibility(self, driver, visibility: str) -> None:
        """Click the visibility radio by label text (not brittle index)."""
        target = resolve_upload_visibility({"default_visibility": visibility})
        labels = driver.find_elements(By.XPATH, YOUTUBE_RADIO_BUTTON_XPATH)
        for el in labels:
            text = (el.text or "").strip()
            aria = (el.get_attribute("aria-label") or "").strip()
            name = (el.get_attribute("name") or "").strip()
            haystack = f"{text} {aria} {name}"
            if radio_matches_visibility(haystack, target):
                try:
                    el.click()
                except ElementClickInterceptedException:
                    driver.execute_script("arguments[0].click();", el)
                time.sleep(0.5)
                return

        # Fallback: paper-radio name attributes used by some Studio builds.
        for name_attr in (target.upper(), target.lower(), target.capitalize()):
            found = driver.find_elements(By.NAME, name_attr)
            if found:
                try:
                    found[0].click()
                except ElementClickInterceptedException:
                    driver.execute_script("arguments[0].click();", found[0])
                time.sleep(0.5)
                return

        raise RuntimeError(
            f"Could not find YouTube visibility radio for {target!r}. "
            "Studio UI may have changed — refusing to click a wrong index."
        )

    def _wait_for_done_enabled(self, driver, timeout: float = 180) -> None:
        """Wait until Done/Publish is clickable (Checks may block it)."""

        def _enabled(d):
            buttons = d.find_elements(By.ID, YOUTUBE_DONE_BUTTON_ID)
            if not buttons:
                return False
            btn = buttons[0]
            aria_disabled = (btn.get_attribute("aria-disabled") or "").lower()
            if aria_disabled == "true":
                return False
            try:
                return btn.is_enabled() and btn.is_displayed()
            except Exception:
                return False

        WebDriverWait(driver, timeout).until(_enabled)

    def _click_done_and_confirm(self, driver) -> None:
        """Click Done/Publish and dismiss common secondary confirmations."""
        done_button = driver.find_element(By.ID, YOUTUBE_DONE_BUTTON_ID)
        try:
            done_button.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", done_button)

        time.sleep(2)
        # Public visibility sometimes shows an extra "Publish" confirm sheet.
        confirm_xpaths = [
            "//ytcp-button[@id='publish-button']",
            "//*[@id='publish-button']",
            "//*[self::button or @role='button'][normalize-space()='Publish']",
        ]
        for xpath in confirm_xpaths:
            for el in driver.find_elements(By.XPATH, xpath):
                try:
                    if not el.is_displayed():
                        continue
                    el.click()
                    time.sleep(1)
                    return
                except Exception:
                    continue

    def _upload_dialog_looks_published(self, driver) -> bool:
        """True when post-Done success copy is visible (not just the draft link)."""
        phrases = (
            "video published",
            "video is being processed",
            "finished processing",
            "checks complete",
            "your video is live",
        )
        try:
            body = (driver.find_element(By.TAG_NAME, "body").text or "").lower()
        except Exception:
            body = ""
        return any(phrase in body for phrase in phrases)

    def upload_video(self) -> bool:
        """
        Uploads the video to YouTube.

        Returns:
            success (bool): Whether the upload was successful or not.
        """
        try:
            self.get_channel_id()

            driver = self._ensure_browser()
            wait = WebDriverWait(driver, 60)
            verbose = get_verbose()

            # Go to youtube.com/upload
            driver.get("https://www.youtube.com/upload")

            # Set video file
            FILE_PICKER_TAG = "ytcp-uploads-file-picker"
            file_picker = wait.until(
                EC.presence_of_element_located((By.TAG_NAME, FILE_PICKER_TAG))
            )
            INPUT_TAG = "input"
            file_input = file_picker.find_element(By.TAG_NAME, INPUT_TAG)
            file_input.send_keys(self.video_path)

            # Wait for upload dialog and title field
            wait.until(
                EC.presence_of_all_elements_located((By.ID, YOUTUBE_TEXTBOX_ID))
            )
            time.sleep(3)

            # Set title
            textboxes = self._require_elements(
                driver, By.ID, YOUTUBE_TEXTBOX_ID, minimum=2, context="title/description textboxes"
            )
            if len(textboxes) != 2 and verbose:
                warning(
                    f"Expected exactly 2 textboxes (title, description) but found "
                    f"{len(textboxes)}. Using first as title, last as description — "
                    "verify this is still correct if upload looks wrong."
                )

            title_el = textboxes[0]
            description_el = textboxes[-1]

            if verbose:
                info("\t=> Setting title...")

            self._set_textbox_value(title_el, self.metadata["title"], driver=driver)

            if verbose:
                info("\t=> Setting description...")

            # Hashtags in the title open a suggestion dropdown that blocks the description box
            self._dismiss_youtube_overlays(driver)
            time.sleep(0.5)
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", description_el
            )
            time.sleep(0.5)
            self._set_textbox_value(
                description_el, self.metadata["description"], driver=driver
            )

            time.sleep(0.5)

            # Capture the assigned video id from the dialog's "Video link"
            # field now — it's final as soon as the upload starts, and is
            # immune to the stale-top-row problem in the video list.
            uploaded_video_id = self._capture_upload_dialog_video_id(driver)
            if verbose and uploaded_video_id:
                info(f"\t=> Captured video id from upload dialog: {uploaded_video_id}")

            # Set `made for kids` option
            if verbose:
                info("\t=> Setting `made for kids` option...")

            is_for_kids_checkbox = driver.find_element(
                By.NAME, YOUTUBE_MADE_FOR_KIDS_NAME
            )
            is_not_for_kids_checkbox = driver.find_element(
                By.NAME, YOUTUBE_NOT_MADE_FOR_KIDS_NAME
            )

            if not get_is_for_kids():
                is_not_for_kids_checkbox.click()
            else:
                is_for_kids_checkbox.click()

            time.sleep(0.5)

            # Best-effort: set the "Altered or synthetic content" disclosure.
            disclose_ai = get_production_setting(
                "ai_disclosure", get_ai_disclosure_default()
            )
            self._set_ai_disclosure(driver, bool(disclose_ai))

            visibility = resolve_upload_visibility(get_publishing_config())
            if verbose:
                info(f"\t=> Advancing to visibility step (target: {visibility})...")
            self._advance_to_visibility_step(driver, wait)

            if verbose:
                info(f"\t=> Setting visibility to {visibility}...")
            self._set_visibility(driver, visibility)

            if verbose:
                info("\t=> Waiting for Done/Publish to become enabled...")
            self._wait_for_done_enabled(driver, timeout=180)

            if verbose:
                info("\t=> Clicking done/publish button...")
            self._click_done_and_confirm(driver)

            if verbose:
                info("\t=> Getting video URL...")

            # Prefer dialog link; give Studio time to finish the publish dialog
            # so we do not close Firefox while the upload is still a Draft.
            deadline = time.time() + 45
            while time.time() < deadline and not uploaded_video_id:
                uploaded_video_id = self._capture_upload_dialog_video_id(driver)
                if uploaded_video_id:
                    break
                time.sleep(1.5)

            publish_ok = self._upload_dialog_looks_published(driver)

            # Always verify against the Shorts list when possible. Drafts get
            # video IDs too, so a dialog link alone is not proof of publish.
            list_video_id = ""
            for attempt in range(4):
                try:
                    driver.get(
                        f"https://studio.youtube.com/channel/{self.channel_id}/videos/short"
                    )
                    time.sleep(3)
                    list_video_id = self._find_uploaded_video_id_in_list(driver) or ""
                except Exception as list_err:
                    warning(f"Studio Shorts list verification attempt failed: {list_err}")
                    list_video_id = ""
                if list_video_id:
                    break
                if attempt < 3:
                    time.sleep(5)

            if list_video_id:
                uploaded_video_id = list_video_id
                publish_ok = True
            elif not publish_ok:
                raise RuntimeError(
                    "Upload wizard finished but the video was not found in Studio "
                    "Shorts — it was likely left as a Draft. Open YouTube Studio → "
                    "Content → Drafts, set visibility, publish, then backfill the "
                    "URL in .mp/analytics.json."
                )
            elif not uploaded_video_id:
                warning(
                    "Publish UI looked OK but no video id was captured; logging "
                    "upload without a URL. Repair analytics after confirming in Studio."
                )

            url = build_url(uploaded_video_id) if uploaded_video_id else ""
            self.uploaded_video_url = url

            upload_brand = load_active_brand()
            log_video(
                title=self.metadata.get("title", ""),
                format_type=getattr(self, "format_type", "short"),
                niche=self.niche,
                video_path=self.video_path,
                url=url,
                subject=getattr(self, "subject", ""),
                brand_id=upload_brand.get("brand_id", ""),
                status="uploaded",
                experiment=self._build_experiment_metadata(),
                research=self._research_metadata(),
                production=self.production_metadata,
            )

            if verbose:
                success(f" => Uploaded Video: {url or '(URL not captured)'}")

            # Add video to cache
            self.add_video(
                {
                    "title": self.metadata["title"],
                    "description": self.metadata["description"],
                    "url": url,
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            )

            # Close the browser
            self.close_browser()

            return True
        except Exception as e:
            import traceback

            # Persist the real cause on the instance — callers only see a
            # bool return value, so without this, scheduled/cron runs that
            # log "UPLOAD FAILED" to a file have no way to know why.
            self.last_upload_error = f"{type(e).__name__}: {e}"
            self.last_upload_traceback = traceback.format_exc()
            error(f"YouTube upload failed: {e}")
            if get_verbose():
                traceback.print_exc()
            self.close_browser()
            return False

    def get_videos(self) -> List[dict]:
        """
        Gets the uploaded videos from the YouTube Channel.

        Returns:
            videos (List[dict]): The uploaded videos.
        """
        if not os.path.exists(get_youtube_cache_path()):
            # Create the cache file
            with open(get_youtube_cache_path(), "w") as file:
                json.dump({"videos": []}, file, indent=4)
            return []

        videos = []
        # Read the cache file
        with open(get_youtube_cache_path(), "r") as file:
            previous_json = json.loads(file.read())
            # Find our account
            accounts = previous_json["accounts"]
            for account in accounts:
                if account["id"] == self._account_uuid:
                    videos = account["videos"]

        return videos
