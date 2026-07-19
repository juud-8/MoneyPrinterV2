# Archive Song episodes

Archive Song is an optional audio mode for source-backed historical Shorts. It
uses the normal research and script stages, creates a validated songwriting
package, and stops at a manual Suno handoff. The repository does not call,
scrape, or automate Suno.

## Create the package

Choose a stable episode identifier so the same command finds its checkpoint:

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\venv\Scripts\python.exe scripts\run_brand_short.py the_strange_archive `
  --audio-mode archive-song `
  --episode dancing-plague-1518 `
  --topic "The Dancing Plague of 1518"
```

The successful first phase exits with `STATUS: awaiting_song_audio` and prints
the episode directory and exact resume command. No visual assets are generated
before this pause. Durable files live under:

```text
output/<brand-id>/episodes/<episode-id>/
```

The directory contains `song_package.json`, `lyrics.txt`, `suno_prompt.txt`,
`pronunciations.json`, `visual_beat_map.json`, `fact_check.json`,
`research_brief.json`, `approved_script.txt`, `README_SUNO.md`, and
`archive_song_state.json`. Suggested publication metadata is also checkpointed
as `metadata.json`.

Review the script, lyrics, pronunciations, claim mappings, and uncertainty
warnings. To deliberately replace only the song package while keeping its
approved research and script:

```powershell
.\venv\Scripts\python.exe scripts\run_brand_short.py the_strange_archive `
  --audio-mode archive-song --episode dancing-plague-1518 `
  --regenerate-song-package
```

## Manual Suno handoff and resume

1. Open Suno manually.
2. Paste `lyrics.txt` into its lyrics field.
3. Paste `suno_prompt.txt` into its style/instructions field.
4. Generate multiple candidates.
5. Choose the clearest factual performance and verify pronunciations.
6. Export it as WAV or MP3.
7. Put it in the episode directory as `song.wav`, `song.mp3`,
   `archive_song.wav`, or `archive_song.mp3`.
8. Resume:

```powershell
.\venv\Scripts\python.exe scripts\run_brand_short.py the_strange_archive `
  --audio-mode archive-song --episode dancing-plague-1518 --resume
```

An audio file elsewhere can be imported explicitly:

```powershell
.\venv\Scripts\python.exe scripts\run_brand_short.py the_strange_archive `
  --audio-mode archive-song --episode dancing-plague-1518 --resume `
  --song-audio "C:\Music\candidate.wav"
```

The operator's imported file is never overwritten or deleted. The renderer uses
a separate derived `production_audio.wav` (44.1 kHz stereo PCM via FFmpeg). When
multiple accepted filenames exist, the newest by mtime is selected unless
`--song-audio` is supplied. Replacing the import invalidates normalized audio,
timed maps, alignment, assets, and any prior render via a stored SHA-256
identity. Archive Song does not add the normal background library track over
the imported musical mix.

After audio exists, the pipeline writes `visual_beat_map_timed.json` (raw
progress→time), `visual_beat_map_normalized.json` (merge/split-adjusted timeline
shared by shots and full-screen captions), `lyrics_alignment.json`, and
`lyrics.srt`. Local Whisper may supply an outer timing window when available;
phrase placement is otherwise a labeled proportional fallback. The JSON is an
editable correction format that keeps source lyrics separate from timestamps and
is preserved on resume when the lyrics and imported audio identity are unchanged.
Lyric rendering keeps the phrase visible, highlights the active word, and
supports short full-screen beat-map text moments.

Visuals are copied into `assets/` after every completed shot. A failed rerun
reuses complete research, package, audio, alignment, and visual checkpoints.
The completed render is `final_video.mp4`; state becomes `rendered`.

## Factual safeguards

The parser rejects visual beats with unknown source IDs and packages without
fact traceability. Research `disputed_points` must remain verbatim in
`disputed_claim_warnings`. The prompt forbids unsupported claims, invented
dialogue, artist imitation, and copyrighted lyric references. These checks do
not replace operator review of linked sources.

The Dancing Plague pilot is test/example data only at
`tests/fixtures/dancing_plague_1518.json`. Production code does not reference it
or hard-code it to a brand.

## Configuration

Global defaults live in `config.json` (see `config.example.json` → `archive_song`).
Optional brand overrides go in the brand manifest:

```json
"production": {
  "archive_song": {
    "target_duration_seconds": 60,
    "min_duration_seconds": 55,
    "max_duration_seconds": 65,
    "duration_tolerance_seconds": 0.25,
    "lyric_min_words": 75,
    "lyric_max_words": 110,
    "default_musical_direction": "dark medieval folk cabaret; clear consonants",
    "default_vocal_direction": "Immediate vocal entrance; articulate proper nouns",
    "bpm_min": 70,
    "bpm_max": 120,
    "caption_style": "lyric_highlight",
    "hook_repetition": "prefer_repeated_hook",
    "visual_pacing": "beat_map",
    "fullscreen_emphasis": "on_screen_text",
    "fullscreen_max_seconds": 1.5,
    "audio_filenames": ["song.wav", "song.mp3", "archive_song.wav", "archive_song.mp3"],
    "min_shot_seconds": 1.5,
    "max_shot_seconds": 12.0,
    "embed_source_in_visual_prompts": false,
    "show_source_on_screen": false
  }
}
```

Precedence: engine defaults ← `config.json` `archive_song` ← brand
`production.archive_song` ← episode package fields (duration/vocal/style) ← CLI
(`--skip-song-validation`, `--song-audio`).

After audio import, shot prompts and durations come from the timed visual beat
map (`suggested_visual`, `camera_motion`, fact, period). Equal-duration lyric
prompts remain a logged fallback when the map is missing or malformed. Source
IDs are never shown on-screen unless `show_source_on_screen` is true.

Audio outside the configured window stops with an actionable warning and is
never silently truncated. `--skip-song-validation` converts duration failures to
warnings for an intentional operator exception; existence, WAV/MP3 format,
decode, and normalization checks still apply.

## Troubleshooting

- **Track too long or short:** choose another generation or intentionally edit
  it. The pipeline will not crop a musical section automatically.
- **Clipping warning:** listen to the exported master and choose a cleaner
  candidate. Normalization does not aggressively remix or limit it.
- **Leading/trailing silence:** trim manually if unintended. Automatic trim is
  disabled so the arrangement is not changed silently.
- **Pronunciation:** improve the guide, generate another candidate manually, and
  replace the imported audio.
- **Caption drift:** correct phrase timestamps after listening to final audio;
  singing transcription is less reliable than speech transcription.
- **Invalid audio:** re-export a non-empty, locally decodable WAV or MP3.
- **Need a clean package:** use `--regenerate-song-package`; research and script
  checkpoints remain intact.

Before commercial use, verify that the operator's current Suno plan and Suno's
current terms permit the intended usage. Terms and plan rights can change.
