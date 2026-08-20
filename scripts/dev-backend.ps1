# Run this in PowerShell from the repo root: .\scripts\dev-backend.ps1
# Starts the ULTRON backend with auto-reload for development.

$ErrorActionPreference = "Stop"

Set-Location "$PSScriptRoot\..\backend"

$pyVersion = (python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if ([version]$pyVersion -lt [version]"3.12") {
    Write-Error "Python 3.12+ required, found $pyVersion. Install from https://www.python.org/downloads/"
    exit 1
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creating Python virtual environment..."
    python -m venv .venv
}

Write-Host "Activating virtual environment..."
& ".venv\Scripts\Activate.ps1"

Write-Host "Installing/updating dependencies..."
pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Write-Host "No .env found -- copying .env.example. Edit .env before Phase 2 (API keys)."
    Copy-Item ".env.example" ".env"
}

Write-Host "Applying database migrations..."
alembic upgrade head

Write-Host "Starting ULTRON backend on http://127.0.0.1:8756 ..."
uvicorn app.main:app --host 127.0.0.1 --port 8756 --reload
