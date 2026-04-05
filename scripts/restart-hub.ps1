#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Restart Hub with latest code.
.DESCRIPTION
    1. git pull --ff-only
    2. pip install -e .
    3. Stop running Hub process (singleton lock release)
    4. Start Hub using settings from .env (COPILOT_MODEL, COPILOT_AUTOPILOT)
.PARAMETER Model
    Override COPILOT_MODEL from .env
.PARAMETER Autopilot
    Override COPILOT_AUTOPILOT from .env
.PARAMETER Cwd
    Default working directory for Copilot sessions
.PARAMETER Timeout
    Hub timeout in minutes (default: 60, 0 = unlimited)
.PARAMETER SkipPull
    Skip git pull (use current code)
.PARAMETER Verbose
    Enable debug logging
.EXAMPLE
    .\restart-hub.ps1
    .\restart-hub.ps1 -Autopilot -Model claude-sonnet-4.6
    .\restart-hub.ps1 -SkipPull -Verbose
#>

param(
    [string]$Model     = "",
    [switch]$Autopilot,
    [string]$Cwd       = "",
    [int]   $Timeout   = 60,
    [switch]$SkipPull,
    [switch]$Verbose
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path $PSScriptRoot -Parent

# --- Load .env -----------------------------------------------------------
$EnvFile = Join-Path $RepoRoot ".env"
if (Test-Path $EnvFile) {
    Write-Host "[INFO] Loading .env ..." -ForegroundColor Cyan
    Get-Content $EnvFile -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        # skip comments and blank lines
        if (-not $line -or $line.StartsWith('#')) { return }
        # strip optional "export " prefix
        if ($line.StartsWith('export ')) { $line = $line.Substring(7).TrimStart() }
        if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $key   = $Matches[1]
            $value = $Matches[2].Trim() -replace '^[''"]|[''"]$', ''
            # env vars already set take priority
            if (-not [System.Environment]::GetEnvironmentVariable($key)) {
                [System.Environment]::SetEnvironmentVariable($key, $value, "Process")
            }
        }
    }
} else {
    Write-Warning ".env not found: $EnvFile"
}

# --- Validate required vars ----------------------------------------------
# Hub falls back TELEGRAM_BOT_TOKEN if HUB_BOT_TOKEN is not set (see config.py)
$BotToken = [System.Environment]::GetEnvironmentVariable("TELEGRAM_HUB_BOT_TOKEN")
if (-not $BotToken) { $BotToken = [System.Environment]::GetEnvironmentVariable("TELEGRAM_BOT_TOKEN") }
$ChatId = [System.Environment]::GetEnvironmentVariable("TELEGRAM_CHAT_ID")

if (-not $BotToken -or -not $ChatId) {
    Write-Error "Required: TELEGRAM_BOT_TOKEN (or TELEGRAM_HUB_BOT_TOKEN) + TELEGRAM_CHAT_ID"
    exit 1
}

# --- Resolve model/autopilot from .env or CLI args -----------------------
if (-not $Model) {
    $Model = [System.Environment]::GetEnvironmentVariable("COPILOT_MODEL")
    if (-not $Model) { $Model = "claude-opus-4.6" }
}
if (-not $Autopilot) {
    $envAuto = [System.Environment]::GetEnvironmentVariable("COPILOT_AUTOPILOT")
    if ($envAuto -in @("true", "1", "yes")) { $Autopilot = $true }
}

Write-Host ""
Write-Host "=== Hub Restart ===" -ForegroundColor Green
Write-Host "  Model    : $Model"
Write-Host "  Autopilot: $Autopilot"
Write-Host "  Timeout  : $Timeout min"
Write-Host ""

# --- [1/4] git pull ------------------------------------------------------
if (-not $SkipPull) {
    Write-Host "[1/4] git pull --ff-only ..." -ForegroundColor Cyan
    Push-Location $RepoRoot
    try {
        git pull --ff-only
        if ($LASTEXITCODE -ne 0) { Write-Error "git pull failed (exit $LASTEXITCODE)"; exit 1 }
    } finally { Pop-Location }
} else {
    Write-Host "[1/4] git pull ... SKIPPED" -ForegroundColor Gray
}

# --- [2/4] pip install ----------------------------------------------------
Write-Host "[2/4] pip install -e . ..." -ForegroundColor Cyan
Push-Location $RepoRoot
try {
    python -m pip install -e . --quiet
    if ($LASTEXITCODE -ne 0) { Write-Error "pip install failed (exit $LASTEXITCODE)"; exit 1 }
} finally { Pop-Location }

# --- [3/4] Stop existing Hub (singleton lock release) ---------------------
Write-Host "[3/4] Stopping existing Hub ..." -ForegroundColor Cyan
$LockPort = [System.Environment]::GetEnvironmentVariable("HUB_LOCK_PORT")
if (-not $LockPort) { $LockPort = 47732 }

# Method 1: Find process holding the singleton lock port
$LockHolder = Get-NetTCPConnection -LocalPort $LockPort -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($LockHolder) {
    $pid_to_kill = $LockHolder.OwningProcess
    Write-Host "  Stopping Hub PID $pid_to_kill (lock port $LockPort)" -ForegroundColor Yellow
    Stop-Process -Id $pid_to_kill -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
} else {
    # Method 2: Fallback - find by command line
    $HubPIDs = Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*telegram_copilot_bridge*--hub*" } |
        Select-Object -ExpandProperty ProcessId
    if ($HubPIDs) {
        $HubPIDs | ForEach-Object {
            Write-Host "  Stopping Hub PID $_" -ForegroundColor Yellow
            Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 2
    } else {
        Write-Host "  No running Hub found" -ForegroundColor Gray
    }
}

# --- [4/4] Start Hub ------------------------------------------------------
$HubArgs = @("-m", "telegram_copilot_bridge", "--hub")
$HubArgs += @("--model", $Model)
if ($Autopilot) { $HubArgs += "--autopilot" }
if ($Cwd)       { $HubArgs += @("--cwd", $Cwd) }
$HubArgs += @("--timeout", "$Timeout")
if ($Verbose)   { $HubArgs += "--verbose" }

Write-Host "[4/4] Starting Hub ..." -ForegroundColor Green
Write-Host "  python $($HubArgs -join ' ')" -ForegroundColor Gray
Write-Host ""

Push-Location $RepoRoot
python @HubArgs
Pop-Location
