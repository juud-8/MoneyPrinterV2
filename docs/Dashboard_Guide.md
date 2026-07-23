# Dashboard Guide — EL JEFE Mission Control (MoneyPrinterV2)

Operator walkthrough for the local analytics + production UI.

> The control panel's on-screen identity is **EL JEFE // Mission Control**
> (brass/ink command deck). Beyond the theme it adds: a header **systems-check
> LED strip** (`/api/health` — click for fix details + Run preflight), a
> **Command Deck** (Today's Ops, Attention, Generate CTAs, Review Bay, Archive
> Song handoffs), **Telemetry** (KPIs, collapsible Growth Terrain, charts),
> a **Ctrl+K command palette**, keyboard shortcuts (`1–7`, `R`, `M`, `/`, `?`),
> per-brand **Open folder** / **Approve & Post**, inline retention on Performance,
> a **Weekly Review** tab, and **job history that survives restarts**
> (`.mp/logs/webui/jobs.json`).

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

Split into two bands:

**Command Deck**
- **Today's Ops** — posts vs `shorts_per_day`, next publish window + scheduler task hint
- **Attention** — silent upload failures, stale metrics, failed jobs, spend threshold, archive-song pauses
- **Window picker** (7d / 14d / 30d / All) + **⟳ Metrics** + Sync
- Primary Generate CTAs, insights “Double down” buttons when active
- **Review Bay** — newest `output/<brand>/` renders with Open folder / Approve & Post
- **Archive Song bay** — episodes at `awaiting_song_audio` with Open episode folder

**Telemetry**
- **KPI strip** — subs, channel views, posts in window, posted today, premium spend, attention count
- **Growth Terrain (3D)** — the single Three.js hero (subscriber ribbons). Collapse/expand is remembered. WebGL pauses when Overview is hidden or the tab is backgrounded.
- **2D charts** — posts/day, channel growth, output mix, top videos
- **Recent posts** + spend alert banner (`asset_spend_alert_threshold_usd`)

### Brands

Per brand:

- Subs + channel views (latest snapshot)
- Uploaded count, spend in window, posts, metrics filled
- **Generate only** / **Generate & Post now** / **Approve & Post** (from latest render)
- **Focus charts** — filters Overview charts to that brand
- Performance insights (top/bottom) once enough data exists
- Recent posts list
- **Publish times** — edit early/prime windows in `brands/<id>/manifest.json` (shows `scheduler_start_hint`)

### Performance

Full video metrics table: date, brand, title, status, views, likes, comments, retention %.

Public views/likes/comments come from **Refresh YouTube metrics**.  
Retention (`avg_view_pct`) can be set **inline** in the table (Save), or via CLI:

```powershell
.\venv\Scripts\python.exe src\analytics.py retention "<title or video id>" 72.5
```

Large tables are virtualized while scrolling. Copy video id / open YouTube from the row actions.

### Spend

- Window budget gauge + cost-per-uploaded-short (proxy)
- Doughnut: spend by tier
- Pie: spend by provider
- Bar: rejection pulse (topic near-duplicates + duration gate retries/aborts)
- List of recent premium spend events

### Pipeline

- Job list (generate / metrics / preflight) — history in `.mp/logs/webui/jobs.json` survives restarts (orphaned “running” jobs become `interrupted`)
- **Filing theater (default)** — stage rail + soft animation while a job runs
- **See terminal** — raw subprocess log; live tail via SSE (`/api/jobs/<id>/log/stream`) with poll fallback
- Cancel a running job
- When a job finishes, Overview auto-refreshes

### Review

7-day weekly ritual: summary cards (posts, spend, cost/upload, quality gates) + plain-text block with Copy.

### Help

In-app quick start mirroring this guide, plus the path to this file.

---

## Daily workflow

1. Start the control panel.
2. Clear **Attention** items on the Command Deck (systems, silent failures, stale metrics).
3. **Generate only** from the deck or Brands; watch **Pipeline**.
4. Review under `output/<brand_id>/` (Review Bay / Open folder).
5. When happy: **Approve & Post** or **Generate & Post now** (pilot brands treat the click as confirmation).
6. After the upload is live: **Refresh YouTube metrics**.
7. Check Overview / Performance; use **Review** weekly.

When `post_bridge.enabled` (and `auto_crosspost`) are set in `config.json`, a
successful YouTube upload is also cross-posted to connected TikTok/Instagram
accounts, and the Twitter/X bot can run alongside via its own scheduler slot —
see `docs/PostBridge.md`. Both are optional; the dashboard and pipeline work
identically with neither configured.

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
