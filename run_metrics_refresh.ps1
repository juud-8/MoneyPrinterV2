# Shortcut — run from repo root:
#   .\run_metrics_refresh.ps1              # refresh now
#   .\run_metrics_refresh.ps1 -Register    # schedule weekly (Sun 9:00 AM)
param(
    [switch]$Register,
    [string]$TaskName = "MoneyPrinterV2MetricsRefresh",
    [ValidateSet("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")]
    [string]$DayOfWeek = "Sunday",
    [string]$Time = "09:00"
)
$Root = $PSScriptRoot
& (Join-Path $Root "scripts\run_metrics_refresh.ps1") @PSBoundParameters
exit $LASTEXITCODE
