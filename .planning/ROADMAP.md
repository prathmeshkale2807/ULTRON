# Roadmap: ULTRON

## Overview
ULTRON is a Personal AI Assistant built phase-by-phase per an approved architecture, maintaining strict boundaries between untrusted AI logic and local execution.

## Core Principles & Rules

**PERMANENT RULE**: 
Completed phases are frozen baselines. Future phases must preserve prior security and safety boundaries and pass the full regression suite.

**Major Architectural Principles**:
- **Untrusted AI**: AI content is inherently untrusted.
- **Strict Safety Boundaries**: The execution pipeline (Auth -> Orchestrator -> Safety Gate -> Confirmation -> Executor -> Verification -> Audit) must never be bypassed.
- **Side-Effect Safety**: No direct external side-effects without explicit validation and user confirmation. E2E external integrations must be mockable in standard CI.
- **Idempotency & Recovery**: Idempotent/safe actions use bounded retries. Non-idempotent actions never retry blindly.

## Milestones

- ✅ **v1.0 MVP** - Phases 1-19 (SHIPPED)
- ✅ **v2.0 Advanced Capabilities** - Phases 21-27 (SHIPPED)

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 1-19) - SHIPPED</summary>

### Phase 1: Project Scaffolding / Local Auth Foundation
**Status**: SHIPPED
**Goal**: Initial scaffolding, backend health checks, and desktop app integration.
**Test Baseline**: N/A

### Phase 2: AI Provider Manager
**Status**: SHIPPED
**Goal**: Integration of AI adapters (Claude/Gemini) with sensitivity-gated routing.
**Test Baseline**: N/A

### Phase 3: Tool Registry + Safety Gate + Tool Executor
**Status**: SHIPPED
**Goal**: Tool registration and structured execution pipelines.
**Test Baseline**: N/A

### Phase 4: Permissions, Profiles, Audit, Emergency Stop
**Status**: SHIPPED
**Goal**: Profiling, permission models, and the Safety Gate evaluation engine.
**Test Baseline**: N/A

### Phase 5: Task Manager + Worker + Cancellation
**Status**: SHIPPED
**Goal**: Priority queues, asynchronous background worker execution, and task cancellation boundaries.
**Test Baseline**: N/A

### Phase 6: Windows PC Control
**Status**: SHIPPED
**Goal**: PC automation via local desktop integration.
**Test Baseline**: N/A

### Phase 7: Conversation Engine + Orchestrator
**Status**: SHIPPED
**Goal**: Conversations, planning, and task generation orchestration.
**Test Baseline**: N/A

### Phase 8: Browser Automation
**Status**: SHIPPED
**Goal**: Browser automation integration with strict safety boundaries and localhost/private IP blocking.
**Test Baseline**: N/A

### Phase 9: Long-Term Memory
**Status**: SHIPPED
**Goal**: Contextual recall and long-term memory for agent profiles.
**Test Baseline**: N/A

### Phase 10: Email + Calendar
**Status**: SHIPPED
**Goal**: External integrations for Email and Calendar scheduling.
**Test Baseline**: N/A

### Phase 11: Device Manager + Android Companion
**Status**: SHIPPED
**Goal**: Secure Android device pairing, per-principal device ownership, authenticated heartbeats, device lifecycle management, and the backend foundation for the Android companion.
**Test Baseline**: N/A

### Phase 12: Basic Android Control + WebSocket Transport
**Status**: SHIPPED
**Goal**: Real Android companion interaction through an authenticated WebSocket transport, including basic device status, location, SMS, app opening, and volume control with verification and safety enforcement.
**Test Baseline**: N/A

### Phase 13: Voice Engine
**Status**: SHIPPED
**Goal**: Streaming audio processing, voice activity detection, and STT/TTS pipelines.
**Test Baseline**: N/A

### Phase 14: Wake Word + Conversation Mode
**Status**: SHIPPED
**Goal**: Hardened voice pipeline with watchdog timeouts and emergency stop bounds.
**Test Baseline**: N/A

### Phase 15: Full-Duplex Voice + Barge-In
**Status**: SHIPPED
**Goal**: Real-time conversational interruption (barge-in) and state synchronization.
**Test Baseline**: N/A

### Phase 16: Advanced Android Automation
**Status**: SHIPPED
**Goal**: Controlled Android automation capabilities including notification access, allowlisted intents, media control, brightness/settings control, app discovery, battery information, request correlation, cancellation, and read-back verification.
**Test Baseline**: N/A

### Phase 17: Automations + Scheduler
**Status**: SHIPPED
**Goal**: Robust atomicity, idempotency checks, and crash recovery for the background scheduler.
**Test Baseline**: 274 passed, 0 failed, 5 skipped

### Phase 18: Security Hardening
**Status**: SHIPPED
**Goal**: Dedicated security audit focusing on Trust Boundaries, SSRF checks, Auth Bypasses, and Race Conditions.
**Test Baseline**: 280 passed, 0 failed, 5 skipped

### Phase 19: Full-System Validation + Reliability
**Status**: SHIPPED
**Goal**: Prove complete architectural resilience, concurrent state safety, crash recovery, and E2E boundaries.
**Test Baseline**: 294 passed, 0 failed, 5 skipped

</details>

<details>
<summary>✅ v2.0 Advanced Capabilities (Phases 21-27) - SHIPPED</summary>

### Phase 21: Production Deployment & Packaging
**Status**: SHIPPED
**Goal**: Production deployment configuration, packaging, and distribution pipelines.
**Delivered**: PyInstaller-packaged backend (`ultron-backend.spec`), Tauri v2 MSI/NSIS installers, `externalBin` integration in `tauri.conf.json`, WAL mode + file-locking for migration safety, PyInstaller-aware path resolution in `database.py` and `config.py`.

### Phase 22: UI/UX & Desktop/Android Experience
**Status**: SHIPPED
**Goal**: Frontend polish, UX improvements, and richer Desktop/Android app interfaces.
**Delivered**: Tauri + React 18 desktop UI with Chat, Tasks, Devices, and Security views. Image attachment pipeline with multimodal send. CSS design system with custom properties.

### Phase 23: Vision / Multimodal Interaction
**Status**: SHIPPED
**Goal**: Computer vision and multimodal input processing integration.
**Delivered**: `process_image()` Pillow-based validator (magic-byte parsing, decompression-bomb mitigation, 5MB limit, 2048×2048 cap, format allowlist). `AttachmentRecord` model and authenticated `/api/attachments/{id}` endpoint. Multimodal `ContentPart` threading through ConversationManager → AI providers.

### Phase 24: Multi-Agent Orchestration
**Status**: SHIPPED
**Goal**: Support for distributed and concurrent multi-agent collaboration and planning.
**Delivered**: `AgentManager` with budget guards (MAX_DEPTH=3, MAX_AGENTS_PER_TASK=5, MAX_MESSAGES_PER_TASK=50), EmergencyStop gate on agent spawn/messaging, `AgentRecord` + `AgentMessageRecord` DB models, terminal-state immutability, cascading cancellation.

### Phase 25: Advanced Device Automation
**Status**: SHIPPED
**Goal**: Deeper OS-level and application-level automation capabilities.
**Delivered**: Extended Android tools (notification access, allowlisted intents, media control, brightness, app discovery, battery, request correlation, cancellation, read-back verification). Extended Windows tools (application management, process control, screenshots, system info).

### Phase 26: Performance & Scalability
**Status**: SHIPPED
**Goal**: Optimization for latency, concurrent scaling, and resource efficiency.
**Delivered**: SQLite WAL mode (`PRAGMA journal_mode=WAL`), `PRAGMA synchronous=NORMAL`, `PRAGMA busy_timeout=5000`, WAL permission syncing. `TaskWorker` with bounded asyncio priority queue (max 1000), semaphore-capped concurrency (max 16), `run_in_threadpool` for all DB-blocking calls in `ConversationManager`.

### Phase 27: Final Production Security Audit
**Status**: SHIPPED
**Goal**: Ultimate production-grade security, penetration testing, and trust boundary validation.
**Delivered**: Windows ACL enforcement via `icacls` on ULTRON data directory at startup. SSRF DNS-resolution checks with private-IP blocking. Browser network policy (`allow_local_network_browser`). Input sanitization (`normalize_actor`). One-time short-lived WebSocket connection tickets for Voice and Devices. `test_phase27_ssrf.py` and `test_phase27_windows_acl.py` added to regression suite.
**Final Test Baseline**: 329 passed, 0 failed, 3 skipped (backend) + 3 passed, 0 failed (frontend)

**Residual Known Risk**: DNS-rebinding TOCTOU — `validate_url_safe()` resolves the hostname once at validation time, but Playwright navigates independently. A DNS rebinding attack could serve a public IP at validation time and switch to a private IP when Playwright connects. Mitigation: Playwright's own route interception blocks private-range connections and redirects at the browser level, reducing practical exploitability but not eliminating the race without local proxy IP pinning.

</details>
