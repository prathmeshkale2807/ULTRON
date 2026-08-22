# Run this in PowerShell from the repo root: .\scripts\dev-desktop.ps1
# Starts the ULTRON desktop shell (Tauri + React) in dev mode.
# The backend (.\scripts\dev-backend.ps1) must be running first --
# the UI will show "unreachable" in its status card otherwise, which is
# the correct/honest behavior, not a bug.

$ErrorActionPreference = "Stop"

Set-Location "$PSScriptRoot\..\apps\desktop"

Write-Host "Installing frontend dependencies..."
npm install

Write-Host "Starting ULTRON desktop shell..."
npm run tauri dev
