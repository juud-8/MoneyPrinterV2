# Local media integration status

> Every future Codex, Claude Desktop, or Cursor agent working on local media
> integration must update this document before finishing.

## Repository checkpoint

- Branch: `codex/sunobuild`
- HEAD: `e2f2132d0c1cfca94bd5e50c5ebf87da8797846b` —
  `Record local media checkpoint status`
- Phase 1 implementation commit:
  `cc0e03e9670ce294a0c8cf06215511d9f4405873` —
  `Add Archive Song and local media provider foundation`
- Phase 2 began from a clean worktree with no untracked files.
- The earlier MoneyPrinter Python/FFmpeg render had exited before Phase 2. The
  old locked temporary media artifact was no longer present; no process was
  terminated.
- Phase 2 changes were committed on `codex/sunobuild` on 2026-07-17 at Jeff's
  direction after full revalidation (233 tests passing, compileall clean, webui
  smoke-tested on a side port). The concurrent dashboard modularization
  (webui-*.js split) was committed separately on the same branch. No push,
  merge, amend, stash, reset, clean, or discard operation was performed.

## Current phase

Phase 2: Voicebox optional local narration provider.

Status: implementation and offline validation complete. Production selection
is wired but strictly opt-in. A live Voicebox request has not been made.
ACE-Step, GPU queue work, continuity, LongLive, and Phase 3 have not begun.

The next action is an operator-controlled local Voicebox comparison after Jeff
installs/starts Voicebox separately and downloads a chosen model manually.

## Voicebox API verification

- External repository: `https://github.com/juud-8/voicebox`
- Audited branch/commit: `main` at
  `da79e37ef50e38772a806dc05a0cf02c398899b7`
- Backend version: `0.5.0`; the adapter accepts only `0.5.x`.
- Detailed source links and endpoint schemas:
  `docs/VOICEBOX_INTEGRATION.md`.
- Used endpoints: `GET /openapi.json`, `GET /health`, `GET /profiles`,
  `GET /models/status`, `POST /generate`, `GET /history/{id}`,
  `POST /generate/{id}/cancel`, and `GET /audio/{id}`.
- Generation is asynchronous. MoneyPrinter polls durable history rather than
  consuming SSE, then downloads the completed audio.
- `POST /generate` requires no auth/client header in the verified local API.
  `X-Voicebox-Client-Id` applies to `/speak` and MCP bindings, which are not
  used.
- Runtime FastAPI OpenAPI is available at `/openapi.json`. The checked-in
  Voicebox `docs/openapi.json` is older than the current async route source and
  is not used as the adapter contract.
- `/models/status` is checked before generation. Missing/downloading weights
  fail closed, preventing `/generate` from initiating a model download.

## Phase 2 implementation

- Added strict, dependency-free Voicebox API response schemas.
- Added a loopback-only synchronous HTTP client with bounded health/generation
  timeouts, async history polling, typed HTTP/schema errors, and best-effort
  cancellation on timeout.
- Added a conservative capability map pinned to Voicebox 0.5.0 for seven TTS
  engines, model variants, profile types, languages, delivery instructions,
  performance tags, chunking, effects, transcription availability, seed/take,
  streaming, and async behavior.
- Only `chatterbox_turbo` receives documented performance tags. Other engines
  raise by default or strip those exact tags only when explicitly configured.
- Added lossless configuration precedence: defaults/legacy `tts_provider` ←
  global `audio` ← brand `production.audio` ← episode ← CLI. `false`, zero,
  null, and empty strings have explicit validation semantics; unknown keys are
  rejected.
- Added `VoiceboxAudioProvider` behind the shared `AudioProvider` contract.
  It resolves profiles, validates profile/engine/language/model compatibility,
  refuses absent weights, submits/polls/downloads, and applies explicit retry.
- Added immutable original audio, atomic 44.1 kHz stereo PCM derivation,
  decode/identity validation, and shared provenance.
- Added request/provider manifests without raw narration, raw profile ids,
  secrets, authorization headers, or sensitive voice samples.
- Wired Voicebox through the existing `TTS.synthesize()` authority without raw
  HTTP in `TTS`. Existing ElevenLabs/Fish/Kitten paths and their legacy fallback
  behavior are unchanged when Voicebox is not selected.
- Voicebox fallback defaults off. When explicitly enabled it makes only the
  named fallback attempt and records requested provider, failed provider, error
  class, selected fallback, attempt count, output path, and output hash.
- Attached the narration provider manifest/identity to YouTube production
  metadata before caption/render work. Fresh narration generation therefore
  cannot retain dependent captions or render output from a prior TTS result.
- Added a guarded non-publishing comparison script. It refuses to run unless
  Voicebox is selected and fallback is disabled.
- Factored the existing Windows-safe FFmpeg normalization argv builder into a
  shared local-media helper; Archive Song imports it with unchanged behavior.
- Voicebox transcription was audited but not wired. MoneyPrinter does not yet
  have a shared typed STT provider contract; the current `local_whisper`
  caption path remains authoritative.

## Artifact contract

Voicebox narration artifacts are unique per request under the requested output
anchor's sibling `narration` directory, normally:

```text
.mp/narration/<request-hash>-<request-id>/
├── voicebox_original.wav
├── production_audio.wav
├── voicebox_request.json
├── audio_validation.json
├── provenance.json
└── provider_manifest.json
```

The original is never normalized or replaced in place. The derived production
WAV is promoted atomically. A failed normalization removes partial derived
files and never produces valid provenance. Different profile, engine, text,
effects, language, seed, chunking, or source identity creates a different
request hash. Phase 2 intentionally has no cross-run narration cache, so a
failed request cannot reuse a stale prior Voicebox result.

## Files changed in Phase 2

Added:

- `docs/VOICEBOX_INTEGRATION.md`
- `scripts/test_voicebox_narration.py`
- `src/media_providers/audio_assets.py`
- `src/media_providers/voicebox_capabilities.py`
- `src/media_providers/voicebox_client.py`
- `src/media_providers/voicebox_provider.py`
- `src/media_providers/voicebox_schemas.py`
- `src/media_providers/voicebox_settings.py`
- `tests/test_voicebox_provider.py`

Modified and tracked:

- `README.md`
- `config.example.json`
- `docs/Configuration.md`
- `docs/LOCAL_MEDIA_INTEGRATION_STATUS.md`
- `src/archive_song.py`
- `src/classes/Tts.py`
- `src/classes/YouTube.py`
- `src/config.py`
- `src/media_providers/__init__.py`
- `src/media_providers/errors.py`

Modified locally but intentionally ignored by the repository:

- `COMMANDS.md` — Voicebox service checks and non-publishing comparison
  commands were added. `.gitignore` already excludes this operator-local file,
  so it does not appear in `git status` and would need an explicit repository
  policy decision before any later commit includes it.

No dependency, credential, database, brand manifest, upload, production
integration, or model file was added or changed.

## Exact validation results

All commands used `PYTHONIOENCODING=utf-8` on Windows. All automated tests were
offline and used fake HTTP clients/in-memory WAV data.

- `.\venv\Scripts\python.exe -m unittest tests.test_voicebox_provider -v`
  — 29 tests passed.
- `.\venv\Scripts\python.exe -m unittest tests.test_media_providers -v`
  — 17 tests passed. This includes existing ElevenLabs direct dispatch and
  legacy Kitten fallback regression tests.
- `.\venv\Scripts\python.exe -m unittest tests.test_archive_song -v`
  — 28 tests passed.
- `.\venv\Scripts\python.exe -m unittest tests.test_config -v`
  — 11 tests passed during focused wiring validation.
- `.\venv\Scripts\python.exe -m unittest discover -s tests`
  — 226 tests passed.
- `.\venv\Scripts\python.exe -m compileall src scripts`
  — passed; all listed source/script directories compiled.
- `.\venv\Scripts\python.exe scripts\run_brand_short.py --help`
  — passed; existing narration/Archive Song/resume/upload parser remained
  available and no generation ran.
- `.\venv\Scripts\python.exe scripts\test_voicebox_narration.py --help`
  — passed; no local inference ran.
- `git diff --check` — passed.

`scripts/preflight_local.py` was intentionally not run because it performs live
configured-provider endpoint checks. The interactive `src/main.py` smoke was
not required by the Phase 2 validation list and was not rerun. Its prior
file-lock owner is gone; the safe parser smoke above passed.

## Default behavior and production status

- Default provider changed: **no**.
- Production selection wired: **yes, opt-in only** through `audio.provider`.
- Existing `tts_provider` remains authoritative when `audio.provider` is null
  or absent.
- Existing ElevenLabs/Fish/Kitten dispatch changed: **no**.
- Voicebox implicit fallback: **none**.
- Caption default changed: **no**; `local_whisper` remains default.
- Upload/review behavior changed: **no**; `review_before_upload` and all upload
  boundaries remain intact.
- Live Voicebox request made: **no**.
- External provider/API request made: **no**.
- Model download/load/start made: **no**.
- Upload/publish/schedule action made: **no**.
- Commit/push/merge made during Phase 2 implementation: **no**. The reviewed
  diff was committed afterward on 2026-07-17 (see Repository checkpoint).

## Known limitations and risks

- Only Voicebox 0.5.x is accepted. A newer minor/major API requires a fresh
  source audit and capability-map update.
- `/models/status` supplies model state, not a complete capability document;
  engine behavior is conservatively pinned to verified 0.5.0 source.
- No real voice quality, latency, GPU memory, long-form prosody, or effects
  comparison exists yet because live inference was prohibited in this phase.
- Narration has no cross-run Voicebox cache. This avoids stale output but means
  an identical later request generates a new take.
- Transcription is documented but not adapted until a shared STT contract can
  be introduced without changing existing captions.
- Voicebox stores its own generation history/audio separately; the operator is
  responsible for securing and pruning that local data.
- `TTS.py` still eagerly imports KittenTTS/soundfile as part of the historical
  module structure.
- End-to-end MoviePy/Selenium media quality is not covered by automated tests.

## Security, privacy, and cost

- Voicebox URLs are restricted to loopback HTTP with an explicit port.
- No auth/client-id header is sent or persisted.
- Raw narration/profile ids are sent only to the local Voicebox process as
  required by its API; MoneyPrinter manifests use hashes.
- Original and normalized voice audio are sensitive local artifacts.
- MoneyPrinter never calls Voicebox model download/load/unload/delete routes.
- Local Voicebox has no provider fee. Explicit ElevenLabs/Fish fallback can
  incur cost and remains disabled by default.
- No Voicebox code was copied; the separately linked project is MIT-licensed.

## Manual operator actions

1. Install Voicebox 0.5.x separately using its own instructions.
2. Start Voicebox separately on `127.0.0.1:17493`.
3. Manually download one selected TTS model in Voicebox.
4. Use `/profiles` to choose an exact profile name/id.
5. Configure `audio.provider: "voicebox"`, that profile/engine, and
   `audio.allow_fallback: false` in private `config.json`.
6. Run the non-publishing comparison below and review both WAV files plus the
   JSON manifests before any full content run.

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\venv\Scripts\python.exe scripts\test_voicebox_narration.py `
  --text "In 1518, Strasbourg records described a dancing outbreak, although later retellings often exaggerate what the surviving sources prove." `
  --seed 42
```

To switch back immediately, set `audio.provider` to `null` or remove the
`audio` object. The existing `tts_provider` takes over.

## Rollback

There is no migration. Before any commit, reverse only the reviewed Phase 2
diff: remove the nine added tracked code/test/doc files, restore the small
selector/metadata changes in config/TTS/YouTube, restore Archive Song's local
FFmpeg helper, and remove the `audio` example/documentation additions. Preserve
all Phase 1/Archive Song commits and unrelated local files. Do not use `git
reset`, `git clean`, or destructive history operations.

## Recommended next prompt

```text
Review the uncommitted Voicebox Phase 2 implementation in MoneyPrinterV2 on
codex/sunobuild. Read docs/VOICEBOX_INTEGRATION.md and
docs/LOCAL_MEDIA_INTEGRATION_STATUS.md, show branch/status/HEAD and the full
Phase 2 diff, and do not alter defaults or call external services. If Jeff has
installed Voicebox 0.5.x, first verify its loopback health/profiles/model status
without downloading anything, then run exactly one non-publishing comparison
with fallback disabled and inspect the original/production WAVs and manifests.
Do not upload, commit, push, begin ACE-Step, or begin LongLive without a separate
explicit instruction.
```

## Voicebox readiness evaluation (2026-07-18)

Offline readiness check added: `scripts/evaluate_voicebox_readiness.py`.

Result on this workstation (no live inference performed):

- `audio.provider` is still `elevenlabs` (not `voicebox`)
- `audio.voicebox.profile` is empty
- Voicebox `/health` on `http://127.0.0.1:17493` is not reachable
- `ready_for_live_comparison`: **false**

Operator next steps unchanged: install/start Voicebox 0.5.x, set
`audio.provider=voicebox` + `allow_fallback=false` + profile, re-run readiness,
then `scripts/test_voicebox_narration.py`. ACE-Step / LongLive remain blocked
until that comparison decision.
