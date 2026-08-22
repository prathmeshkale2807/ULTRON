# Run this in PowerShell from the repo root: .\scripts\run-tests.ps1
# Runs the backend test suite.

$ErrorActionPreference = "Stop"

Set-Location "$PSScriptRoot\..\backend"

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

& ".venv\Scripts\Activate.ps1"
pip install -r requirements.txt

Write-Host "Running backend test suite..."
pytest -v
