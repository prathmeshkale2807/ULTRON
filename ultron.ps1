#Requires -Version 5.1
<#
.SYNOPSIS
    ULTRON One-Command JARVIS Launcher — Phase 30

.DESCRIPTION
    Single-command entry point for the ULTRON personal AI assistant.

    Behaviour:
    1. Locates the repository root and the backend .venv.
    2. Detects whether the backend is already running on port 8756.
       - If already running: connects to it without starting a duplicate.
       - If not running: starts it and records the exact PID.
    3. Waits for /api/health to return 200 (up to 30 seconds).
    4. Starts the interactive ULTRON JARVIS CLI/voice interface.
    5. On exit: only terminates the backend process started by THIS launcher.
       Never kills unrelated Python processes or all listeners on the port.
    6. Handles Ctrl+C gracefully.

.PARAMETER DebugMode
    Enables verbose diagnostic logging.

.NOTES
    Security: this launcher never reads, prints, or logs the local auth token.
    It does not bypass any ULTRON security mechanism.
#>

[CmdletBinding()]
param (
    [switch]$DebugMode
)

$ErrorActionPreference = "Stop"

if ($DebugMode) {
    $env:ULTRON_LOG_LEVEL = "DEBUG"
}

# ── Locate repository root and Python interpreter ─────────────────────────
$Root    = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Python  = Join-Path $Backend ".venv\Scripts\python.exe"

# ── Constants ──────────────────────────────────────────────────────────────
$BackendUrl    = "http://127.0.0.1:8756"
$HealthUrl     = "$BackendUrl/api/health"
$MaxWaitSec    = 30
$PollMs        = 500

# ── Helper: test if backend is already healthy ─────────────────────────────
function Test-BackendHealthy {
    try {
        $r = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

# ── Verify .venv exists ───────────────────────────────────────────────────
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

# ── Detect whether backend is already running ──────────────────────────────
$BackendProcess  = $null   # process started BY THIS LAUNCHER (null = not started)
$BackendOwned    = $false  # true only if we started it ourselves

if (-not (Test-BackendHealthy)) {
    Write-Host "  [1/2] Starting ULTRON backend..."

    try {
        $startInfo = New-Object System.Diagnostics.ProcessStartInfo
        $startInfo.FileName               = $Python
        $startInfo.Arguments              = "-m uvicorn app.main:app --host 127.0.0.1 --port 8756 --no-access-log"
        $startInfo.WorkingDirectory       = $Backend
        $startInfo.UseShellExecute        = $false
        $startInfo.RedirectStandardOutput = $false
        $startInfo.RedirectStandardError  = $false
        $startInfo.WindowStyle            = [System.Diagnostics.ProcessWindowStyle]::Minimized

        $BackendProcess = [System.Diagnostics.Process]::Start($startInfo)
        $BackendOwned   = $true

        if ($null -eq $BackendProcess) {
            Write-Host "  ERROR: Failed to start backend process."
            exit 1
        }

        Write-Host "  Backend PID   $($BackendProcess.Id)"
    } catch {
        Write-Host "  ERROR: Could not start backend: $_"
        exit 1
    }

    # ── Wait for backend to become healthy ────────────────────────────────
    Write-Host "  [2/2] Waiting for backend to become healthy..."

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
}

# ── Start the JARVIS Terminal CLI ──────────────────────────────────────────
$CliExitCode = 0

try {
    Push-Location $Backend
    & $Python -m app.cli.main
    $CliExitCode = $LASTEXITCODE
} catch {
    Write-Host "  ERROR: CLI crashed: $_"
    $CliExitCode = 1
} finally {
    Pop-Location

    # Only terminate the backend process THIS LAUNCHER started.
    # Never kill unrelated Python processes or all port-8756 listeners.
    if ($BackendOwned -and $null -ne $BackendProcess -and -not $BackendProcess.HasExited) {
        Write-Host ""
        Write-Host "  Stopping ULTRON backend (PID $($BackendProcess.Id))..."
        try {
            Stop-Process -Id $BackendProcess.Id -Force -ErrorAction SilentlyContinue
            $BackendProcess.WaitForExit(3000) | Out-Null
        } catch {
            # Best-effort
        }
        Write-Host "  Backend stopped."
    }

    Write-Host ""
    Write-Host "  ULTRON offline."
    Write-Host ""
}

exit $CliExitCode
