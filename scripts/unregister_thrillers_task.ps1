# Unregister the archived 60 Second Thrillers daily Task Scheduler job.
# Safe to run multiple times.
$ErrorActionPreference = "Stop"
$TaskName = "60SecondThrillersDaily"
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
schtasks /Query /TN $TaskName 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    schtasks /Delete /TN $TaskName /F
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Removed scheduled task '$TaskName'."
    } else {
        Write-Error "Failed to delete '$TaskName'."
    }
} else {
    Write-Host "Task '$TaskName' not found (already removed)."
}
$ErrorActionPreference = $prevEap
