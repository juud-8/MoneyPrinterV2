# Configuration

All your configurations will be in a file in the root directory, called `config.json`, which is a copy of `config.example.json`. You can change the values in `config.json` to your liking.

## Values

- `verbose`: `boolean` - If `true`, the application will print out more information.
- `firefox_profile`: `string` - The path to your Firefox profile. This is used to use your Social Media Accounts without having to log in every time you run the application.
- `headless`: `boolean` - If `true`, the application will run in headless mode. This means that the browser will not be visible.
- `ollama_base_url`: `string` - Base URL of your local Ollama server (default: `http://127.0.0.1:11434`).
- `ollama_model`: `string` - Ollama model to use for text generation (e.g. `llama3.2:3b`). If empty, the app queries Ollama at startup and lets you pick from the available models interactively.
- `twitter_language`: `string` - The language that will be used to generate & post tweets.
- `nanobanana2_api_base_url`: `string` - Nano Banana 2 API base URL (default: `https://generativelanguage.googleapis.com/v1beta`).
- `nanobanana2_api_key`: `string` - API key for Nano Banana 2 (Gemini image API). If empty, MPV2 falls back to environment variable `GEMINI_API_KEY`.
- `nanobanana2_model`: `string` - Nano Banana 2 model name (default: `gemini-3.1-flash-image-preview`).
- `nanobanana2_aspect_ratio`: `string` - Aspect ratio for generated images (default: `9:16`).
- `threads`: `number` - The amount of threads that will be used to execute operations, e.g. writing to a file using MoviePy.
- `is_for_kids`: `boolean` - If `true`, the application will upload the video to YouTube Shorts as a video for kids.
- `google_maps_scraper`: `string` - The URL to the Google Maps scraper. This will be used to scrape Google Maps for local businesses. It is recommended to use the default value.
- `zip_url`: `string` - The URL to the ZIP file that contains the to be used Songs for the YouTube Shorts Automater.
- `email`: `object`:
    - `smtp_server`: `string` - Your SMTP server.
    - `smtp_port`: `number` - The port of your SMTP server.
    - `username`: `string` - Your email address.
    - `password`: `string` - Your email password.
- `google_maps_scraper_niche`: `string` - The niche you want to scrape Google Maps for.
- `scraper_timeout`: `number` - The timeout for the Google Maps scraper.
- `outreach_message_subject`: `string` - The subject of your outreach message. `{{COMPANY_NAME}}` will be replaced with the company name.
- `outreach_message_body_file`: `string` - The file that contains the body of your outreach message, should be HTML. `{{COMPANY_NAME}}` will be replaced with the company name.
- `stt_provider`: `string` - Provider for subtitle transcription. Default is `local_whisper`. Options:
    * `local_whisper`
    * `third_party_assemblyai`
- `whisper_model`: `string` - Whisper model for local transcription (for example `base`, `small`, `medium`, `large-v3`).
- `whisper_device`: `string` - Device for local Whisper (`auto`, `cpu`, `cuda`).
- `whisper_compute_type`: `string` - Compute type for local Whisper (`int8`, `float16`, etc.).
- `assembly_ai_api_key`: `string` - Your Assembly AI API key. Get yours from [here](https://www.assemblyai.com/app/).
- `tts_voice`: `string` - Voice for KittenTTS text-to-speech. Default is `Jasper`. Options: `Bella`, `Jasper`, `Luna`, `Bruno`, `Rosie`, `Hugo`, `Kiki`, `Leo`.
- `font`: `string` - The font that will be used to generate images. This should be a `.ttf` file in the `fonts/` directory.
- `imagemagick_path`: `string` - The path to the ImageMagick binary. This is used by MoviePy to manipulate images. Install ImageMagick from [here](https://imagemagick.org/script/download.php) and set the path to the `magick.exe` on Windows, or on Linux/MacOS the path to `convert` (usually /usr/bin/convert).
- `script_sentence_length`: `number` - The number of sentences in the generated video script (default: `4`).
- `post_bridge`: `object`:
    - `enabled`: `boolean` - Enables Post Bridge cross-posting after successful YouTube uploads.
    - `api_key`: `string` - Your Post Bridge API key. If empty, MPV2 falls back to `POST_BRIDGE_API_KEY`.
    - `platforms`: `string[]` - Platforms to target. Supported values in v1 are `tiktok` and `instagram`.
    - `account_ids`: `number[]` - Optional fixed Post Bridge account IDs to avoid account-selection prompts.
    - `auto_crosspost`: `boolean` - If `true`, cross-post automatically after a successful YouTube upload. If `false`, interactive runs ask and cron runs skip.
- `youtube_api_key`: `string` - Google Cloud API key with **YouTube Data API v3** enabled, used by `src/youtube_metrics.py` and the web UI's "Refresh YouTube metrics" button to pull public view/like/comment counts and channel subscriber snapshots into `.mp/analytics.json`. Note: AI Studio Gemini keys do **not** work here — create a standard API key in Google Cloud Console ([enable the API](https://console.cloud.google.com/apis/library/youtube.googleapis.com), then [create credentials](https://console.cloud.google.com/apis/credentials)). Falls back to the `YOUTUBE_API_KEY` environment variable.
- `premium_image_model`: `string` - Gemini image model used for the `premium_image` asset tier (thumbnails, and any shot a brand opts into premium stills).
- `standard_image_provider`: `string` - Provider for standard-tier still images: `gemini` (default) or `fal`. `fal` routes every standard shot to the much cheaper fal.ai image model (`fal_image_model`) and falls back to Gemini on failure; the `premium_image` tier always stays on Gemini. Brands can override via `production.standard_image_provider`.
- `fal_image_model`: `string` - fal.ai model id for standard-tier still images when `standard_image_provider` is `fal` (default: `fal-ai/flux/schnell`, roughly $0.003/image vs ~$0.067 for Gemini stills). Verify against fal.ai's current catalog/pricing before changing.
- `fal_api_key`: `string` - Your fal.ai API key, used for the `premium_video` asset tier and (when `standard_image_provider` is `fal`) standard still images. If empty, MPV2 falls back to the `FAL_KEY` environment variable. Premium video is off by default for every brand — see [the brand setup guide](../brands/ACCOUNT_SETUP.md) to opt in.
- `fal_video_model`: `string` - fal.ai model id for premium video clips (default: `fal-ai/veo3.1/fast`, $0.10/s vs $0.20/s for full Veo 3.1). Verify against fal.ai's current catalog/pricing before changing.
- `fal_video_resolution`: `string` - Resolution requested from the fal.ai video model (default: `1080p`).
- `fal_video_poll_timeout_seconds`: `number` - Max seconds to wait for a fal.ai video generation job before giving up and falling back to a premium still image.
- `premium_video_max_duration_seconds`: `number` - Hard cap on a single premium video clip's requested duration (cost control; default: `6`).
- `asset_spend_alert_threshold_usd`: `number` - Informational threshold: the weekly analytics review warns if recent (7-day) premium asset spend exceeds this (default: `25`). Does not block generation.
- `fishaudio_api_key`: `string` - Fish Audio API key, used when `tts_provider` is `fishaudio` (~$15 per 1M characters — roughly 90% cheaper than ElevenLabs). If empty, MPV2 falls back to the `FISH_AUDIO_API_KEY` environment variable.
- `fishaudio_voice_id`: `string` - Fish Audio voice model reference id (create/clone a voice at [fish.audio](https://fish.audio)). Brands can override via `production.fishaudio_voice_id`.
- `fishaudio_model`: `string` - Fish Audio TTS model (default: `s2-pro`). On failure, MPV2 falls back to ElevenLabs (if configured) and then KittenTTS.

## Example

```json
{
  "verbose": true,
  "firefox_profile": "",
  "headless": false,
  "ollama_base_url": "http://127.0.0.1:11434",
  "ollama_model": "",
  "twitter_language": "English",
  "nanobanana2_api_base_url": "https://generativelanguage.googleapis.com/v1beta",
  "nanobanana2_api_key": "",
  "nanobanana2_model": "gemini-3.1-flash-image-preview",
  "nanobanana2_aspect_ratio": "9:16",
  "threads": 2,
  "zip_url": "",
  "is_for_kids": false,
  "google_maps_scraper": "https://github.com/gosom/google-maps-scraper/archive/refs/tags/v0.9.7.zip",
  "email": {
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "username": "",
    "password": ""
  },
  "google_maps_scraper_niche": "",
  "scraper_timeout": 300,
  "outreach_message_subject": "I have a question...",
  "outreach_message_body_file": "outreach_message.html",
  "stt_provider": "local_whisper",
  "whisper_model": "base",
  "whisper_device": "auto",
  "whisper_compute_type": "int8",
  "assembly_ai_api_key": "",
  "tts_voice": "Jasper",
  "font": "bold_font.ttf",
  "imagemagick_path": "Path to magick.exe or on linux/macOS just /usr/bin/convert",
  "script_sentence_length": 4,
  "post_bridge": {
    "enabled": false,
    "api_key": "",
    "platforms": ["tiktok", "instagram"],
    "account_ids": [],
    "auto_crosspost": false
  }
}
```

## Environment Variable Fallbacks

- `GEMINI_API_KEY`: used when `nanobanana2_api_key` is empty.
- `YOUTUBE_API_KEY`: used when `youtube_api_key` is empty.
- `POST_BRIDGE_API_KEY`: used when `post_bridge.api_key` is empty.
- `FAL_KEY`: used when `fal_api_key` is empty.
- `FISH_AUDIO_API_KEY`: used when `fishaudio_api_key` is empty.

Example:

```bash
export GEMINI_API_KEY="your_api_key_here"
export POST_BRIDGE_API_KEY="your_post_bridge_api_key_here"
```

See [PostBridge.md](./PostBridge.md) for the full Post Bridge setup and behavior details.
