#Requires -Version 5.1
<#
.SYNOPSIS
    ULTRON One-Command JARVIS Launcher

.DESCRIPTION
    Single-command entry point for the ULTRON JARVIS personal AI assistant.

    Behaviour:
    1. Locates the repository root and the backend .venv.
    2. Detects whether the backend is already running on port 8756.
       - If already running: connects to it without starting a duplicate.
       - If not running: starts it and records the exact PID.
    3. Waits for /api/health to return 200 (up to 30 seconds).
    4. Launches the futuristic Desktop HUD UI in the browser.
    5. Starts the ULTRON JARVIS voice assistant (microphone -> AI -> speaker).
    6. On exit: only terminates the backend process started by THIS launcher.
       Never kills unrelated Python processes or all listeners on the port.
    7. Handles Ctrl+C gracefully.

.PARAMETER DebugMode
    Enables verbose diagnostic logging.

.PARAMETER NoUI
    Skip launching the desktop HUD. Voice-only mode.

.NOTES
    Security: this launcher never reads, prints, or logs the local auth token.
    It does not bypass any ULTRON security mechanism.
#>

[CmdletBinding()]
param (
    [switch]$DebugMode,
    [switch]$NoUI
)

$ErrorActionPreference = "Stop"

if ($DebugMode) {
    $env:ULTRON_LOG_LEVEL = "DEBUG"
}

# Locate repository root and Python interpreter
$Root        = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend     = Join-Path $Root "backend"
$Desktop     = Join-Path $Root "apps\desktop"
$Python      = Join-Path $Backend ".venv\Scripts\python.exe"
$NodeModules = Join-Path $Desktop "node_modules"

# Constants
$BackendUrl = "http://127.0.0.1:8756"
$HealthUrl  = "$BackendUrl/api/health"
$UiUrl      = "http://127.0.0.1:1420"
$MaxWaitSec = 30
$PollMs     = 500

# Helper: test if backend is already healthy
function Test-BackendHealthy {
    try {
        $r = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

# Helper: test if a local dev server is responding
function Test-UiReady {
    param([string]$Url)
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        return ($r.StatusCode -lt 500)
    } catch {
        return $false
    }
}

# Verify .venv exists
if (-not (Test-Path $Python)) {
    Write-Host "  ERROR: Python virtual environment not found."
    Write-Host ""
    Write-Host "  Expected: $Python"
    Write-Host ""
    Write-Host "  Run the following from the backend directory to create it:"
    Write-Host "    python -m venv .venv"
    Write-Host "    .venv\Scripts\pip install -r requirements.txt"
    Write-Host ""
    exit 1
}

# Track what this launcher started so we only clean up our own processes
$BackendProcess = $null
$BackendOwned   = $false
$UiProcess      = $null
$UiOwned        = $false

# Auto-migrate database (idempotent)
Push-Location $Backend
try {
    & $Python -m alembic upgrade head 2>&1 | Out-Null
} catch { }
Pop-Location

# Start backend if not already running
if (-not (Test-BackendHealthy)) {
    Write-Host "  [1/3] Starting ULTRON backend..."

    $LogDir     = Join-Path $Backend "logs"
    $LogFileOut = Join-Path $LogDir "backend.log"
    $LogFileErr = Join-Path $LogDir "backend.err.log"
    if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

    try {
        $BackendProcess = Start-Process `
            -FilePath $Python `
            -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port 8756 --no-access-log" `
            -WorkingDirectory $Backend `
            -RedirectStandardOutput $LogFileOut `
            -RedirectStandardError $LogFileErr `
            -WindowStyle Hidden `
            -PassThru

        $BackendOwned = $true

        if ($null -eq $BackendProcess) {
            Write-Host "  ERROR: Failed to start backend process."
            exit 1
        }

        Write-Host "  Backend PID   $($BackendProcess.Id)  (logs -> backend/logs/backend.log)"
    } catch {
        Write-Host "  ERROR: Could not start backend: $_"
        exit 1
    }

    Write-Host "  [2/3] Waiting for backend to become healthy..."

    $Ready   = $false
    $Elapsed = 0

    while ($Elapsed -lt $MaxWaitSec) {
        Start-Sleep -Milliseconds $PollMs
        $Elapsed += ($PollMs / 1000)

        if ($BackendOwned -and $BackendProcess.HasExited) {
            Write-Host ""
            Write-Host "  ERROR: Backend process exited unexpectedly (exit code $($BackendProcess.ExitCode))."
            Write-Host "  Check the backend logs for details."
            exit 1
        }

        if (Test-BackendHealthy) {
            $Ready = $true
            break
        }
    }

    if (-not $Ready) {
        Write-Host ""
        Write-Host "  ERROR: ULTRON backend failed to become healthy within ${MaxWaitSec}s."
        if ($BackendOwned -and -not $BackendProcess.HasExited) {
            Stop-Process -Id $BackendProcess.Id -Force -ErrorAction SilentlyContinue
        }
        exit 1
    }

    Write-Host "  Backend       ONLINE"
} else {
    Write-Host "  Backend       ALREADY ONLINE (external process)"
}

# Launch Futuristic Desktop HUD UI
if (-not $NoUI) {
    Write-Host "  [3/3] Launching ULTRON JARVIS Desktop HUD..."

    $NpmCmd = Get-Command npm -ErrorAction SilentlyContinue

    if (($null -ne $NpmCmd) -and (Test-Path $NodeModules)) {
        $UiLogOut = Join-Path (Join-Path $Backend "logs") "ui.log"
        $UiLogErr = Join-Path (Join-Path $Backend "logs") "ui.err.log"

        $UiProcess = Start-Process `
            -FilePath "npm.cmd" `
            -ArgumentList "run", "dev" `
            -WorkingDirectory $Desktop `
            -RedirectStandardOutput $UiLogOut `
            -RedirectStandardError $UiLogErr `
            -WindowStyle Hidden `
            -PassThru

        $UiOwned = $true

        if ($null -ne $UiProcess) {
            Write-Host "  UI Dev Server PID $($UiProcess.Id)  (logs -> backend/logs/ui.log)"

            # Wait up to 15s for Vite to be ready
            $UiElapsed = 0
            $UiReady   = $false
            while ($UiElapsed -lt 15) {
                Start-Sleep -Seconds 1
                $UiElapsed++
                if (Test-UiReady -Url $UiUrl) {
                    $UiReady = $true
                    break
                }
            }

            if ($UiReady) {
                Start-Process $UiUrl
                Write-Host "  Desktop HUD   ONLINE -> $UiUrl"
            } else {
                Start-Process $UiUrl
                Write-Host "  Desktop HUD   Starting (browser will open when ready)"
            }
        } else {
            Write-Host "  Desktop HUD   SKIPPED (could not start npm dev server)"
        }
    } else {
        Write-Host "  Desktop HUD   SKIPPED (run: cd apps\desktop then npm install)"
    }
}

Write-Host ""
Write-Host "  +--------------------------------------------------+"
Write-Host "  |         ULTRON JARVIS  --  ONLINE                |"
Write-Host "  +--------------------------------------------------+"
Write-Host ""
Write-Host "  Voice is the primary interface."
Write-Host "  Wake phrase : Hey ULTRON"
Write-Host "  HUD URL     : $UiUrl"
Write-Host ""

# Start the JARVIS Voice Assistant (microphone -> AI -> speaker)
$CliExitCode = 0

try {
    Push-Location $Backend
    & $Python -m app.cli.main
    $CliExitCode = $LASTEXITCODE
} catch {
    Write-Host "  ERROR: Voice assistant crashed: $_"
    $CliExitCode = 1
} finally {
    Pop-Location

    # Stop Vite dev server if WE started it
    if ($UiOwned -and ($null -ne $UiProcess) -and (-not $UiProcess.HasExited)) {
        try {
            Stop-Process -Id $UiProcess.Id -Force -ErrorAction SilentlyContinue
            $UiProcess.WaitForExit(2000) | Out-Null
        } catch { }
        Write-Host "  Desktop HUD stopped."
    }

    # Only terminate the backend process THIS LAUNCHER started
    if ($BackendOwned -and ($null -ne $BackendProcess) -and (-not $BackendProcess.HasExited)) {
        Write-Host ""
        Write-Host "  Stopping ULTRON backend (PID $($BackendProcess.Id))..."
        try {
            Stop-Process -Id $BackendProcess.Id -Force -ErrorAction SilentlyContinue
            $BackendProcess.WaitForExit(3000) | Out-Null
        } catch { }
        Write-Host "  Backend stopped."
    }

    Write-Host ""
    Write-Host "  ULTRON offline."
    Write-Host ""
}

exit $CliExitCode
