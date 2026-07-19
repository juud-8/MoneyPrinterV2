

# MoneyPrinterV2 Engineering Instructions

## Project Mission

MoneyPrinterV2 is a modular, multi-brand content production system.

The goal is not merely to generate videos. The long-term goal is to become a
closed-loop channel optimization platform that:

1. Generates candidate content packages.
2. Verifies factual claims.
3. Produces reviewable media.
4. Uploads only after approval.
5. Collects performance analytics.
6. Diagnoses results honestly.
7. Improves future strategy without overfitting.

## Non-Negotiable Architecture Rules

- Preserve the brand-agnostic engine architecture.
- Never hardcode `the_strange_archive` or another brand inside generic engine code.
- Brand-specific behavior belongs in brand manifests, configurable profiles, or
  strategy data.
- Preserve backward compatibility unless the task explicitly approves a migration.
- Prefer small cohesive modules over expanding `classes/YouTube.py` indefinitely.
- Do not duplicate logic already available elsewhere in the repository.
- Use typed structured objects or validated schemas for LLM-generated data.
- Treat LLM output as untrusted input and validate it before use.

## Upload and External-Action Safety

- Never upload, publish, delete, edit, unlist, schedule, or modify a live video
  unless the user explicitly requests that action.
- Preserve `review_before_upload`.
- Do not respond to comments or change channel settings.
- Analytics integrations must be read-only.
- Dry-run by default when external services are involved.
- Do not make paid asset-generation calls during testing unless explicitly approved.

## Data Safety

- Never commit credentials, API keys, OAuth tokens, cookies, browser profiles,
  `.env` contents, or local configuration secrets.
- Never destructively overwrite `.mp/analytics.json`.
- Back up persisted data before migrations.
- Migrations must be versioned, repeatable, and tested.
- Use YouTube video IDs as canonical identities instead of titles.
- Missing analytics must remain explicitly missing; never silently fabricate proxies.
- Label proxy metrics clearly.

## Historical Content Quality

- Central historical claims require adequate sourcing.
- Never present folklore, legends, disputed claims, or uncertain dates as settled fact.
- Do not generate modern true crime, living-person allegations, graphic violence,
  deceptive conspiracy framing, or fictional events presented as real.
- Preserve source and claim metadata wherever practical.
- Generated visuals should be checked for obvious anachronisms.

## Testing and Validation

Before declaring work complete:

- Discover and run the repository's existing tests.
- Add focused tests for all new behavior.
- Run `python -m compileall src`.
- Exercise malformed LLM output.
- Exercise missing configuration.
- Exercise failed external-service calls.
- Exercise duplicate and partial data.
- Verify Windows compatibility.
- Report commands run and their results.
- Never hide failing tests.

## Git and Scope

- Work in an isolated Codex worktree for substantial changes.
- Keep each task focused on one feature.
- Do not perform unrelated cleanup.
- Do not commit generated media, secrets, caches, virtual environments, or local data.
- Present the implementation plan before making major architectural changes.
- Use clear commits grouped by logical change.
- Do not merge to `main` automatically.

## Completion Report

At completion provide:

1. What changed.
2. Why the architecture was selected.
3. Files added and modified.
4. Data or configuration migrations.
5. Tests run and results.
6. Known limitations.
7. Security and cost considerations.
8. Exact operator commands.
9. Rollback instructions.
10. Recommended next task.# Repository Guidelines

## Project Structure & Module Organization
- `src/` contains the application code. Use `src/main.py` as the interactive entrypoint.
- `src/classes/` holds provider-specific components (for example `YouTube.py`, `Twitter.py`, `Tts.py`, `AFM.py`, `Outreach.py`).
- Shared utilities and configuration live in modules like `src/config.py`, `src/utils.py`, `src/cache.py`, and `src/constants.py`.
- `src/brand_switcher.py`, `src/content_styles.py`, `src/asset_gen.py`, `src/asset_strategy.py` implement the multi-brand system and tiered asset generation — keep these brand-agnostic; a brand's behavior should come entirely from its manifest, never from an `if brand_id == "..."` check in engine code.
- `brands/<brand_id>/` holds each brand's manifest (`manifest.json`), brand-specific assets (e.g. an outro clip), and any brand-pinned scheduled-run scripts. This directory is content/business data, not engine code — treat it as gitignored/private by default.
- `scripts/` contains helper workflows such as setup, preflight checks, and upload helpers.
- `docs/` contains feature documentation; `assets/` and `fonts/` contain static resources.

## Build, Test, and Development Commands
- `bash scripts/setup_local.sh`: bootstrap local development (creates `venv`, installs deps, seeds `config.json`, runs preflight).
- `source venv/bin/activate && pip install -r requirements.txt`: manual dependency install/update.
- `python3 scripts/preflight_local.py`: validate local provider/config readiness before running tasks.
- `python3 src/main.py`: start the CLI app.
- `bash scripts/upload_video.sh`: run direct script-based upload flow from repo root.

## Coding Style & Naming Conventions
- Target Python 3.12 (project requirement in `README.md`).
- Use 4-space indentation and follow existing Python conventions:
  - `snake_case` for functions/variables
  - `PascalCase` for classes
  - `UPPER_SNAKE_CASE` for constants
- Keep new business logic in focused modules under `src/`; keep provider/integration code in `src/classes/`.
- Prefer small, explicit functions and preserve existing CLI-first behavior.

## Testing Guidelines
- There is a `tests/` suite (`python -m unittest discover -s tests`) covering pure-logic modules: config parsing, brand resolution (`brand_switcher`), content styles, asset strategy/fallback (`asset_gen`/`asset_strategy`), description building (`content_funnel`), and Post Bridge. There is no enforced coverage threshold, and the Selenium/MoviePy pipeline itself is not covered by automated tests.
- On Windows, set `$env:PYTHONIOENCODING = "utf-8"` before running tests/scripts in PowerShell — `status.py`'s emoji-prefixed log messages otherwise crash under the default `cp1252` console encoding.
- Minimum validation for changes:
  - Run `python -m unittest discover -s tests`
  - Run `python3 scripts/preflight_local.py`
  - Smoke-test impacted flows via `python3 src/main.py`
- When adding tests, place them in the top-level `tests/` directory with names like `test_<module>.py`, and isolate any test that touches `.mp/` (cache files) by patching the relevant path function (e.g. `cache.get_cache_path`) to a temp directory — several existing tests do this; never let a test write to the real `.mp/` cache.

## Commit & Pull Request Guidelines
- Follow the existing commit style: imperative summaries like `Fix ...`, `Update ...`, optionally with issue refs (for example `(#128)`).
- Open PRs against `main`.
- Link each PR to an issue, keep scope to one feature/fix, and use a clear title + description.
- Mark not-ready PRs with `WIP` and remove it when ready for review.

## Security & Configuration Tips
- Treat `config.json` as environment-specific; do not commit real API keys or private profile paths.
- Start from `config.example.json` and prefer environment variables where supported (for example `GEMINI_API_KEY`, `ELEVENLABS_API_KEY`, `FAL_KEY`).
- `brands/<brand_id>/manifest.json` files can contain account-identifying info (Google account email, channel id, voice id) — treat them with the same care as `config.json` even though they aren't gitignored by default; avoid putting real secrets directly in a manifest.
- Generated video output (`output/`) is gitignored — never force-add it; these are large binaries that don't belong in git history.
