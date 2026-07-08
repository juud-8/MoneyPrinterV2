# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MoneyPrinterV2 (MPV2) is a Python 3.12 CLI tool that automates four online workflows:
1. **YouTube Shorts** — generate video (LLM script → TTS → images → MoviePy composite) and upload via Selenium
2. **Twitter/X Bot** — generate and post tweets via Selenium
3. **Affiliate Marketing** — scrape Amazon product info, generate pitch, share on Twitter
4. **Local Business Outreach** — scrape Google Maps (Go binary), extract emails, send cold outreach via SMTP

There is no web UI, no REST API, no CI, and no linting config. There is a small `tests/` suite (`python -m unittest discover -s tests`) covering pure-logic modules (config parsing, brand resolution, content styles, asset strategy/fallback, Post Bridge) — not the Selenium/MoviePy pipeline itself.

The app is also used as a personal, multi-brand content factory (see "Multi-Brand System" below) — `brands/<brand_id>/` holds brand-specific manifests, assets, and scripts that are gitignored/private-by-convention; the engine code itself should never reference a specific brand by name or id.

## Running the Application

```bash
# First-time setup
cp config.example.json config.json   # then fill in values
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# macOS quick setup (auto-configures Ollama, ImageMagick, Firefox profile)
bash scripts/setup_local.sh

# Preflight check (validates services are reachable)
python scripts/preflight_local.py

# Run
python src/main.py
```

The app **must** be run from the project root. `python src/main.py` adds `src/` to `sys.path`, so all imports use bare module names (e.g., `from config import *`, not `from src.config import *`).

## Architecture

### Entry Points
- `src/main.py` — interactive menu loop (primary)
- `src/cron.py` — headless runner invoked by the scheduler as a subprocess: `python src/cron.py <platform> <account_uuid>`

### Provider Pattern
Several service categories use a string-based dispatch pattern configured in `config.json` (and overridable per-brand in `brands/<id>/manifest.json` → `production`):

| Category | Config key | Options |
|---|---|---|
| LLM (default) | `llm_provider` | `ollama` (local, via `ollama` Python SDK) or `gemini` |
| LLM (quality — topic/script/title/metadata) | `quality_llm_provider` | Same options; `generate_text(..., quality=True)` uses this. Falls back to Ollama if Gemini fails. |
| TTS | `tts_provider` | `kittentts` (local), `elevenlabs`, or `fishaudio` (Fish Audio, ~90% cheaper; fallback chain fishaudio → elevenlabs → kittentts) |
| Image gen (standard tier) | `standard_image_provider` | `gemini` ("Nano Banana 2", `nanobanana2_model`) or `fal` (`fal_image_model`, FLUX schnell by default — ~20x cheaper, falls back to Gemini on failure) |
| Image gen (premium tier) | — | Always Gemini (`premium_image_model`) |
| Video clip gen (premium, opt-in) | `fal_video_model` | fal.ai (defaults to `fal-ai/veo3.1/fast`) — see "Asset Tiers" below |
| STT | `stt_provider` | `local_whisper`, `third_party_assemblyai` |

Ollama must be running locally for any Ollama use; Gemini/ElevenLabs/Fish Audio/fal.ai need API keys in `config.json` (or their respective env vars: `GEMINI_API_KEY`, `ELEVENLABS_API_KEY`, `FISH_AUDIO_API_KEY`, `FAL_KEY`).

### Multi-Brand System
A "brand" is a YouTube channel + niche + voice + visual style + funnel, described entirely by data — the engine never branches on a brand's name or id.

- **`brands/<brand_id>/manifest.json`** — one folder per brand (e.g. `brands/panorama_productions/`, `brands/sixty_second_thrillers/`). Each manifest sets `niche`, `firefox_profile`, `content_type`, `production` overrides (voice id, target duration, image style, outro clip, `asset_strategy`), and `funnel` (affiliate/lead-magnet links).
- **`src/brand_switcher.py`** — resolves/persists the active brand (`.mp/active_brand.json`), links a brand to a cached YouTube account (`brand_id` field in `.mp/youtube.json`), and exposes `get_production_setting()`/`get_effective_setting()` for per-brand overrides with `config.json` fallback.
- **`src/content_styles.py`** — content-shape profiles (hook style, pacing rules, minimum-length enforcement, music mood) keyed by a generic style name (`micro_horror`, `practical_demo`), selected via a brand's `content_type` or an explicit `production.content_style` override. Adding a brand with an existing content shape needs zero engine code changes.
- **`src/channel_branding.py`** / **`src/content_funnel.py`** — read the active brand for niche/funnel data and build monetized YouTube descriptions (affiliate link → disclosure → body → lead magnet → tagline → hashtags).

### Asset Tiers (premium image/video generation)
Every shot in a video defaults to a "standard" Gemini still image. A brand can opt specific shots into a premium tier via `production.asset_strategy` in its manifest (e.g. `{"hook": "premium_video"}`) — today only the `hook` (first shot) and `default` (everything else) roles are recognized; this is an intentional pilot scope.

- **`src/asset_gen.py`** — generates images (Gemini, `standard`/`premium_image` tiers) and short video clips (fal.ai, `premium_video` tier — defaults to Veo 3.1). `generate_asset_with_fallback()` tries the requested tier and falls back down the chain (`premium_video` → `premium_image` → `standard`) on failure/timeout so a flaky premium provider never blocks a run.
- **`src/asset_strategy.py`** — resolves which tier a shot role should use, merging brand manifest config over engine defaults (default is `"standard"` everywhere — zero risk/zero cost unless a brand opts in).
- Premium asset spend is logged to `.mp/analytics.json` (`analytics.log_asset_spend()`) and surfaced in the weekly review (`analytics.print_weekly_review()`), with an informational threshold alert (`asset_spend_alert_threshold_usd`) — not a hard budget cap.

### Key Modules
- **`src/llm_provider.py`** — unified `generate_text(prompt, quality=False)` across Ollama/Gemini
- **`src/asset_gen.py`** / **`src/asset_strategy.py`** — tiered image/video asset generation (see above)
- **`src/content_styles.py`** — brand-agnostic content-shape profiles (see above)
- **`src/config.py`** — 40+ getter functions, each re-reads `config.json` on every call (no caching). `ROOT_DIR` = project root, computed as `os.path.dirname(sys.path[0])`
- **`src/brand_switcher.py`** — multi-brand resolution/switching (see above)
- **`src/cache.py`** — JSON file persistence in `.mp/` directory (accounts, videos, posts, products)
- **`src/analytics.py`** — append-only video + premium-asset-spend log (`.mp/analytics.json`) for manual weekly review
- **`src/review_gate.py`** — optional human approval prompt before upload (`review_before_upload`)
- **`src/post_bridge_integration.py`** / **`src/classes/PostBridge.py`** — optional cross-post of a successful YouTube upload to TikTok/Instagram via the Post Bridge API
- **`src/video_effects.py`** / **`src/video_captions.py`** — Ken Burns pan/zoom + crossfades, and word-by-word animated captions
- **`src/constants.py`** — menu strings, Selenium selectors (YouTube Studio, X.com, Amazon)
- **`src/classes/YouTube.py`** — most complex class; full pipeline: topic → script → metadata → per-shot asset tier selection → images/video clips → TTS → subtitles → MoviePy combine → Selenium upload
- **`src/classes/Twitter.py`** — Selenium automation against x.com
- **`src/classes/AFM.py`** — Amazon scraping + LLM pitch generation
- **`src/classes/Outreach.py`** — Google Maps scraper (requires Go) + email sending via yagmail
- **`src/classes/Tts.py`** — KittenTTS (local) / ElevenLabs (cloud) wrapper

### Data Storage
All persistent state lives in `.mp/` at the project root as JSON files (`youtube.json`, `twitter.json`, `afm.json`, `analytics.json`, `active_brand.json`). This directory also serves as scratch space for temporary WAV, PNG, MP4 (including generated premium video clips), and SRT files — non-JSON files are cleaned on each run by `rem_temp_files()`. Finished videos are additionally copied to `output/<brand_id>/` (gitignored) so they survive that cleanup.

### Browser Automation
Selenium uses pre-authenticated Firefox profiles (never handles login). The profile path is stored per-brand in the manifest and per-account in the cache JSON. The YouTube Studio upload flow (`classes/YouTube.py::upload_video`) is the most fragile part of the codebase — it drives the Studio UI via hardcoded selectors and will break silently if YouTube changes its DOM; `_require_elements()` asserts expected element counts before indexing so failures are loud and specific instead of a bare `IndexError`.

### CRON Scheduling
Uses Python's `schedule` library (in-process, not OS cron) for the interactive menu's "Setup CRON Job" option, spawning `subprocess.run(["python", "src/cron.py", platform, account_id, model, brand_id])`. For unattended daily production, brand-pinned scripts under `brands/<brand_id>/` (e.g. a `run_daily.ps1` + `scheduled_run.py`) are driven by the OS's own scheduler (Windows Task Scheduler) instead — they call `brand_switcher.switch_brand()` explicitly rather than relying on whatever brand is currently active.

## Configuration

All config lives in `config.json` at the project root (gitignored — never commit real keys). See `config.example.json` for the full template and `docs/Configuration.md` for reference. Key external dependencies to configure:
- **ImageMagick** — required for MoviePy subtitle rendering (`imagemagick_path`)
- **Firefox profile** — must be pre-logged-in to target platforms (`firefox_profile`, or per-brand in its manifest)
- **Ollama** — for local LLM text generation (via `ollama` Python SDK)
- **Gemini** — for quality LLM generation and all image generation (`gemini_api_key`/`nanobanana2_api_key`)
- **ElevenLabs** — optional, for cloud TTS (`elevenlabs_api_key`)
- **fal.ai** — optional, only needed if a brand opts into `premium_video` shots (`fal_api_key` / `FAL_KEY` env var)
- **Go** — only needed for Outreach (Google Maps scraper)

## Contributing

PRs go against `main`. One feature/fix per PR. Open an issue first. Use `WIP` label for in-progress PRs.
