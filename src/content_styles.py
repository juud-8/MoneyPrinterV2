"""Content style profiles.

A brand selects one of these profiles via its manifest's `content_type`
(e.g. "horror") or an explicit `production.content_style` override. All
content-shape decisions — hook style, pacing/length rules, minimum-length
enforcement, and music mood — live here, keyed by a generic style name.

The video-generation engine (`classes/YouTube.py`) never branches on a
specific brand name or brand_id. Adding a new brand that reuses an existing
content shape (e.g. another horror-style channel) requires zero engine code
changes — just set `content_type` (or `production.content_style`) in its
manifest.
"""

from datetime import datetime
from typing import Callable, Optional, TypedDict


class ContentStyle(TypedDict):
    topic_prompt: Callable[[str, str], str]
    uses_episode_hint: bool
    default_target_seconds: float
    subtract_outro_from_target: bool
    min_target_floor_seconds: float
    short_script_rules: Optional[str]
    short_length_instruction: Optional[Callable[[int, int, int], str]]
    enforce_min_word_count: bool
    enforce_min_audio_duration: bool
    min_audio_duration_ratio: float
    music_keywords: Optional[list[str]]
    # Optional hard ceiling on Short length. When set alongside
    # enforce_max_word_count=True, classes/YouTube.py::generate_script will
    # retry a script that runs too long, the same way it already retries one
    # that's too short. Defaults below (None/False) preserve existing
    # behavior for every style that doesn't opt in.
    max_target_ceiling_seconds: Optional[float]
    enforce_max_word_count: bool
    # Optional multi-candidate topic/title generation + heuristic scoring
    # (see topic_scoring.py). A value of 1 (the default for every existing
    # style) preserves the original single-completion behavior exactly.
    topic_candidate_count: int
    title_candidate_count: int
    # Optional extra rules appended to the title prompt in
    # classes/YouTube.py::generate_metadata (None = generic rules only).
    title_rules: Optional[str]
    # Optional hard gate on REAL TTS audio length (seconds). When set,
    # classes/YouTube.py::_generate_pipeline rejects a generation whose
    # voiceover runs past this, retries with a shorter-script instruction,
    # and aborts (never uploads) if it still exceeds the cap. Every
    # rejection is logged via analytics.log_duration_rejection.
    max_audio_duration_seconds: Optional[float]


def _micro_horror_topic_prompt(niche: str, episode_hint: str) -> str:
    return f"""Generate ONE micro-horror story idea for a 60-second YouTube Short.

Niche: {niche}

Requirements:
- Must work as a complete scary story with a twist ending in under 60 seconds
- Psychological dread over gore; unsettling, not gratuitous
- Specific setting or character (e.g. "The babysitter who noticed the family photos change")
- Return ONLY the topic sentence, nothing else.{episode_hint}"""


def _narrative_nonfiction_topic_prompt(niche: str, episode_hint: str) -> str:
    return f"""Generate ONE "weird but true" historical fact or micro-story idea for a
75-second YouTube Short.

Niche: {niche}

Requirements:
- MUST be a real, independently verifiable historical event, fact, or figure — never an
  invented event presented as if it really happened. If you are not confident a fact is
  real and checkable, do not use it.
- Must have a genuine "wait, really?" hook — specific, surprising, and concrete (e.g. a
  real date, name, place, or number), not a vague generality
- Avoid sensitive, graphic, or exploitative framing of real victims/tragedies — favor the
  strange, ironic, or overlooked over the violent
- Return ONLY the topic sentence, nothing else.{episode_hint}"""


def _practical_demo_topic_prompt(niche: str, episode_hint: str) -> str:
    return f"""Generate ONE specific, clickable YouTube video idea for this niche: {niche}.

Requirements:
- Must be practical and demo-friendly (tool, workflow, or comparison)
- Must promise a clear outcome in under 60 seconds (Short) or 8 minutes (long-form)
- Avoid generic titles like "AI is amazing"
- Return ONLY the topic sentence, nothing else."""


def _weird_history_topic_prompt(niche: str, episode_hint: str) -> str:
    today = datetime.now().strftime("%B %d")
    return f"""Generate ONE "weird but true" historical fact or micro-story idea for a
50-60 second YouTube Short, in the style of a dry-witted archive file.

Niche: {niche}

Prefer topics from: strange wars, bizarre trials, disasters, odd customs, accidental
inventions, hoaxes, royal/political oddities, scientific mishaps, or forgotten conflicts.
Good reference energy: "army vs birds," "war over a pig," "dead pope put on trial,"
"the flood made of beer," "the war started by a bucket."

The topic MUST pair a specific number (a year, a count, a quantity) with an absurd
conflict or outcome — the number and the absurdity should collide in one sentence.
Titles built from topics like these are the channel's best performers:
- "How Liechtenstein Sent 80 Men to War in 1866 and Returned with 81"
- "How Cherries Made Millard Fillmore President in 1850"
A topic that can't produce a title like that (concrete number + absurd twist) is the
wrong topic — pick a different one.

Today's date is {today}. If a genuinely strange, well-documented historical event
happened on this exact day-of-year (in any year), STRONGLY prefer it and include the
date in the topic — anniversary hooks travel further in the feed. If nothing strong
matches this date, ignore this paragraph entirely rather than forcing a weak connection.

Requirements:
- MUST be a real, independently verifiable historical event, fact, or figure, drawn from
  public historical sources — never an invented event presented as if it really happened.
  If you are not confident a fact is real and checkable, do not use it.
- Must have a genuine "wait, WHAT?" hook — specific and concrete (a real date, name,
  place, or number), not a vague generality
- Must be fully explainable in 50-60 seconds of narration (a single contained incident,
  not a sprawling multi-year saga)
- Favor absurd contrast (a mundane cause with an outsized/ironic consequence, or vice versa)
- Avoid sensitive, graphic, or exploitative framing of real victims/tragedies — favor the
  strange, ironic, or overlooked over the violent

Explicitly DO NOT generate:
- Modern true crime or anything involving a living person / recent allegations
- Unsolved disappearances or conspiracy theories
- Fictional stories presented as real
- Graphic violence
- Generic "top 10 facts" list format
- Motivational or Stoic-quote content
- Reddit-story narration style
- Repetitive, generic AI-slop phrasing ("you won't believe", "mind-blowing", etc.)

Return ONLY the topic sentence, nothing else.{episode_hint}"""


def _micro_horror_length_instruction(target_secs: int, target_words: int, min_words: int) -> str:
    return (
        f"Write approximately {target_words} words ({target_secs} seconds when spoken aloud). "
        f"MINIMUM {min_words} words — do NOT write a shorter script. "
        f"Use 14-20 short punchy sentences."
    )


def _narrative_nonfiction_length_instruction(target_secs: int, target_words: int, min_words: int) -> str:
    return (
        f"Write approximately {target_words} words ({target_secs} seconds when spoken aloud). "
        f"MINIMUM {min_words} words — do NOT write a shorter script. "
        f"Use 10-16 sentences with a clear setup -> surprising fact -> closing thought structure."
    )


def _weird_history_length_instruction(target_secs: int, target_words: int, min_words: int) -> str:
    # Word-count math (safe to retune if `production.target_duration_seconds`
    # is overridden for this brand): narration runs at roughly 150 wpm
    # (~2.5 words/sec, see classes/YouTube.py::_short_speech_wps). The engine
    # subtracts `production.outro_duration_seconds` from the target when
    # pacing the story (see CONTENT_STYLES["weird_history"]
    # subtract_outro_from_target) — the outro clip is appended after the
    # narration/captions, not baked into the script.
    #
    # Story narration target: ~50-60 seconds (~125-150 words). Outro: ~3.2s.
    # Script-length ceiling max_target_ceiling_seconds (~70s / ~175 words)
    # sits below the hard 75s audio gate (max_audio_duration_seconds) so a
    # slightly slow TTS read still clears the gate.
    return (
        f"Write approximately {target_words} words ({target_secs} seconds spoken aloud at "
        f"~150 words/minute). MINIMUM {min_words} words. This is the STORY ONLY — a "
        f"~3 second brand outro is appended after narration, so do NOT pad the script "
        f"to fill that time. HARD CEILING: do NOT run past roughly 70 seconds of "
        f"narration (~175 words) even if the story feels like it needs more room — cut a "
        f"supporting beat instead of running long. Structure the script as ONE setup "
        f"paying off ONE punchline — never a list of loosely related facts. Use 7-11 "
        f"sentences following this exact structure: "
        f"(1) the FULL absurd outcome stated as a flat declarative fact in the first "
        f'sentence, under 15 words, verdict first (e.g. "In 1457, a pig was tried and '
        f'executed for murder.") — the viewer must grasp the entire twist premise '
        f"within the first 3 seconds, with zero setup or throat-clearing before it; "
        f"(2) one line acknowledging it sounds fake but is documented/real; "
        f"(3) 2-3 short sentences of setup escalating with specific factual beats "
        f"(names, dates, numbers) that all build toward the payoff; (4) the punchline — "
        f"the strangest twist or outcome, delivered in the final seconds as the payoff "
        f"the setup was building to; (5) end with ONE dry, deadpan Archivist-style "
        f'sign-off line (e.g. "The archive marks this file as: feathered, official, and '
        f'deeply embarrassing."). Tone: dry-witted documentary narrator, curious not '
        f"cringe. NO fake-horror voice, NO exaggerated YouTube hype, NO \"you won't "
        f"believe what happened next\", NO \"like and subscribe\" in the narration itself."
    )


# Engine-level default rules, used for any style that doesn't override
# `short_script_rules` (e.g. practical_demo's Shorts) and for long-form
# scripts regardless of style (no style currently changes long-form rules).
DEFAULT_SCRIPT_RULES = """
        - Line 1 MUST be a pattern-interrupt hook under 12 words (no "welcome" or "hey guys")
        - Deliver value using the research bullets — add original commentary, not generic AI fluff
        - End with a clear CTA (follow, comment, or get the free toolkit)
        """


CONTENT_STYLES: dict[str, ContentStyle] = {
    "micro_horror": {
        "topic_prompt": _micro_horror_topic_prompt,
        "uses_episode_hint": True,
        "default_target_seconds": 60.0,
        "subtract_outro_from_target": True,
        "min_target_floor_seconds": 40.0,
        "short_script_rules": """
        - Line 1 MUST be a cold-open hook that creates immediate dread (under 10 words)
        - Build tension sentence by sentence across the full runtime; save the twist for the final sentences
        - Psychological horror only — no excessive gore descriptions
        - End with a subtle CTA ("Follow for more 60 second thrillers" or similar)
        """,
        "short_length_instruction": _micro_horror_length_instruction,
        "enforce_min_word_count": True,
        "enforce_min_audio_duration": True,
        "min_audio_duration_ratio": 0.85,
        "music_keywords": ["dark", "cinematic", "ambient", "horror"],
        "max_target_ceiling_seconds": None,
        "enforce_max_word_count": False,
        "topic_candidate_count": 1,
        "title_candidate_count": 1,
        "title_rules": None,
        "max_audio_duration_seconds": None,
    },
    "practical_demo": {
        "topic_prompt": _practical_demo_topic_prompt,
        "uses_episode_hint": False,
        "default_target_seconds": 45.0,
        "subtract_outro_from_target": False,
        "min_target_floor_seconds": 0.0,
        "short_script_rules": None,
        "short_length_instruction": None,
        "enforce_min_word_count": False,
        "enforce_min_audio_duration": False,
        "min_audio_duration_ratio": 1.0,
        "music_keywords": None,
        "max_target_ceiling_seconds": None,
        "enforce_max_word_count": False,
        "topic_candidate_count": 1,
        "title_candidate_count": 1,
        "title_rules": None,
        "max_audio_duration_seconds": None,
    },
    "narrative_nonfiction": {
        "topic_prompt": _narrative_nonfiction_topic_prompt,
        "uses_episode_hint": False,
        "default_target_seconds": 75.0,
        "subtract_outro_from_target": True,
        "min_target_floor_seconds": 50.0,
        "short_script_rules": """
        - Line 1 MUST be a specific, concrete hook (a real name/date/number) — no "today we look at..."
        - Every claim must be presented as what actually happened — do not fictionalize or embellish facts
        - Close with a short, thought-provoking line connecting the fact to something the viewer recognizes today
        - End with a light CTA ("Follow for more strange-but-true history" or similar)
        """,
        "short_length_instruction": _narrative_nonfiction_length_instruction,
        "enforce_min_word_count": True,
        "enforce_min_audio_duration": True,
        "min_audio_duration_ratio": 0.85,
        "music_keywords": ["mysterious", "documentary", "ambient", "cinematic", "orchestral"],
        "max_target_ceiling_seconds": None,
        "enforce_max_word_count": False,
        "topic_candidate_count": 1,
        "title_candidate_count": 1,
        "title_rules": None,
        "max_audio_duration_seconds": None,
    },
    "weird_history": {
        "topic_prompt": _weird_history_topic_prompt,
        "uses_episode_hint": False,
        # 50-60s target band (mid-point default); see
        # _weird_history_length_instruction for the words-per-minute math
        # and how to safely retune these if overridden per-brand.
        "default_target_seconds": 55.0,
        "subtract_outro_from_target": True,
        "min_target_floor_seconds": 45.0,
        "short_script_rules": """
        - First line MUST state the FULL absurd outcome as a flat declarative fact, under 15
          words, verdict first (e.g. "In 1457, a pig was tried and executed for murder.") —
          zero setup or throat-clearing; the viewer must grasp the twist premise in 3 seconds
        - Follow with one line acknowledging it sounds fake but is documented/real
        - Structure as ONE setup paying off ONE punchline — never a list of loosely related facts
        - Set up with 2-3 specific factual beats (real names/dates/numbers) — never fictionalize
        - Deliver the punchline — the strangest twist or outcome — in the final ~10 seconds
        - End with exactly ONE dry, deadpan Archivist-style sign-off line, not a hype CTA
        - Tone: dry-witted documentary narrator, curious not cringe — no fake-horror voice,
          no exaggerated hype, no "you won't believe what happened next"
        """,
        "short_length_instruction": _weird_history_length_instruction,
        "enforce_min_word_count": True,
        "enforce_min_audio_duration": True,
        "min_audio_duration_ratio": 0.85,
        "music_keywords": ["mysterious", "documentary", "ambient", "cinematic", "orchestral"],
        # Script-length ceiling on narration (~70s) — kept below the hard
        # 75s audio gate so a slightly slow TTS read still clears it.
        "max_target_ceiling_seconds": 70.0,
        "enforce_max_word_count": True,
        # Generate a few candidate topics/titles and keep the highest-scored
        # one (see topic_scoring.py) — favors specificity, numbers, and
        # absurd contrast over the first draft the LLM happens to produce.
        "topic_candidate_count": 3,
        "title_candidate_count": 3,
        "title_rules": """
- The title MUST contain at least one specific number (a year, a count, or a quantity)
- The title MUST pair that number with an absurd conflict or outcome, stated plainly —
  the number and the absurdity colliding is what earns the click
- Best-performer examples to match in shape (not topic):
  "How Liechtenstein Sent 80 Men to War in 1866 and Returned with 81"
  "How Cherries Made Millard Fillmore President in 1850"
""",
        # Hard gate on real voiceover length: reject + retry shorter, and
        # abort (never upload) if the narration still runs past this.
        "max_audio_duration_seconds": 75.0,
    },
}

DEFAULT_STYLE_NAME = "practical_demo"

# Maps a manifest's `content_type` to a style name. Brands with an
# unrecognized or missing `content_type` fall back to DEFAULT_STYLE_NAME.
CONTENT_TYPE_TO_STYLE = {
    "horror": "micro_horror",
    "history": "narrative_nonfiction",
}


def resolve_style_name(brand: dict) -> str:
    """Pick a style name for a brand manifest — explicit override first,
    then `content_type` mapping, then the generic default."""
    production = brand.get("production", {}) or {}
    explicit = production.get("content_style")
    if explicit and explicit in CONTENT_STYLES:
        return explicit

    content_type = brand.get("content_type", "")
    return CONTENT_TYPE_TO_STYLE.get(content_type, DEFAULT_STYLE_NAME)


def get_content_style(brand: Optional[dict] = None) -> ContentStyle:
    """Get the resolved content style for a brand (defaults to the active brand)."""
    if brand is None:
        from brand_switcher import load_active_brand

        brand = load_active_brand()
    return CONTENT_STYLES[resolve_style_name(brand)]
