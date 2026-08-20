# ULTRON — Phase 1: Project Scaffolding

Personal AI assistant, built phase-by-phase per the approved architecture.
This phase contains **real infrastructure only** — no PC control, no
Android control, no AI calls, no voice yet. Every component either works
for real or is explicitly reported as `not_implemented`; nothing is faked.

## What exists in Phase 1

- **Backend** (`backend/`): Python + FastAPI service. Real SQLite database,
  real logging, one real endpoint (`/api/health`) that proves the database
  round-trip works and honestly reports which components don't exist yet.
- **Desktop shell** (`apps/desktop/`): Tauri + React. Polls the backend's
  health endpoint and renders the real response — connected/unreachable
  state is genuine, not simulated.
- **Tests** (`backend/tests/`): exercise the real app + real temp database
  via FastAPI's TestClient.

## Prerequisites (Windows)

Install these first:

1. **Python 3.12+** — https://www.python.org/downloads/ (check "Add to PATH")
2. **Node.js 20+ LTS** — https://nodejs.org/
3. **Rust toolchain** (required by Tauri) — https://rustup.rs/
   - After installing, restart your terminal and run `rustc --version` to confirm.
4. **Visual Studio Build Tools** (Tauri's Windows build dependency) —
   install the "Desktop development with C++" workload from
   https://visualstudio.microsoft.com/visual-cpp-build-tools/
5. **WebView2** — usually already present on Windows 10/11; if not,
   https://developer.microsoft.com/microsoft-edge/webview2/

Verify each in **PowerShell**:

```powershell
python --version
node --version
npm --version
rustc --version
cargo --version
```

## First-time setup

In **PowerShell**, from the repo root:

```powershell
Copy-Item backend\.env.example backend\.env
# (Phase 1 doesn't need any real API keys yet — the defaults work as-is.)
```

## Running it

Two terminals, both **PowerShell**, both from the repo root:

**Terminal 1 — backend:**
```powershell
.\scripts\dev-backend.ps1
```
This creates a virtual environment, installs dependencies, and starts the
API on `http://127.0.0.1:8756`. Visit `http://127.0.0.1:8756/api/health`
in a browser to see the raw JSON.

**Terminal 2 — desktop app:**
```powershell
.\scripts\dev-desktop.ps1
```
This installs frontend dependencies and opens the ULTRON window. It
should show `connected` and list the database as `ok`, with everything
else listed as `not_implemented`.

## Running tests

```powershell
.\scripts\run-tests.ps1
```

## Database migrations

Schema changes are owned by Alembic, not `create_all()`. `dev-backend.ps1`
runs `alembic upgrade head` automatically before starting the server. To
run it manually or create a new migration later:

```powershell
cd backend
.venv\Scripts\Activate.ps1
alembic upgrade head                          # apply migrations
alembic revision --autogenerate -m "message"  # create a new one (future phases)
```

## Known limitation of this scaffold

This code was written and syntax-checked in a Linux sandbox without
network access or a Windows/Rust toolchain, so the FastAPI/SQLAlchemy
dependency-level behavior and the Tauri build have **not** been runtime-
verified end-to-end yet — only Python syntax-compiled. The commands above
are the actual verification step; run them on your machine and treat the
Phase 1 completion report's "known issues" section as provisional until
you've done so. See `docs/PHASE_1_COMPLETION_REPORT.md`.

## Project structure

```
ultron/
├── apps/desktop/        # Tauri + React frontend
├── backend/              # FastAPI core service
│   ├── app/
│   │   ├── api/          # HTTP routes
│   │   └── core/         # config, logging, database
│   └── tests/
├── scripts/               # Windows PowerShell dev scripts
└── docs/
```

Later phases add `backend/app/agents/`, `backend/app/tools/`,
`backend/app/permissions/`, `backend/app/devices/`, `backend/app/voice/`,
etc., per the approved architecture — deliberately not scaffolded yet so
Phase 1 stays reviewable and doesn't contain empty placeholder modules.
