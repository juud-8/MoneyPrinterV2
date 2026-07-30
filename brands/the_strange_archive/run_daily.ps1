# Daily The Strange Archive — use with Windows Task Scheduler (2 tasks for 2 Shorts/day)
#
# Generate only (review before publish):
#   powershell -ExecutionPolicy Bypass -File brands\the_strange_archive\run_daily.ps1 -Slot early
#   powershell -ExecutionPolicy Bypass -File brands\the_strange_archive\run_daily.ps1 -Slot prime
#
# Generate + upload:
#   powershell -ExecutionPolicy Bypass -File brands\the_strange_archive\run_daily.ps1 -Slot early -Upload
#   powershell -ExecutionPolicy Bypass -File brands\the_strange_archive\run_daily.ps1 -Slot prime -Upload
#
# Task Scheduler (local time):
#   TheStrangeArchiveEarly  — start ~5:15 PM  → publishes 5:45-6:00 PM  (-Slot early)
#   TheStrangeArchivePrime  — start ~6:00 PM  → publishes 6:30-7:00 PM  (-Slot prime)

param(
    [ValidateSet("early", "prime")]
    [string]$Slot = "prime",
    [switch]$Upload
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
Set-Location $Root

$env:PYTHONIOENCODING = "utf-8"

$EnsureOllama = Join-Path $Root "scripts\ensure_ollama.ps1"
& $EnsureOllama
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$Python = Join-Path $Root "venv\Scripts\python.exe"
$Script = Join-Path $Root "brands\the_strange_archive\scheduled_run.py"

if (-not (Test-Path $Python)) {
    Write-Error "venv not found. Run: python -m venv venv; pip install -r requirements.txt"
}

$Args = @($Script, "--slot", $Slot)
if ($Upload) {
    $Args += "--upload"
}

& $Python @Args
exit $LASTEXITCODE
