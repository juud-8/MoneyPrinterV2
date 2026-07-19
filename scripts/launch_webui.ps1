# Launch MoneyPrinterV2 control panel and open the browser.
# Double-click via Desktop shortcut, or:
#   powershell -ExecutionPolicy Bypass -File scripts\launch_webui.ps1

param(
    [int]$Port = 0
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if ($Port -le 0) {
    if ($env:MPV2_WEBUI_PORT) {
        $Port = [int]$env:MPV2_WEBUI_PORT
    } else {
        $Port = 5757
    }
}

$Url = "http://127.0.0.1:$Port"
$Python = Join-Path $Root "venv\Scripts\python.exe"
$Webui = Join-Path $Root "src\webui.py"

if (-not (Test-Path $Python)) {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
        "venv Python not found:`n$Python`n`nRun setup first from the project root.",
        "MoneyPrinterV2",
        "OK",
        "Error"
    ) | Out-Null
    exit 1
}

function Test-WebuiUp {
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        return $resp.StatusCode -ge 200
    } catch {
        return $false
    }
}

if (-not (Test-WebuiUp)) {
    $env:PYTHONIOENCODING = "utf-8"
    $env:MPV2_WEBUI_PORT = "$Port"
    Start-Process -FilePath $Python -ArgumentList "`"$Webui`"" -WorkingDirectory $Root -WindowStyle Minimized

    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 250
        if (Test-WebuiUp) {
            $ready = $true
            break
        }
    }
    if (-not $ready) {
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show(
            "Control panel did not become ready at $Url`nCheck the minimized Python window for errors.",
            "MoneyPrinterV2",
            "OK",
            "Warning"
        ) | Out-Null
        exit 1
    }
}

Start-Process $Url
