# 60 Second Thrillers — archived 2026-07-11

Production is blocked via `sixty_second_thrillers` in `src/archived_brands.py`.
Task Scheduler job `60SecondThrillersDaily` was removed (`scripts/unregister_thrillers_task.ps1`).

## Resurrect

1. Remove `sixty_second_thrillers` from `ARCHIVED_BRANDS` in `src/archived_brands.py`.
2. Restore `brands/sixty_second_thrillers/manifest.json` (local; `brands/` is gitignored).
3. Re-register the daily task:
   ```powershell
   schtasks /Create /TN 60SecondThrillersDaily /TR "c:\Users\jeffd\dev\MoneyPrinterV2\scripts\_archived\sixty_second_thrillers\run_thrillers_daily.bat --upload" /SC DAILY /ST 19:00 /RL LIMITED /F
   ```

Historical `.mp/youtube.json` and `.mp/analytics.json` entries are preserved.
