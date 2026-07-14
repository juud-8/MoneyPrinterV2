# Trend-to-Archive MVP

The Trend-to-Archive engine is a disabled-by-default suggestion system. It collects trend evidence, proposes sourceable historical bridges, scores them transparently, and stops at a human-approved `TopicSeed`. It does not schedule, generate, upload, repost, or change a live channel during approval.

## Safety boundary

- Only `off` and `suggest` modes exist. `priority` is rejected.
- Every live provider is disabled until enabled in a brand manifest, and collection is still dry-run unless the operator passes `--live`.
- X is a fixture-only stub. No live X request is implemented.
- Google Trends is an official-provider placeholder and manual-import path. No unofficial scraping is implemented.
- YouTube collection accepts only `youtube_api_key` or `YOUTUBE_API_KEY`; it never falls back to a Gemini key.
- Bridge generation uses the configured local Ollama model. Offline bridge JSON can be imported instead.
- Approval creates a seed and prints a separate generation command. It never executes that command.
- The ordinary duplicate, grounded-research, brand-policy, script, duration, review, and upload gates remain authoritative.
- Trend keywords are context for research. Existing title/description generation remains responsible for final packaging and must not keyword-stuff.

## Brand configuration

Add this under `production` in the private `brands/<brand_id>/manifest.json`. Keep it disabled until the operator has reviewed the provider and scoring limits.

```json
{
  "trend_strategy": {
    "enabled": false,
    "mode": "off",
    "max_trend_assisted_share": 0.20,
    "recent_window_days": 30,
    "evergreen_target_share": 0.70,
    "experiment_target_share": 0.10,
    "providers": {
      "gdelt": {
        "enabled": false,
        "cache_ttl_minutes": 180,
        "daily_request_limit": 50,
        "daily_cost_limit_usd": 0
      },
      "wikimedia": {
        "enabled": false,
        "cache_ttl_minutes": 360,
        "daily_request_limit": 50,
        "daily_cost_limit_usd": 0
      },
      "youtube": {
        "enabled": false,
        "cache_ttl_minutes": 180,
        "daily_request_limit": 20,
        "daily_cost_limit_usd": 0
      },
      "x": {"enabled": false},
      "google_trends": {"enabled": false}
    },
    "scoring": {
      "minimum_cross_source_count": 2,
      "minimum_opportunity_score": 75,
      "minimum_archive_fit_score": 80,
      "minimum_sourceability_score": 70,
      "estimated_production_hours": 4
    }
  }
}
```

To permit suggestions, set only `enabled` to `true` and `mode` to `suggest`. Enable providers individually after reviewing quotas. Keep `publishing.review_before_upload` true in the brand manifest and `review_before_upload` true in `config.json`.

The YouTube Data API provider uses the existing dedicated `youtube_api_key` setting or `YOUTUBE_API_KEY`. Do not put credentials in a brand manifest.

## Operator workflow

All commands run from the repository root. On Windows PowerShell, use `python`; on systems where Python 3 is named separately, use `python3`.

Import the deterministic MVP fixture without making live calls:

```powershell
python src/trends.py collect --brand <brand_id> --manual tests/fixtures/trends/mvp_cases.json
python src/trends.py list clusters
python src/trends.py inspect <cluster_id>
```

Collect confirmation from only the providers enabled in the brand manifest:

```powershell
python src/trends.py collect --brand <brand_id> --term "american bison" --provider gdelt --provider wikimedia --provider youtube --live
```

Without `--live`, the command reports that external calls were skipped. Provider errors are partial results; successful evidence remains usable and evergreen production is independent.

Generate bridge candidates locally and collect historical sources:

```powershell
python src/trends.py bridge <cluster_id> --brand <brand_id>
python src/trends.py opportunities --brand <brand_id>
```

For an entirely offline review, provide validated bridge candidates with at least two independent historical source domains:

```powershell
python src/trends.py bridge <cluster_id> --brand <brand_id> --bridge-file tests/fixtures/trends/bridge_candidates.json
```

Record the human decision:

```powershell
python src/trends.py approve <opportunity_id> --brand <brand_id> --operator "<name>" --reason "<editorial reason>"
python src/trends.py reject <opportunity_id> --brand <brand_id> --operator "<name>" --reason "<rejection reason>"
```

If the projected trend-assisted share exceeds its configured maximum, approval is blocked. An editorial exception must be explicit and auditable:

```powershell
python src/trends.py approve <opportunity_id> --brand <brand_id> --operator "<name>" --reason "<editorial reason>" --override-reason "<why this exception is justified>"
```

Review the mix at any time:

```powershell
python src/trends.py report --brand <brand_id>
```

Approval prints a separate command containing the seed ID. Generation remains a deliberate later action:

```powershell
python scripts/run_brand_short.py <brand_id> --trend-seed <seed_id>
```

That command generates reviewable media but does not upload unless the operator separately adds `--upload` and the existing review gate permits it.

## Persistence and rollback

Trend data lives in `.mp/trends.sqlite3`; canonical records use stable IDs rather than titles. Schema migrations are repeatable and recorded in `schema_migrations`. Upgrading an existing v1 database to v2 creates `.mp/trends.sqlite3.v1.bak` before changing the schema.

To roll back application code, switch back to the reviewed baseline branch/commit. To roll back only local trend data, stop all MoneyPrinterV2 processes, preserve the current database for investigation, and restore the versioned `.bak` file. Do not overwrite `.mp/analytics.json`; the trend database is separate.

## Known MVP limits

- Trend discovery begins with operator terms or manual imports; GDELT, Wikimedia, and YouTube act primarily as confirmation providers.
- Historical bridge quality still depends on local-model output and source availability, so human review is mandatory.
- There is no scheduler, dashboard, priority queue, automatic reposting, or automatic package optimization.
- Opportunity scores are advisory. Hard policy, source, duplicate, catalog, expiration, and content-mix gates are separate.
- Unknown metrics remain `null` with an explanation and are excluded from the known-component average; they are never silently converted to zero.
