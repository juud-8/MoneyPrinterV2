# Dashboard Guide — MoneyPrinterV2 Control Panel

Operator walkthrough for the local analytics + production UI.

## What is the “dashboard”?

There are three related surfaces. **Use the control panel** for day-to-day work.

| Surface | How to open | Use when |
|---------|-------------|----------|
| **Control panel (primary)** | `python src/webui.py` → http://127.0.0.1:5757 | Live ops, charts, jobs, metrics refresh |
| **Static HTML snapshot** | `scripts/generate_dashboard.py --open` → `.mp/dashboard.html` | Share/export a frozen view |
| **CLI table** | `scripts/dashboard.py` or main menu → Brand Dashboard | Quick terminal check |

All three read `.mp/analytics.json` via `analytics.get_dashboard_data()`.

---

## Start in 30 seconds

From the **project root** in PowerShell:

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\venv\Scripts\python.exe src\webui.py
```

Open **http://127.0.0.1:5757**

Custom port:

```powershell
$env:MPV2_WEBUI_PORT = "5758"
.\venv\Scripts\python.exe src\webui.py
```

Stop with Ctrl+C in that terminal. This does **not** stop Windows Task Scheduler jobs.

---

## Tour of each tab

### Overview

- **KPI strip** — deduped posts, uploaded count, premium spend for the selected window, all-time spend.
- **Window picker** (7d / 14d / 30d / All) — changes spend charts and rejection pulse. Post history on the Performance table stays full.
- **Growth Terrain (3D)** — subscriber snapshots over time as ribbons. Click a ribbon tip to filter 2D charts to that brand.
- **Spend Constellation (3D)** — premium asset events in the window; sphere size scales with cost.
- **2D charts** — posts/day, channel growth lines, views leaderboard, upload vs generated mix.
- **Recent posts** — last 15 deduped videos with status / views / likes when available.
- **Spend alert banner** — appears when window spend exceeds `asset_spend_alert_threshold_usd` in `config.json`.

### Brands

Per brand:

- Subs + channel views (latest snapshot)
- Uploaded count, spend in window, posts, metrics filled
- **Generate only** / **Generate & Post now**
- **Focus charts** — filters Overview charts to that brand
- Performance insights (top/bottom) once enough data exists
- Recent posts list
- **Publish times** — edit early/prime windows in `brands/<id>/manifest.json`

### Performance

Full video metrics table: date, brand, title, status, views, likes, comments, retention %.

Public views/likes/comments come from **Refresh YouTube metrics**.  
Retention (`avg_view_pct`) is **manual** from YouTube Studio:

```powershell
.\venv\Scripts\python.exe src\analytics.py retention "<title or video id>" 72.5
```

### Spend

- Doughnut: spend by tier
- Pie: spend by provider
- Bar: rejection pulse (topic near-duplicates + duration gate retries/aborts)
- List of recent premium spend events

### Pipeline

- Session job list (generate / metrics refresh)
- **Filing theater (default)** — stage rail + soft animation while a job runs; MoviePy progress when available
- **See terminal** — toggle to the raw subprocess log (tqdm spam); preference remembered in the browser
- Failed jobs auto-switch to terminal so the traceback is visible
- Cancel a running job
- When a job finishes, Overview auto-refreshes

Jobs are **in-memory for this webui process only** — restarting webui clears the list (logs remain under `.mp/logs/webui/`).

### Help

In-app quick start mirroring this guide, plus the path to this file.

---

## Daily workflow

1. Start the control panel.
2. Open **Brands** → **Generate only** for the channel you want.
3. Watch **Pipeline** until the job succeeds; review the file under `output/<brand_id>/`.
4. When happy: **Generate & Post now** (pilot brands treat the button as confirmation).
5. After the upload is live: **Refresh YouTube metrics**.
6. Check Overview / Performance for views.

CLI equivalents are documented in `COMMANDS.md` (`run_brand_short.py`, `upload_brand_short.py`).

---

## Weekly review ritual

1. Run metrics refresh (UI button, `.\run_metrics_refresh.ps1`, or the Sunday scheduled task).
2. On Overview: scan Growth Terrain, leaderboard, and brand insights.
3. On Spend: confirm premium spend is intentional; note the alert threshold.
4. Optionally paste Studio “average percentage viewed” via the retention CLI.
5. Double down on topics that show up in brand **Performance insights** (those feed topic generation automatically once active).

Insights activate when a brand has **5+** uploaded Shorts **older than 48 hours** with view data.

---

## Publish slots vs Task Scheduler

| Concept | Where | Meaning |
|---------|-------|---------|
| `window_start` / `window_end` | Brand manifest via Brands tab | Daily runner posts at a random time **inside** this window |
| `scheduler_start_hint` | Manifest (read-only hint in UI) | When your Windows task should **start** (usually ~30 min before the window) |

Editing slots in the UI writes `brands/<brand_id>/manifest.json`. The scheduled Python runner re-reads that file each run. The Windows task trigger itself is separate — update it in Task Scheduler if you move windows earlier.

---

## Data map

```text
YouTube pipeline ──log_video / log_asset_spend──► .mp/analytics.json
youtube_metrics.py ──views/likes/comments + snapshots──► .mp/analytics.json
                              │
                              ▼
                   get_dashboard_data()
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         Control panel   Static HTML        CLI
```

| Field | How it gets filled |
|-------|--------------------|
| Video row (title, status, path, url) | Automatic on generate / upload |
| views, likes, comments | Metrics refresh (YouTube Data API) |
| channel subscribers / total views | Metrics refresh → `channel_snapshots` |
| premium spend | Automatic on premium asset gen |
| topic / duration rejections | Automatic during generation |
| avg_view_pct (retention) | Manual CLI (Studio) |
| ctr, rpm, affiliate_clicks | Not auto-filled (placeholders) |

Config needed for metrics: `youtube_api_key` in `config.json` (Google Cloud key with YouTube Data API v3 — not an AI Studio Gemini key). Env fallback: `YOUTUBE_API_KEY`.

---

## When numbers are blank

| Symptom | Fix |
|---------|-----|
| Views show "—" | Run Refresh YouTube metrics; confirm video has a URL |
| Growth Terrain empty | Need ≥1 successful metrics refresh (snapshots) |
| Insights inactive | Need 5+ aged uploaded Shorts with views |
| Spend charts empty | No premium tiers used in window (or spend not logged) |
| Charts missing entirely | Check browser console; Chart.js is local under `/static/vendor/` |
| 3D scenes fallback | GPU/WebGL blocked — 2D charts still work |

---

## Troubleshooting

**Flask won’t start / port in use**  
Change `MPV2_WEBUI_PORT`, or stop the other process on 5757.

**Metrics job fails / 403**  
Wrong key type or YouTube Data API not enabled on the Cloud project. See `docs/Configuration.md` → `youtube_api_key`.

**Generate stuck / Selenium hang**  
Open Pipeline log; cancel the job; fix Firefox profile / Studio UI; retry one upload at a time.

**Overview didn’t update after metrics**  
Jobs finishing should trigger a refresh. Click another tab and back, or change the window picker. Hard-refresh the browser if needed.

**Emoji / encoding crash in related CLI tools**  
Always set `$env:PYTHONIOENCODING = "utf-8"` in PowerShell first.

---

## Related commands

```powershell
# Metrics now
.\run_metrics_refresh.ps1

# CLI dashboard
.\venv\Scripts\python.exe scripts\dashboard.py

# Static HTML
.\venv\Scripts\python.exe scripts\generate_dashboard.py --open

# Weekly text review
.\venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'src'); from analytics import print_weekly_review; print_weekly_review()"
```

See also: `COMMANDS.md` (Control panel, Metrics refresh, workflows B and E).
