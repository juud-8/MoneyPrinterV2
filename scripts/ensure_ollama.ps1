# Ensure Ollama API is reachable; start ollama serve if needed (Windows).
param(
    [int]$MaxWaitSeconds = 45
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Get-OllamaBaseUrl {
    $configPath = Join-Path $Root "config.json"
    if (Test-Path $configPath) {
        try {
            $cfg = Get-Content $configPath -Raw | ConvertFrom-Json
            if ($cfg.ollama_base_url) {
                return $cfg.ollama_base_url.TrimEnd("/")
            }
        } catch {
            # fall through to default
        }
    }
    return "http://127.0.0.1:11434"
}

function Test-OllamaReady {
    param([string]$BaseUrl)
    try {
        $null = Invoke-RestMethod -Uri "$BaseUrl/api/tags" -TimeoutSec 3
        return $true
    } catch {
        return $false
    }
}

function Find-OllamaExe {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
        (Join-Path $env:ProgramFiles "Ollama\ollama.exe")
    )

    foreach ($path in $candidates) {
        if (Test-Path $path) {
            return $path
        }
    }

    return $null
}

$baseUrl = Get-OllamaBaseUrl

if (Test-OllamaReady -BaseUrl $baseUrl) {
    Write-Host "[OK] Ollama already running at $baseUrl"
    exit 0
}

$ollamaExe = Find-OllamaExe
if (-not $ollamaExe) {
    Write-Error "Ollama not found in PATH or default install locations. Install from https://ollama.com"
    exit 1
}

Write-Host "[..] Starting Ollama: $ollamaExe serve"
Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden

$deadline = (Get-Date).AddSeconds($MaxWaitSeconds)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
    if (Test-OllamaReady -BaseUrl $baseUrl) {
        Write-Host "[OK] Ollama ready at $baseUrl"
        exit 0
    }
}

Write-Error "Ollama did not become ready within ${MaxWaitSeconds}s at $baseUrl"
exit 1
