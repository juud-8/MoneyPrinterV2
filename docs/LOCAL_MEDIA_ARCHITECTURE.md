# Local media architecture

## Purpose and audited baseline

This document records the MoneyPrinterV2 local-media architecture as it exists
on branch `codex/sunobuild`. The committed comparison point for this audit is
`2ba00b5` (`Stop transient Ollama probe failures from pinning SYSTEMS:
CRITICAL`). Archive Song is present as uncommitted work layered over that
commit. It must not be discarded or treated as part of the committed base.

This phase adds provider-neutral contracts and an adapter seam. It does not
install or integrate Voicebox, ACE-Step, or LongLive, and it does not route the
existing production pipeline through the new registry.

## Runtime entry points and control flow

The primary interactive entry point is [`main()`](../src/main.py#L104). It
resolves the active brand/account, constructs `TTS` and `YouTube`, generates a
video, and asks separately whether to upload. Brand selection is handled by
[`run_switch_brand_menu()`](../src/main.py#L34).

The principal non-interactive entry points are:

- [`scripts/run_brand_short.py`](../scripts/run_brand_short.py#L23), whose
  parser supports narration or Archive Song, resume, and an explicit `--upload`
  flag. [`main()`](../scripts/run_brand_short.py#L62) generates locally unless
  that flag is present.
- [`scripts/run_brand_longform.py`](../scripts/run_brand_longform.py#L17), which
  uses the same `YouTube`/`TTS` objects for long-form generation.
- [`src/cron.py`](../src/cron.py#L22), the scheduled flow.
- [`src/webui.py`](../src/webui.py#L319), whose generation API launches the
  brand runner and only includes `--upload` when the caller explicitly asks.
- [`scripts/upload_brand_short.py`](../scripts/upload_brand_short.py#L28), an
  explicit upload-only path for an existing local file.

For both normal and Archive Song generation,
[`YouTube.generate_video()`](../src/classes/YouTube.py#L2118) selects Short
format and enters [`_generate_pipeline()`](../src/classes/YouTube.py#L1982).
That function dispatches to
[`_generate_archive_song_pipeline()`](../src/classes/YouTube.py#L1686) only when
the normalized audio mode is `archive_song`; otherwise it runs the historical
narration flow.

## Configuration and precedence

`src/config.py` reads `config.json` on demand rather than maintaining one
validated configuration object. Relevant selectors include
[`get_tts_provider()`](../src/config.py#L388),
[`get_stt_provider()`](../src/config.py#L245), and the ElevenLabs getters at
[`get_elevenlabs_api_key()`](../src/config.py#L393),
[`get_elevenlabs_voice_id()`](../src/config.py#L398), and
[`get_elevenlabs_model()`](../src/config.py#L412). API-key getters generally use
`config.json` first and their documented environment variable second. The
ElevenLabs voice ID uses the active brand's `production.elevenlabs_voice_id`
before the global value; the provider and model remain global settings.

Brand manifests live at `brands/<brand_id>/manifest.json`. The audit found one
manifest, but account-identifying values are intentionally not reproduced
here. Active-brand resolution in
[`get_active_brand_id()`](../src/brand_switcher.py#L88) is:

1. `.mp/active_brand.json`, when valid;
2. the legacy/global `channel_config_file` setting;
3. the default brand ID when its manifest exists;
4. the first discovered manifest;
5. the default ID as a final fallback.

[`load_active_brand()`](../src/brand_switcher.py#L135) loads the full manifest.
[`get_production_setting()`](../src/brand_switcher.py#L144) reads a brand-only
override, while [`get_effective_setting()`](../src/brand_switcher.py#L154)
implements selected brand-then-global fallbacks. Generic engine code therefore
does not need a brand-ID conditional.

Archive Song has a deliberately explicit merge implemented by
[`resolve_archive_song_settings()`](../src/archive_song_settings.py#L161):
engine defaults, then global `config.json` `archive_song`, then manifest
`production.archive_song`, then episode package values, then CLI overrides.
[`load_resolved_archive_song_settings()`](../src/archive_song_settings.py#L215)
connects that merge to the current config. Missing global or brand Archive Song
blocks resolve to conservative engine defaults.

## Narration providers

[`TTS`](../src/classes/Tts.py#L26) is the existing narration dispatcher:

- KittenTTS is the default local provider and writes 24 kHz audio with
  `soundfile`.
- [`_synthesize_elevenlabs()`](../src/classes/Tts.py#L36) makes the current REST
  request, applies the existing fixed voice settings, writes returned MP3 bytes,
  and records `last_provider_used`/`last_model_used`.
- Fish Audio is another remote provider and writes returned MP3 bytes.
- [`synthesize()`](../src/classes/Tts.py#L128) preserves the current fallback
  chain: Fish Audio to ElevenLabs when configured, then KittenTTS; or
  ElevenLabs directly to KittenTTS. Pilot mode disables Kitten fallback unless
  `MPV2_ALLOW_KITTEN_TTS_FALLBACK=1` is deliberately set.

The narration pipeline sanitizes the script, chooses a temporary `.wav` path,
and calls `tts_instance.synthesize()` in
[`generate_script_to_speech()`](../src/classes/YouTube.py#L883). The provider may
return an MP3 path instead. The returned path is authoritative, and later
stages read it through MoviePy. Provider/model labels are copied into
`production_metadata`; they do not affect rendering.

There is no common narration protocol in the historical path. The additive
[`ElevenLabsNarrationAdapter`](../src/media_providers/elevenlabs_adapter.py#L34)
now implements the new `AudioProvider` contract by calling the same legacy
method. Existing callers still use `TTS.synthesize()` directly, so narration
defaults, output naming, and fallback behavior are unchanged.

## Audio validation and normalization

Normal narration has no shared post-synthesis validation/normalization stage.
MoviePy decodes whatever path the provider returns, resamples it while
compositing, and the duration gates in `YouTube` may regenerate or shorten the
script. Narration is mixed with a low-volume track from `Songs/` during
[`combine()`](../src/classes/YouTube.py#L1077).

Archive Song uses a stricter local boundary. The operator-owned WAV/MP3 is
discovered but never overwritten. [`validate_and_normalize_audio()`](../src/archive_song.py#L696)
checks existence, supported format, decoding, duration, sample rate, channels,
peak, and leading/trailing silence, then invokes FFmpeg to create a separate
44.1 kHz stereo PCM `production_audio.wav`. Duration violations are blocking
unless the operator explicitly uses the validation override. The combined
Archive Song video uses this complete musical mix and does not add the normal
background track.

## Captioning and transcription

[`generate_subtitles()`](../src/classes/YouTube.py#L933) selects the configured
STT path:

- [`generate_subtitles_local_whisper()`](../src/classes/YouTube.py#L994) lazily
  imports `faster-whisper`, instantiates the configured model/device/compute
  type, uses VAD, and writes SRT.
- [`generate_subtitles_assemblyai()`](../src/classes/YouTube.py#L954) uses the
  remote AssemblyAI client and writes exported SRT.
- An unknown selector logs a warning and falls back to local Whisper.

Normal narration SRT is equalized and rendered either as animated word
captions from [`video_captions.py`](../src/video_captions.py#L59) or as MoviePy
block subtitles. Archive Song tries local Whisper only as a timing hint for
sung lyrics; failure is non-fatal. [`build_lyric_alignment()`](../src/archive_song.py#L864)
creates a labeled proportional phrase fallback, and the editable alignment/SRT
is checkpointed. Archive-specific lyric highlighting and short full-screen beat
text are implemented in [`video_captions.py`](../src/video_captions.py#L128).

Voicebox transcription is not implemented. A future adapter should reuse the
same SRT/alignment boundary rather than coupling caption rendering to Voicebox
internals.

## Visual generation and continuity

Normal visual prompts are generated from the script, then each shot is assigned
a brand-configurable tier by [`asset_strategy.py`](../src/asset_strategy.py#L29).
[`generate_asset_with_fallback()`](../src/asset_gen.py#L359) degrades
`premium_video -> premium_image -> standard`. Standard/premium images are
generated by Gemini or fal.ai; premium clips use fal.ai. Every call returns the
existing lightweight `AssetResult` containing path, modality, tier, estimated
cost, and provider.

Archive Song builds a time-aware shot plan in
[`build_archive_shot_plan()`](../src/archive_song_visuals.py#L378), using the
normalized beat map, historical fact, period, source IDs, visual suggestion,
camera motion, and per-shot duration. Missing or malformed timing falls back to
equal-duration lyric prompts. [`_generate_archive_assets()`](../src/classes/YouTube.py#L1554)
copies each completed asset into the episode checkpoint before continuing.

Current continuity is prompt-level only: brand style suffixes, shot ordering,
camera-motion text, and optional Ken Burns/crossfade effects. There is no typed
character/location/style bible, reference-frame lineage, or cross-shot identity
constraint. A LongLive-inspired planner can be added before
[`_generate_shot_asset()`](../src/classes/YouTube.py#L1267) and can record parent
artifact hashes in shared provenance. A future LongLive worker should remain a
separate process/environment and conform through `VideoProvider`; MoneyPrinter
should not import that repository's internals.

## Archive Song checkpoints and state

Archive Song is a manual Suno handoff; the repository contains no Suno client.
Its durable episode directory is `output/<brand-id>/episodes/<episode-id>/`.
The state schema in [`ArchiveSongState`](../src/archive_song.py#L342) records
research, approved script, validated song package, settings, imported and
normalized audio, timing/alignment files, generated assets, render path, and
errors. [`save_state()`](../src/archive_song.py#L478) and
[`load_state()`](../src/archive_song.py#L491) persist and validate the versioned
JSON checkpoint.

The current state progression is `created -> awaiting_song_audio ->
audio_ready -> assets_ready -> rendered`, with `invalid_song_audio` on a
validation failure. Package generation validates LLM JSON up to three times.
Resume reuses valid research/package/audio/alignment/assets/render checkpoints.
Replacing the imported song invalidates audio-dependent artifacts.

[`compute_file_identity()`](../src/archive_song.py#L391) retains the existing
absolute path, byte size, nanosecond mtime, and SHA-256 shape. Its digest now
uses the shared [`sha256_file()`](../src/media_providers/provenance.py#L36), so
the provider foundation does not create a competing hash implementation.

ACE-Step is not implemented. Its future adapter should return typed
`SongCandidate` records and must preserve explicit human candidate selection
and approval before any result becomes the episode's imported song.

## Rendering and upload boundary

[`combine()`](../src/classes/YouTube.py#L1077) turns stills/clips into a 1080x1920,
30 fps MoviePy composition, fits each shot to the narration/song duration,
adds captions, selects the correct audio-mix behavior, optionally appends the
brand outro, and writes a temporary MP4. Normal generation copies that render
to brand output; Archive Song copies it to the durable episode checkpoint.

Generation and upload are separate operations. The only live YouTube mutation
is [`upload_video()`](../src/classes/YouTube.py#L2480), which uses Selenium.
Callers must opt into upload and pass
[`should_proceed_with_upload()`](../src/review_gate.py#L11). That gate combines
global and manifest `review_before_upload`, interactive approval, and stricter
pilot confirmation. The new provider package has no upload/publish methods.

## Retry, fallback, and cache behavior

- Research retries a new topic for retryable grounding failures; preset topics
  do not silently change.
- Archive Song package parsing retries malformed/untrusted LLM output three
  times.
- Gemini image generation retries rate limits with exponential backoff; tiered
  assets fall back to cheaper modalities.
- TTS has the provider fallback chain described above. The new ElevenLabs
  adapter deliberately does not add another fallback layer.
- Normal account/video cache lives in `.mp/*.json`; analytics uses separate
  persisted data. Tests that touch these paths must patch cache locations.
- Archive Song episode checkpoints are the only durable media-generation resume
  cache. They use content/file hashes to decide whether derived outputs remain
  valid.
- There is no shared request-result provider cache, background job protocol, or
  generalized retry scheduler yet. `retry_count` and `fallback_behavior` in
  provenance make those future decisions auditable without implementing them
  in this phase.

## Shared provider foundation

The additive package [`src/media_providers`](../src/media_providers) contains:

- typed health, capability, request/result, voice, song, video, provenance, and
  registry-entry records in [`contracts.py`](../src/media_providers/contracts.py#L1);
- `AudioProvider`, `SongProvider`, and `VideoProvider` structural protocols;
- stable provider error categories in
  [`errors.py`](../src/media_providers/errors.py#L1);
- the thread-safe in-process [`ProviderRegistry`](../src/media_providers/registry.py#L15);
- canonical hashes and [`create_asset_provenance()`](../src/media_providers/provenance.py#L87);
- the non-invasive ElevenLabs adapter and a lazy registry-entry factory.

The registry contains no global registrations. Importing the package does not
instantiate a model, probe a network, or change the selected provider. External
workers should be integrated through factories/adapters at an explicit
composition root in a later phase.

## Local processes and external service status at audit time

On 2026-07-15, the read-only process audit found Ollama running locally and
several MoneyPrinter Python/FFmpeg processes. `requirements.txt` includes
KittenTTS and `faster-whisper`; those models load only when their current paths
are invoked. No Voicebox, ACE-Step, LongLive, or matching worker process was
found. `nvidia-smi` was not available through the audited shell, so this audit
does not claim a CUDA device or driver status. No process was stopped or
modified.

The repository's operational health checks in
[`provider_health.py`](../src/provider_health.py#L315) cover current API quota,
credential presence, songs, and browser-profile locks. They are distinct from
the provider-neutral `ProviderHealth` contract: operational checks may adapt
their result into the contract later, but they are not replaced here.

## Test coverage and known seams

Existing offline coverage includes configuration/brand resolution, asset
strategy and fallback, provider-health helpers, render/upload helpers, and the
large Archive Song contract/invalidation/CLI/dry-run suite. New coverage in
[`tests/test_media_providers.py`](../tests/test_media_providers.py#L1) validates
contracts, registry behavior, provenance JSON, Windows paths, health states,
unknown/disabled/misconfigured providers, legacy ElevenLabs calls, unchanged
TTS dispatch/fallback, and Archive Song hash compatibility.

The Selenium/MoviePy end-to-end pipeline still has no automated media-quality
oracle. Future Voicebox/ACE-Step/LongLive work therefore needs offline adapter
tests plus an explicit, operator-run dry-run before any production use.
