# ULTRON

## Personal AI Assistant — Production-Hardened Windows Platform

ULTRON is a local-first personal AI assistant designed to provide intelligent
conversation, automation, device control, browser interaction, voice
interaction, memory, scheduling, and multi-agent orchestration while
maintaining a strict security boundary around every executable action.

The project is implemented phase-by-phase with security, verification,
observability, and regression testing treated as first-class requirements.

---

## Current Status

### Phase 1–19 — MVP
**SHIPPED**

### Phase 21–27 — Advanced / Production Hardening
**COMPLETED**

### Phase 28 — JARVIS Terminal / Autonomous CLI Experience
**COMPLETED**

- Single-command interactive JARVIS terminal launcher (`.\ultron.ps1`)
- Automatic backend lifecycle management with safe PID tracking and clean shutdown
- Interactive ANSI status dashboard displaying live backend component health
- Authenticated session management via `X-ULTRON-AUTH` and `SessionManager`
- Real-time confirmation broker polling and interactive CLI approval prompts
- Full preservation of existing security boundaries (ALWAYS_ASK, CRITICAL, SafetyGate, AuditLogger)
- Zero bypass or direct tool execution: all CLI turns route through the standard REST conversation pipeline

### Phase 29 — ULTRON JARVIS-Style Voice Assistant
**COMPLETED**

- Movie-style JARVIS voice assistant experience with single-wake-word activation ("Hey ULTRON" / "ULTRON")
- Continuous Active Conversation: wake word is NOT required between follow-up commands once activated
- Automatically transitions from speaking back to listening with watchdog inactivity timeout (`VOICE_CONVERSATION_TIMEOUT_SECONDS = 15.0s`)
- Natural voice confirmation ("yes", "confirm", "go ahead") and rejection ("no", "cancel") resolving through `ConfirmationBroker`
- Full-duplex voice interruption (barge-in cuts active TTS playback immediately)
- Push-to-talk (`ptt`) fallback mode for seamless interaction without continuous microphone streaming
- Integrated CLI voice mode (`ULTRON > voice`, `voice off`) and desktop sidebar voice indicator
- 100% preservation of security pipeline: voice commands route strictly through `ConversationManager`, with no direct tool handler or LLM execution

---

## Getting Started

### JARVIS Terminal (Recommended)

Launch the full interactive assistant experience with one command from the project root:

```powershell
.\ultron.ps1
```

This will automatically:
1. Check if the ULTRON backend is already running on `http://127.0.0.1:8756`.
2. Start the backend if not running and wait for health readiness.
3. Authenticate using the local token abstraction.
4. Establish a secure session and display the live system dashboard.
5. Provide continuous conversational interaction.
6. Cleanly invalidate the session and shut down only the launcher-spawned backend on exit.

### Development / Direct CLI

To run the CLI directly against an existing backend instance:

```powershell
cd backend
.venv\Scripts\python.exe -m app.cli.main
```

### Terminal Commands

Inside the ULTRON terminal:
- `help` — Show available CLI commands.
- `status` — Display live backend, database, AI provider, device, and session status.
- `clear` — Clear the terminal screen and refresh the banner.
- `exit` / `quit` / `shutdown` — Cleanly invalidate the session and exit.
- Any other text — Processed as a natural-language request through the standard ULTRON agent pipeline.

---

The current architecture includes:

- AI provider management
- Conversation engine
- Tool registry and execution pipeline
- Permission management
- Safety Gate
- Confirmation Broker
- Audit logging
- Emergency Stop
- Task management and worker execution
- Windows semantic UI automation
- Browser automation with SSRF protection
- Long-term memory
- Gmail and Google Calendar integration
- Android device pairing and automation
- Voice STT/TTS pipeline
- Wake-word and conversation mode
- Full-duplex voice with barge-in
- Scheduled automations
- Multi-agent orchestration
- Vision/multimodal capabilities
- Performance and concurrency improvements
- SQLite WAL configuration
- Backpressure and resource limits
- Final production security hardening

---

# Architecture

ULTRON consists primarily of three layers:

```text
┌──────────────────────────────────────────────┐
│              Desktop Application             │
│        Tauri v2 + React + TypeScript         │
└──────────────────────┬───────────────────────┘
                       │
                       │ Local HTTP / WebSocket
                       ▼
┌──────────────────────────────────────────────┐
│                 FastAPI Backend               │
│                                              │
│  Authentication                              │
│       ↓                                      │
│  Conversation / Agent Orchestration          │
│       ↓                                      │
│  Tool Registry                               │
│       ↓                                      │
│  Permission Store                            │
│       ↓                                      │
│  Safety Gate                                 │
│       ↓                                      │
│  Confirmation Broker                         │
│       ↓                                      │
│  Tool Executor                               │
│       ↓                                      │
│  Verification                                │
│       ↓                                      │
│  Audit Log                                   │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
              SQLite / Local Storage