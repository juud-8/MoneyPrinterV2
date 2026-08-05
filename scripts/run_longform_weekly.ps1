# Scheduled weekly long-form run for MoneyPrinterV2.
#
# Generates a themed compilation episode from the brand's published shorts
# (see src/longform_theme.py) and, with -Upload, stages it on YouTube.
# Intended for Windows Task Scheduler.
#
# Manual (generate only, no upload):
#   powershell -ExecutionPolicy Bypass -File scripts\run_longform_weekly.ps1 -BrandId my_brand
#
# Register weekly task (Sunday 2:00 AM local, generate + upload):
#   powershell -ExecutionPolicy Bypass -File scripts\run_longform_weekly.ps1 -Register -BrandId my_brand -Upload
#
# Pick a start time that cannot overlap the daily shorts task: a long-form
# render takes 30-60+ minutes and both jobs share the .mp/ scratch directory.
# They also hold the same run lock, so an overlap is skipped rather than
# corrupted (exit code 75) — but a skipped week is still a missed upload.

param(
    [switch]$Register,
    [string]$BrandId,
    [switch]$Upload,
    [switch]$NoTheme,
    [string]$TaskName = "MoneyPrinterV2LongformWeekly",
    [ValidateSet("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")]
    [string]$DayOfWeek = "Sunday",
    [string]$Time = "02:00"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$env:PYTHONIOENCODING = "utf-8"

$Python = Join-Path $Root "venv\Scripts\python.exe"
$Script = Join-Path $Root "scripts\run_brand_longform.py"
$LogDir = Join-Path $Root ".mp\logs"
$LogFile = Join-Path $LogDir "longform_weekly.log"

if ($Register) {
    if (-not $BrandId) {
        Write-Error "-BrandId is required when registering: the task must pin its brand rather than depend on whichever brand happens to be active at fire time."
    }
    if (-not (Test-Path $Python)) {
        Write-Error "venv not found at $Python. Run: python -m venv venv; pip install -r requirements.txt"
    }
    $ps = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $scriptPath = Join-Path $Root "scripts\run_longform_weekly.ps1"
    $action = '"' + $ps + '" -NoProfile -ExecutionPolicy Bypass -File "' + $scriptPath + '" -BrandId "' + $BrandId + '"'
    if ($Upload) { $action += " -Upload" }
    if ($NoTheme) { $action += " -NoTheme" }

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
    Write-Host "Registered weekly task '$TaskName' for $DayOfWeek at $Time (local time)."
    Write-Host "  Brand:  $BrandId"
    Write-Host "  Upload: $(if ($Upload) { 'yes (staged private for review)' } else { 'no (generate only)' })"
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

$runArgs = @()
if ($BrandId) { $runArgs += $BrandId }
# Themed compilation is the point of the weekly run: the shorts topic generator
# saturates in a narrow niche, while the back catalogue keeps growing.
if (-not $NoTheme) { $runArgs += "--theme" }
if ($Upload) { $runArgs += "--upload" }
$runArgs += "--unattended"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $LogFile -Value "[$stamp] Starting long-form run ($($runArgs -join ' '))" -Encoding utf8

# Not Tee-Object: under Windows PowerShell 5.1 (the scheduled-task host) it
# appends UTF-16, garbling a log whose stamps are written as utf8.
& $Python $Script @runArgs *>&1 | ForEach-Object { $_; Add-Content -Path $LogFile -Value "$_" -Encoding utf8 }
$code = $LASTEXITCODE

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
if ($code -eq 75) {
    # Deliberate no-op: another generation run held the lock.
    Add-Content -Path $LogFile -Value "[$stamp] Skipped - another run in progress" -Encoding utf8
    exit 0
}
if ($code -eq 66) {
    # Deliberate no-op: every eligible theme has already been made. Normal
    # once the catalogue is exhausted; more shorts create more themes.
    Add-Content -Path $LogFile -Value "[$stamp] Skipped - no unused theme available yet" -Encoding utf8
    exit 0
}
Add-Content -Path $LogFile -Value "[$stamp] Finished exit_code=$code" -Encoding utf8
exit $code
