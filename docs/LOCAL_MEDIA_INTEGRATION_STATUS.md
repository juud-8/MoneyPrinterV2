# Local media integration status

> Every future Codex, Claude Desktop, or Cursor agent working on local media
> integration must update this document before finishing.

## Current branch and base

- Current branch: `codex/sunobuild`
- Committed base: `2ba00b5` — `Stop transient Ollama probe failures from pinning SYSTEMS: CRITICAL`
- Safe comparison point: committed diffs use `2ba00b5`; phase-specific review
  must also account for the initial dirty inventory below because Archive Song
  was already uncommitted when this phase began.
- Relevant recent commits: `0331c8f`, `eb10a15`, `a1a26eb`, `603bfd3`, and
  `0cdbcb2`.

### Initial dirty inventory before local-media foundation work

Modified and unstaged:

- `README.md`
- `config.example.json`
- `docs/Configuration.md`
- `scripts/run_brand_short.py`
- `src/classes/YouTube.py`
- `src/config.py`
- `src/video_captions.py`

Untracked:

- `02234b91-2b7c-470d-9481-0b3bc8bf4b34TEMP_MPY_wvf_snd.mp3`
- `docs/ArchiveSong.md`
- `src/archive_song.py`
- `src/archive_song_settings.py`
- `src/archive_song_visuals.py`
- `tests/fixtures/`
- `tests/test_archive_song.py`
- `tests/test_archive_song_dry_run.py`

No files were staged. The initial tracked diff summary was 7 files, 1,013
insertions, and 49 deletions. The Archive Song work is not committed. Do not
discard it, reset it, or use `2ba00b5` alone as a representation of current
behavior.

## Current phase

Phase 1: trustworthy baseline, architecture audit, shared provider contracts,
shared provenance, and a non-invasive existing-provider adapter.

Status: complete for this phase. Voicebox, ACE-Step, and LongLive remain
explicitly deferred.

## Repository checkpoint plan

- Checkpoint date: 2026-07-15
- Implementation commit: pending creation, message
  `Add Archive Song and local media provider foundation`.
- Commit structure: one combined implementation commit is required because
  `src/archive_song.py` imports shared SHA-256 helpers from
  `src/media_providers`. Splitting the completed phases without a broken
  intermediate commit would require fragile partial staging of that untracked
  module.
- Ledger finalization: a ledger-only follow-up commit will record the exact
  implementation hash and final status. A commit cannot include its own hash,
  so the ledger finalization hash is reported by Git after creation rather than
  self-recorded in this file.
- Excluded generated artifact:
  `02234b91-2b7c-470d-9481-0b3bc8bf4b34TEMP_MPY_wvf_snd.mp3`. It belongs to an
  active render and must not be staged, deleted, or modified.

## Completed work

- Captured branch, status, recent history, diff summary, Python environment,
  test commands, local model/media processes, and the Archive Song commit state.
- Audited CLI, configuration/brand precedence, narration providers, audio
  handling, transcription/captions, visuals, Archive Song checkpoints,
  rendering, upload gates, retries, caches, provider-like abstractions, and
  existing tests.
- Added provider-neutral `AudioProvider`, `SongProvider`, and `VideoProvider`
  protocols and validated typed records.
- Added stable provider error categories and a registry with duplicate,
  disabled, unknown, and factory-validation behavior.
- Added provenance containing provider, engine, model/version, request/input/
  source/derived hashes, seed, JSON settings, timestamp, parent artifact,
  approval state, retry count, and fallback behavior.
- Reused the shared chunked SHA-256 helper in Archive Song while retaining its
  existing file-identity JSON shape.
- Added an ElevenLabs adapter that invokes the current legacy synthesis method
  exactly. The normal narration pipeline is not routed through it.
- Added offline tests for the new contracts, registry, provenance, adapter,
  health states, invalid configuration, unknown providers, Windows path JSON,
  narration dispatch/fallback, and Archive Song hash identity.
- Added `docs/LOCAL_MEDIA_ARCHITECTURE.md` based on actual repository code.

## Architecture decisions

1. Keep the provider foundation additive. Existing production paths remain the
   default until each adapter has its own offline and operator dry-run evidence.
2. Use Python dataclasses and structural `Protocol`s; add no dependency.
3. Register factories, not imported external repositories or preloaded model
   instances. A future heavy local worker can stay in a separate environment.
4. Exclude raw prompts/content, API keys, and raw ElevenLabs voice IDs from
   provenance. Hash the voice ID when it contributes to request identity.
5. Keep current operational quota/readiness checks. The new health record is a
   transport contract, not a replacement for `provider_health.py`.
6. Preserve Archive Song's path/size/mtime/SHA-256 identity and checkpoint
   invalidation semantics; share only the digest implementation.
7. Do not introduce a global registry or configuration selector in this phase.
   Importing the foundation has no runtime provider-selection side effect.

## Files changed by this phase

Added:

- `docs/LOCAL_MEDIA_ARCHITECTURE.md`
- `docs/LOCAL_MEDIA_INTEGRATION_STATUS.md`
- `src/media_providers/__init__.py`
- `src/media_providers/contracts.py`
- `src/media_providers/elevenlabs_adapter.py`
- `src/media_providers/errors.py`
- `src/media_providers/provenance.py`
- `src/media_providers/registry.py`
- `tests/test_media_providers.py`

Modified inside the pre-existing untracked Archive Song work:

- `src/archive_song.py` — delegates lyric/file SHA-256 calculation to the
  shared provenance helper; output values and identity shape remain unchanged.

No configuration, manifest, dependency, schema, credential, upload, or external
service file was changed by this phase.

## Test results

- Baseline before provider changes:
  `python -m unittest tests.test_archive_song tests.test_archive_song_dry_run`
  — 29 tests passed.
- Checkpoint Archive Song validation:
  `.\venv\Scripts\python.exe -m unittest tests.test_archive_song -v` — 28
  tests passed.
- Checkpoint provider validation:
  `.\venv\Scripts\python.exe -m unittest tests.test_media_providers -v` — 17
  tests passed.
- Checkpoint full suite:
  `.\venv\Scripts\python.exe -m unittest discover -s tests` — 197 tests
  passed. This discovery run includes `tests.test_archive_song_dry_run`.
- Checkpoint bytecode validation:
  `.\venv\Scripts\python.exe -m compileall src scripts` — passed.
- Safe parser/import smoke: `python scripts/run_brand_short.py --help` —
  passed and showed narration/Archive Song/resume options.
- Interactive CLI smoke: `'7' | python src/main.py` — did not reach the menu.
  Existing startup cleanup raised `PermissionError` for
  `.mp\02234b91-2b7c-470d-9481-0b3bc8bf4b34.mp4`. A read-only exclusive-open
  check on 2026-07-15 confirmed the lock remains. The likely owner is FFmpeg
  PID 3108, parented by Python PID 21376 running
  `scripts\run_brand_short.py the_strange_archive`, launched through
  `src\webui.py`. No process was stopped and no cleanup fix was made.
- `python scripts/preflight_local.py` — intentionally not run. Its native code
  performs live GET requests to the configured Gemini base and, when selected,
  the ElevenLabs subscription endpoint. That conflicts with this session's
  no-paid/external-API-call boundary. No lint/type command is configured in the
  repository.

One combined focused command hit its five-minute wrapper timeout while the
machine had active Python/FFmpeg rendering work and emitted no failure. The same
provider and Archive Song groups were rerun separately and passed as reported
above; the final full suite also passed.

All test commands use `venv\Scripts\python.exe` with
`PYTHONIOENCODING=utf-8` on Windows. No test calls a media provider.

## Known issues and risks

- The worktree contains substantial pre-existing uncommitted Archive Song work;
  ordinary `git diff` does not show untracked-file content against the base.
- `TTS.py` eagerly imports KittenTTS and `soundfile`, making isolated narration
  tests/startup heavier than the provider contracts themselves.
- The new registry is not a production composition root and no existing CLI
  setting selects it. This is intentional compatibility protection.
- Normal narration still lacks a shared post-generation audio validation and
  normalization contract. Adding one could change timing/output and is deferred.
- Existing provider health functions may perform remote quota/billing checks;
  the new adapter's `health()` is configuration-only and explicitly does not
  probe a network.
- Visual continuity is currently prompt-level; there is no durable continuity
  bible or reference-frame lineage yet.
- End-to-end MoviePy/Selenium behavior is not covered by a media-quality test.
- A read-only process check found active MoneyPrinter Python/FFmpeg work. This
  phase did not stop or alter those processes.
- `src/main.py` calls `rem_temp_files()` before displaying its menu and can
  crash with `PermissionError` when another MoneyPrinter render owns a `.mp`
  artifact. This pre-existing concurrency limitation blocked only the
  interactive CLI smoke; the brand-runner parser smoke passed.
- Checkpoint status before staging is dirty only with the reviewed Archive Song
  and provider-foundation boundary plus the excluded generated MoviePy audio
  artifact. Update this statement after commits are created.

## Deferred work

- Voicebox optional local narration adapter.
- Voicebox optional local transcription adapter and SRT/alignment mapping.
- A validated provider configuration resolver and explicit composition root.
- Request/result persistence and provenance attachment to production metadata.
- ACE-Step `SongProvider`, candidate comparison, and explicit human approval.
- LongLive-inspired typed continuity plan and reference-artifact lineage.
- Optional LongLive worker running outside the primary MoneyPrinter environment.
- Operator dry-runs and media-quality review for every new provider.

## Required manual operator steps

Do not install models or change provider defaults merely to exercise these
contracts. Before committing, the operator should review the pre-existing
Archive Song changes and this phase together, because Archive Song is still
uncommitted and `src/archive_song.py` now imports the new package.

After the active renderer releases `.mp` files, the operator may run these two
remaining environment checks deliberately:

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\venv\Scripts\python.exe scripts\preflight_local.py
'7' | .\venv\Scripts\python.exe src\main.py
```

The preflight performs read-only live endpoint checks, including configured
Gemini/ElevenLabs endpoints; run it only when those external checks are allowed.

## Rollback

No migration or runtime selector was added. To roll back only this phase, remove
the added `src/media_providers/` package, `tests/test_media_providers.py`, and
the two `docs/LOCAL_MEDIA_*` documents, then restore the two SHA-256 calls in
the pre-existing untracked `src/archive_song.py` to direct `hashlib.sha256`
calculation. Do not reset or delete any other Archive Song work. Because nothing
was committed, use a reviewed patch/manual edit rather than `git reset` or
`git clean`.

## External service status

- Voicebox: not installed or integrated; no process found.
- ACE-Step: not installed or integrated; no process found.
- LongLive: not installed or integrated; no process found.
- Ollama: local process observed running; no state changed.
- KittenTTS: declared dependency and current local fallback; no model generated
  during this phase.
- faster-whisper: declared dependency/current local STT path; no model generated
  during this phase.
- ElevenLabs: existing remote narration path plus new offline adapter; no API
  request or quota check made by this phase.
- Fish Audio, AssemblyAI, Gemini, and fal.ai: existing integrations only; no
  request made by this phase.
- Suno: manual Archive Song handoff only; no client or automation added.
- CUDA/GPU: not installed or changed; `nvidia-smi` was not available in the
  audited shell, so device status is unverified.

## Exact next recommended prompt

```text
Continue the staged local-media integration in MoneyPrinterV2. First read
docs/LOCAL_MEDIA_ARCHITECTURE.md and docs/LOCAL_MEDIA_INTEGRATION_STATUS.md,
show git status/branch/HEAD, preserve every uncommitted Archive Song and provider
foundation change, and update the status ledger before finishing.

Implement Phase 2: Voicebox only, as an optional local narration and
transcription provider behind the existing src/media_providers contracts. Do
not implement ACE-Step or LongLive. Do not install Voicebox, CUDA, weights, or
dependencies, and do not import Voicebox repository internals. Define a narrow
HTTP or subprocess adapter boundary from Voicebox's documented public interface;
if that interface is not available locally, implement only a configurable client
contract plus offline fake-server tests and document the exact operator input
still required. Preserve tts_provider/stt_provider defaults, ElevenLabs/Fish
Audio/KittenTTS behavior, narration output naming/timing, captions, Archive Song,
review_before_upload, and all upload boundaries. Add no paid or external calls.
Validate malformed responses, missing config, worker unavailable/timeouts,
duplicate/partial output, Windows paths, deterministic provenance, and fallback
behavior. Run focused tests, the full unittest suite, python -m compileall src,
preflight, and a non-generating CLI smoke check; report exact results and rollback.
```
