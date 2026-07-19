# Voicebox local narration integration

MoneyPrinter can use a separately installed Voicebox 0.5.x service as an
optional narration provider. Voicebox remains an independent application: this
repository does not vendor its UI, Rust/Tauri code, model runtimes, database,
installers, or weights. The default MoneyPrinter narration path is unchanged.

## Verified contract

The adapter was audited on 2026-07-15 against `juud-8/voicebox` `main` at
commit [`da79e37ef50e38772a806dc05a0cf02c398899b7`](https://github.com/juud-8/voicebox/commit/da79e37ef50e38772a806dc05a0cf02c398899b7),
whose backend reports version `0.5.0`. MoneyPrinter accepts only `0.5.x` until a
later API audit expands that range.

Verified sources:

- Project features and public API examples:
  [`README.md`](https://github.com/juud-8/voicebox/blob/da79e37ef50e38772a806dc05a0cf02c398899b7/README.md)
- Backend startup and endpoint overview:
  [`backend/README.md`](https://github.com/juud-8/voicebox/blob/da79e37ef50e38772a806dc05a0cf02c398899b7/backend/README.md)
- Version declaration:
  [`backend/__init__.py`](https://github.com/juud-8/voicebox/blob/da79e37ef50e38772a806dc05a0cf02c398899b7/backend/__init__.py)
- Request/response models:
  [`backend/models.py`](https://github.com/juud-8/voicebox/blob/da79e37ef50e38772a806dc05a0cf02c398899b7/backend/models.py)
- Generation, polling/SSE, retry, cancellation, and streaming routes:
  [`backend/routes/generations.py`](https://github.com/juud-8/voicebox/blob/da79e37ef50e38772a806dc05a0cf02c398899b7/backend/routes/generations.py)
- Completed-generation polling:
  [`backend/routes/history.py`](https://github.com/juud-8/voicebox/blob/da79e37ef50e38772a806dc05a0cf02c398899b7/backend/routes/history.py)
- Audio download:
  [`backend/routes/audio.py`](https://github.com/juud-8/voicebox/blob/da79e37ef50e38772a806dc05a0cf02c398899b7/backend/routes/audio.py)
- Profiles and preset discovery:
  [`backend/routes/profiles.py`](https://github.com/juud-8/voicebox/blob/da79e37ef50e38772a806dc05a0cf02c398899b7/backend/routes/profiles.py)
- Profile/engine compatibility:
  [`backend/services/profiles.py`](https://github.com/juud-8/voicebox/blob/da79e37ef50e38772a806dc05a0cf02c398899b7/backend/services/profiles.py)
- Engine/model registry and language support:
  [`backend/backends/__init__.py`](https://github.com/juud-8/voicebox/blob/da79e37ef50e38772a806dc05a0cf02c398899b7/backend/backends/__init__.py)
- Model status (and separate download route, which MoneyPrinter never calls):
  [`backend/routes/models.py`](https://github.com/juud-8/voicebox/blob/da79e37ef50e38772a806dc05a0cf02c398899b7/backend/routes/models.py)
- Health and root/version routes:
  [`backend/routes/health.py`](https://github.com/juud-8/voicebox/blob/da79e37ef50e38772a806dc05a0cf02c398899b7/backend/routes/health.py)
- Transcription route:
  [`backend/routes/transcription.py`](https://github.com/juud-8/voicebox/blob/da79e37ef50e38772a806dc05a0cf02c398899b7/backend/routes/transcription.py)
- Client-header scope:
  [`backend/mcp_server/context.py`](https://github.com/juud-8/voicebox/blob/da79e37ef50e38772a806dc05a0cf02c398899b7/backend/mcp_server/context.py)
- MIT license:
  [`LICENSE`](https://github.com/juud-8/voicebox/blob/da79e37ef50e38772a806dc05a0cf02c398899b7/LICENSE)

The runtime FastAPI application exposes interactive docs at `/docs` and its
generated OpenAPI document at `/openapi.json`. The repository also contains
`docs/openapi.json`, but that checked-in file describes an older, synchronous
surface and is not authoritative for the 0.5 asynchronous routes. The adapter
therefore follows the pinned current route and model sources above.

### Endpoints MoneyPrinter uses

| Method and path | Purpose | Verified response |
|---|---|---|
| `GET /openapi.json` | API identity/version | Runtime OpenAPI `info.version`; packaged `/` may serve the SPA |
| `GET /health` | Fast readiness check | `HealthResponse`; `status` must be `healthy` |
| `GET /profiles` | Resolve configured name or id | Array of profile records |
| `GET /models/status` | Discover installed models without downloading | Object with `models` array |
| `POST /generate` | Submit narration | `GenerationResponse`, normally `status=generating` and an `id` |
| `GET /history/{id}` | Poll persisted generation state | History record with status/error/audio path |
| `POST /generate/{id}/cancel` | Best-effort timeout cleanup | Confirmation JSON |
| `GET /audio/{id}` | Download completed audio | Audio bytes, normally WAV |

`POST /generate` accepts `profile_id`, UTF-8 `text` (1–50,000 characters),
`language`, `seed`, `model_size`, `instruct`, `engine`, `max_chunk_chars`,
`crossfade_ms`, `normalize`, and an explicit `effects_chain`. MoneyPrinter does
not enable Voicebox personality rewriting because factual narration must not be
rewritten implicitly.

Generation is asynchronous. Voicebox also offers SSE at
`GET /generate/{id}/status` and direct audio streaming at
`POST /generate/stream`; MoneyPrinter deliberately uses bounded polling through
`GET /history/{id}` followed by the durable audio endpoint. This fits the
existing synchronous TTS contract and leaves an auditable server generation.

No authentication is required by the verified local `POST /generate` route.
`X-Voicebox-Client-Id` belongs to `/speak` and MCP client bindings, neither of
which this adapter uses. MoneyPrinter sends no authorization or client-id
header. Standard FastAPI failures use a JSON `detail` field; the client accepts
string, structured, or validation-list details without persisting headers.

## Installation and startup

Install Voicebox manually and separately by following its own documentation.
MoneyPrinter never installs Voicebox or downloads weights. Start the installed
Voicebox desktop application, or use Voicebox's documented standalone backend
from its own checkout/environment:

```powershell
python -m backend.main --host 127.0.0.1 --port 17493
```

Do not run that command from MoneyPrinter's virtual environment. Verify the
local API yourself before selecting it:

```powershell
Invoke-RestMethod http://127.0.0.1:17493/openapi.json
Invoke-RestMethod http://127.0.0.1:17493/health
Invoke-RestMethod http://127.0.0.1:17493/profiles
Invoke-RestMethod http://127.0.0.1:17493/models/status
Start-Process http://127.0.0.1:17493/docs
```

Download the chosen model in the Voicebox UI. MoneyPrinter checks
`/models/status` and fails closed if the model is absent or still downloading;
it never calls Voicebox's model-download route.

## Configuration

Keep `config.json` private. To opt in, add or edit:

```json
{
  "tts_provider": "elevenlabs",
  "audio": {
    "provider": "voicebox",
    "fallback_provider": null,
    "allow_fallback": false,
    "voicebox": {
      "base_url": "http://127.0.0.1:17493",
      "profile": "Archive Narrator",
      "engine": "qwen",
      "language": null,
      "model_size": "1.7B",
      "instruct": null,
      "request_timeout_seconds": 600,
      "health_timeout_seconds": 5,
      "poll_interval_seconds": 1,
      "max_retries": 1,
      "effects_preset": null,
      "effects_chain": [],
      "unsupported_tag_policy": "error",
      "max_chunk_chars": 800,
      "crossfade_ms": 50,
      "normalize": true
    }
  }
}
```

Profile matching tries exact id first and then a case-insensitive exact name.
`engine: null` uses the profile's default/preset engine, then Voicebox's `qwen`
default. Empty profile/engine/language values are rejected rather than treated
as missing. `max_retries: 0`, `crossfade_ms: 0`, `normalize: false`, and
`allow_fallback: false` remain meaningful values.

Precedence is engine defaults ← global `audio` ← active brand
`production.audio` ← episode overrides ← CLI overrides. Current production
callers use global/brand configuration; the resolver exposes episode and CLI
layers without adding redundant flags.

Unknown `audio` or `audio.voicebox` keys fail with an actionable configuration
error. Only loopback HTTP URLs with an explicit port are accepted.

## Engine capabilities

Voicebox `/models/status` reports model installation/readiness, not a full
engine capability document. MoneyPrinter combines it with a conservative map
pinned as `voicebox-0.5.0@da79e37`:

| Engine id | Profile type | Languages | Delivery instruction | Performance tags |
|---|---|---|---|---|
| `qwen` | cloned | 10 | no (base backend drops it) | no |
| `qwen_custom_voice` | preset | 10 | yes | no |
| `luxtts` | cloned | English | no | no |
| `chatterbox` | cloned | 23 | no | no |
| `chatterbox_turbo` | cloned | English | no | yes |
| `tada` | cloned | 1B English; 3B ten languages | no | no |
| `kokoro` | preset | 8 | no | no |

All mapped engines expose Voicebox's long-form chunking, effects chain, seed or
take behavior, async queue, direct stream endpoint, and local Whisper
transcription surface. This integration uses async generation, seed, chunking,
and effects; it does not use take/regeneration or streaming routes.

Only `chatterbox_turbo` may receive `[laugh]`, `[chuckle]`, `[gasp]`, `[cough]`,
`[sigh]`, `[groan]`, `[sniff]`, `[shush]`, or `[clear throat]`. Other engines
raise by default. `unsupported_tag_policy: "strip"` explicitly removes only
those verified tags and records a warning; it does not rewrite other narration.

Voicebox 0.5 accepts explicit effect chains in `/generate`, but not effect
preset names. `effects_preset` must remain `null`.

## Explicit fallback

Voicebox never falls back silently. Default `allow_fallback` is `false`. If an
operator deliberately enables it, `fallback_provider` must be exactly one of
`elevenlabs`, `fishaudio`, or `kittentts`. Only that provider is attempted; the
legacy multi-hop fallback chain is not entered.

The provider manifest records requested provider, failed provider, error class,
selected fallback, attempt count, result path, and result hash. Remember that
ElevenLabs and Fish Audio are paid external services; enabling either fallback
authorizes that path during a real production run.

## Artifacts and invalidation

Each request writes a unique directory under the requested output anchor's
sibling `narration` directory, normally `.mp/narration/<request-hash>-<request-id>/`:

```text
voicebox_original.wav
production_audio.wav
voicebox_request.json
audio_validation.json
provenance.json
provider_manifest.json
```

The downloaded original is created once and never edited or replaced. FFmpeg
derives 44.1 kHz stereo PCM through a partial WAV and atomically promotes it.
Failed partial files are removed. Validation checks that both files decode and
records size, duration, sample rate, channels, format, and SHA-256.

Request identity includes text, resolved profile (hashed), engine, model,
language, effects, seed, chunking, tag policy, and parent identity. Changed
input creates a different request hash and artifact directory. Normal narration
always generates captions and rendering after the final TTS path is chosen, so
re-generation cannot retain earlier dependent caption/render output. There is
no cross-run Voicebox narration cache in Phase 2; this is deliberate protection
against reusing stale audio after a failed request.

Manifests contain text/profile hashes rather than raw narration or raw profile
ids. They contain no authorization headers or secrets. Voicebox itself keeps
its own generation history/audio in its separately managed data directory.

## Non-publishing comparison

After Voicebox is installed, running, manually provisioned with the selected
model, and configured with `allow_fallback: false`, run:

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\venv\Scripts\python.exe scripts\test_voicebox_narration.py `
  --text "In 1518, Strasbourg records described a dancing outbreak, although later retellings often exaggerate what the surviving sources prove." `
  --seed 42
```

This command performs local Voicebox inference but does not render, upload,
publish, schedule, or call another provider. It refuses to run unless Voicebox
is selected and fallback is disabled. Phase 2 automated validation ran only its
`--help`; it did not make a live generation request.

## Transcription status

Voicebox 0.5 documents `POST /transcribe` with multipart `file`, optional
`language`, and optional Whisper `model`, returning text and duration. It may
return HTTP 202 while manually missing Whisper weights download. The endpoint
is stable enough to document, but Phase 2 does not wire it: MoneyPrinter's
caption path currently exposes methods on `YouTube`, not a shared typed STT
provider contract. Adding an adapter now would couple two unrelated contracts
or change default captions. Existing `local_whisper` remains authoritative.

## Troubleshooting

- **Not reachable:** start Voicebox and verify `GET /` on the configured
  loopback URL. MoneyPrinter never starts or terminates it.
- **Version incompatible:** use Voicebox 0.5.x or audit the adapter before
  expanding the accepted version.
- **Profile not found:** list `/profiles`; use the exact id or name.
- **Invalid profile/engine:** cloned profiles cannot use preset-only engines;
  preset profiles must use their recorded preset engine.
- **Model missing/downloading:** finish the manual download in Voicebox. The
  adapter refuses to trigger it.
- **Performance tag error:** choose `chatterbox_turbo`, remove the tag, or
  explicitly select the `strip` policy.
- **Timeout:** inspect Voicebox's generation history/logs. MoneyPrinter sends a
  best-effort cancel request and never returns a prior result as fallback.
- **Invalid audio/normalization:** inspect `voicebox_original.wav`, the JSON
  validation file, and MoviePy's `FFMPEG_BINARY` configuration.

## Privacy, GPU, and cost

Requests remain on the configured loopback interface. Raw text and profile id
are necessarily sent to the local Voicebox process, but are not written to
MoneyPrinter provenance. Treat both applications' local audio/history folders
as sensitive voice data.

GPU/model allocation, cache size, and model licensing belong to the separate
Voicebox installation. MoneyPrinter only observes status. It does not download,
load explicitly, unload, or delete models. Local Voicebox has no provider fee;
an explicitly enabled ElevenLabs/Fish fallback can incur cost.

No Voicebox implementation code was copied into MoneyPrinter, so no source
attribution block was required. The external project is MIT-licensed and linked
above.

## Switch back or roll back

Set `audio.provider` to `null` (or remove the `audio` object) to return to the
existing `tts_provider`. Keep `allow_fallback` false unless a paid fallback is
intentional. No data/schema migration is involved.

To remove Phase 2 code before it is committed, reverse only its reviewed diff:
remove the `voicebox_*` provider modules, local comparison script/tests/docs,
restore the small TTS/config/YouTube selector changes, restore Archive Song's
local FFmpeg command helper, and remove the `audio` example block. Do not reset,
clean, or discard unrelated work.
