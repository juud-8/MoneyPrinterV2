# Weekly YouTube metrics refresh for MoneyPrinterV2.
#
# Pulls public view/like/comment counts + channel snapshots into
# .mp/analytics.json (repairs stale URLs first). Safe to run anytime;
# intended for Windows Task Scheduler once a week.
#
# Manual:
#   powershell -ExecutionPolicy Bypass -File scripts\run_metrics_refresh.ps1
#
# Register weekly task (Sunday 9:00 AM local):
#   powershell -ExecutionPolicy Bypass -File scripts\run_metrics_refresh.ps1 -Register

param(
    [switch]$Register,
    [string]$TaskName = "MoneyPrinterV2MetricsRefresh",
    [ValidateSet("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")]
    [string]$DayOfWeek = "Sunday",
    [string]$Time = "09:00"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$env:PYTHONIOENCODING = "utf-8"

$Python = Join-Path $Root "venv\Scripts\python.exe"
$Script = Join-Path $Root "src\youtube_metrics.py"
$LogDir = Join-Path $Root ".mp\logs"
$LogFile = Join-Path $LogDir "metrics_refresh.log"

if ($Register) {
    if (-not (Test-Path $Python)) {
        Write-Error "venv not found at $Python. Run: python -m venv venv; pip install -r requirements.txt"
    }
    $ps = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $scriptPath = Join-Path $Root "scripts\run_metrics_refresh.ps1"
    $action = '"' + $ps + '" -NoProfile -ExecutionPolicy Bypass -File "' + $scriptPath + '"'

    # Remove existing task if present so re-register is idempotent.
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    schtasks /Query /TN $TaskName 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        schtasks /Delete /TN $TaskName /F 2>$null | Out-Null
    }

    $dayCode = $DayOfWeek.Substring(0, 3).ToUpper()
    schtasks /Create /TN $TaskName /TR $action /SC WEEKLY /D $dayCode /ST $Time /RL LIMITED /F
    $createCode = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    if ($createCode -ne 0) {
        Write-Error "Failed to create scheduled task '$TaskName'. Try running PowerShell as Administrator."
    }
    Write-Host "Registered weekly task '$TaskName' - $DayOfWeek at $Time (local time)."
    Write-Host "  Action: $action"
    Write-Host "  Log:    $LogFile"
    Write-Host "  Remove: schtasks /Delete /TN $TaskName /F"
    exit 0
}

if (-not (Test-Path $Python)) {
    Write-Error "venv not found at $Python. Run: python -m venv venv; pip install -r requirements.txt"
}
if (-not (Test-Path $Script)) {
    Write-Error "Missing $Script"
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $LogFile -Value "[$stamp] Starting metrics refresh" -Encoding utf8

& $Python $Script *>&1 | Tee-Object -FilePath $LogFile -Append
$code = $LASTEXITCODE

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $LogFile -Value "[$stamp] Finished exit_code=$code" -Encoding utf8
exit $code
