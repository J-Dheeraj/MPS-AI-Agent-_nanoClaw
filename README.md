# MPS-AI-Agent — nanoClaw (Production System)

> **Architecture reconciliation (2026-06-20).** The production policy mechanism is **deterministic, Ed25519-signed JSON policy rules** loaded by the server's `policy_store` from `POLICY_DIR` (manifest + per-rule JSON, validity/supersession/relevance ranking). The legacy "GEPA skill engine" framing and "Markdown SKILL files injected into the prompt" descriptions below are **superseded**: no Markdown skill is injected into letter generation, and proposal generation is deterministic (no LLM converts corrections into policy). "GEPA" persists only as a product name for the deterministic proposal -> human review -> signed promotion pipeline.

A self-hosted AI agent purpose-built for Singapore Members of Parliament conducting **Meet-the-People Sessions (MPS)** and constituency casework.

> **Production readiness — 2026-06-23.** Independent architecture/security reviews now score the system **9.2/10** ("pilot-ready, approaching production-ready"), up from an early-June baseline. Since 10 June the system added durable generation jobs with atomic ownership, an Ed25519-signed + durable audit-forwarding outbox, fail-closed and integrity-verified supply-chain scanning, a mandatory PostgreSQL-16 concurrency CI gate, a model-evaluation harness, a signed release-record with a release eval-gate, Prometheus alerts/SLOs, and operations runbooks. See **Current status & production readiness** below.

## Current status & production readiness (2026-06-23)

External architecture/security reviews score the system **9.2 / 10** — *pilot-ready, approaching production-ready*. The remaining gaps are operational evidence, not code (see the honest boundary at the end of this section).

**Durable, correct generation**
- Atomic job ownership: interactive jobs are created already `running` with a lease; both the WebSocket path and the background worker take ownership through one compare-and-swap (`claim_job`), so a job is never executed twice.
- Lease + periodic reaper recover crashed/disconnected jobs; an in-process background worker finishes pending jobs with no client attached.

**Audit integrity**
- Append-only SHA-256 hash chain **plus Ed25519-signed checkpoint heads** and a **durable forwarding outbox**: HTTPS-only in production, destination host allowlist (SSRF guard), `Idempotency-Key` per head, and owner-token compare-and-swap acknowledgement so a stale worker cannot clobber a reclaimed row. Health: `GET /health/audit-chain`.

**Supply-chain & CI (all gates fail closed)**
- Vulnerability scan with **grype pinned to v0.114.0**, fresh-DB enforced (no age bypass); **syft / grype / gitleaks installers checksum-verified**; `postgres:16` CI service pinned by digest; GitHub Actions pinned by commit SHA.
- **Mandatory PostgreSQL-16 concurrency job** runs real two-session contention against the Alembic migration chain and fails the build if it skips. Plus `pip-audit --strict`, SBOM (CycloneDX), and gitleaks secret scanning.

**Model assurance & release governance**
- Model-evaluation harness with thresholds: prompt-injection, PII leakage, groundedness, and **citation precision and recall = 1.0**.
- **Signed release record** (`deploy/release/generate_release_record.py`) binds commit + model + prompt hash + policy manifest + validator + dependency-audit + SBOM + eval result; on a `v*` tag the CI gate **fails the release if no model-evaluation result is attached**.

**Monitoring & operations**
- `deploy/monitoring/` — Prometheus `alerts.yml` (validated by `promtool` in CI) + `SLOs.md`.
- `deploy/runbooks/` — PostgreSQL restore/failover drill, signing-key lifecycle + break-glass, audit-sink operations.
- `deploy/audit-sink/reference_sink.py` + `tests/test_audit_sink_contract.py` — a runnable append-only reference sink and a contract test so the external audit sink is **testable, not assumed**.

**Verification:** **113 passed / 7 skipped** (Python suite), bash end-to-end **24/24**, PostgreSQL concurrency green in CI, Alembic schema head **`20260621_03`**. CI is green.

**Honest boundary:** reaching *production-ready* now requires executed evidence outside this repo — running the evaluation against the **production** Ollama model on a trusted runner, deploying and contract-testing a real **WORM audit sink**, executing **backup/restore + failover drills** with measured RPO/RTO, and HA/load testing. The code mechanisms to attach and enforce that evidence (release record + gate, contract test, alert rules, runbooks) are in place.



Volunteers and vetters use a **cross-platform Tauri v2 desktop app** to draft and approve formal appeal letters with AI assistance. All AI inference runs fully **on-premises via Ollama** — no Anthropic API key, no cloud calls, no constituent data ever leaves the LAN.

> **Companion repo:** [MPS-AI-Agent-Hermes](https://github.com/J-Dheeraj/MPS-AI-Agent-Hermes) proposes policy-skill improvements from anonymised, approved corrections. The pipeline is **deterministic and human-promoted**: it does not auto-apply changes or let a model mutate active policy. A human approves each proposal in the **Hermes Review App** (Tauri desktop), and promotion produces an **Ed25519-signed policy manifest** that NanoClaw verifies fail-closed before trusting any rule.

---

## Table of Contents

1. [How the system works](#how-the-system-works)
2. [MPS Night workflow — step by step](#mps-night-workflow--step-by-step)
3. [Architecture](#architecture)
4. [Component overview](#component-overview)
   - [mps\_server — FastAPI backend](#mps_server--fastapi-backend-python)
   - [nanoclaw-tauri-client — Desktop app](#nanoclaw-tauri-client--desktop-app-tauri-v2)
5. [Data model](#data-model)
6. [Roles](#roles)
7. [Security](#security)
8. [Installation and setup](#installation-and-setup)
   - [Server setup](#1-server-setup-central-machine)
   - [Tauri client setup](#2-tauri-client-setup-volunteer--vetter-laptops)
   - [Running in development](#3-running-in-development-mode)
   - [Building for production](#4-building-for-production)
9. [Running the full stack](#running-the-full-stack)
10. [Hermes GEPA integration](#hermes-gepa-integration)
11. [Security verification checklist](#security-verification-checklist)
12. [Project structure](#project-structure)
13. [Troubleshooting](#troubleshooting)

---

## How the system works

Every MPS night, the MP's team sets up a central server machine running `mps_server` (FastAPI) and Ollama. Volunteer laptops and vetter laptops connect to this server over the local LAN — no internet is required at any point.

**The flow in one paragraph:** A volunteer sits with a resident, enters their case details (masked NRIC, agency, issue type), and clicks **Generate Draft**. Ollama's `llama3.2:3b` model streams a formal appeal letter directly into the Tauri app. The volunteer edits it if needed and clicks **Submit for Vetting**. A vetter picks up the case from their queue, reads the draft, edits it directly inside the Tauri app, and clicks **Submit to MP**. This freezes the letter — it cannot be changed again. The next day, the MP reviews all frozen letters in the MPS platform and approves them for sending to the agencies.

**Nothing leaves the LAN.** The server never connects to the internet. Ollama runs entirely on-premises. NRIC numbers are masked at the point of entry and never stored in full.

---

## MPS Night workflow — step by step

```
BEFORE THE SESSION
------------------
1. Admin starts the server:
      bash start-server.sh
   (or: systemctl --user start mps-server)

2. Admin opens the session in the Tauri client or via curl:
      POST /sessions/open  { "date": "2026-06-08" }

3. Volunteer and vetter laptops launch the Tauri client:
      cd nanoclaw-tauri-client
      npm run tauri dev          (development)
      ./nanoclaw-client          (production binary)

DURING THE SESSION (per resident)
----------------------------------
4. Volunteer: Enter server address (e.g. 192.168.1.50:8000), log in.

5. Volunteer: Click "New Case".
   a. Search for resident by masked NRIC (S****567A format).
      - If found: select them.
      - If new: register them (NRIC masked immediately — full NRIC never stored).
   b. Choose agency (HDB / CPF / MSF / MOH / MOM / ICA).
   c. Choose case type (Grant / Appeal / Enquiry / Re-appeal).
   d. Set urgency (Normal / Urgent / Critical).
   e. Tick "Re-appeal?" if this is a follow-up to a previous rejected appeal.
   f. Enter case notes (the resident's situation in plain language).
   g. Click "Create Case".

6. Volunteer: In the Letter view, click "Generate Draft".
   - Ollama streams the letter token by token into the editable area.
   - Letters follow the 10-part structure (reference, salutation, background,
     current situation, grounds for appeal, supporting info, request,
     undertaking, closing, MP signature block).
   - Volunteer can edit the draft freely.
   - Click "Copy to Clipboard" to paste into the MPS platform as a working copy.
   - Click "Submit for Vetting" when ready.

7. Vetter: Vetter queue shows all cases with status "pending_vetter".
   - Click a case to open the Vetter view.
   - The letter appears in a fully editable contenteditable area.
   - Vetter edits the letter directly — corrects policy figures, tone, structure.
   - Click "Submit to MP":
       Server saves final_content, sets is_frozen=True, case -> pending_mp.
       Letter is now locked — no further edits possible.
   - OR: Click "Return to Volunteer" with a comment if more information is needed.
       Case goes back to "returned" status; volunteer is notified.

8. Volunteer revises if returned, resubmits, vetter reviews again.

AFTER THE SESSION
-----------------
9. Admin closes session:
      POST /sessions/close

10. Next day: MP reviews all pending_mp letters in the MPS platform, approves,
    platform auto-sends to agencies.

11. Any policy corrections noticed during the session are logged in the
    Feedback tab, vetters validate, Hermes GEPA picks them up Sunday 2am.
```

---

## Architecture

```
+------------------------------- LAN only (no internet) ----------------------------------------+
|                                                                                                 |
|  [Volunteer laptop 1]         [Vetter laptop]             [Central server]                     |
|  Tauri v2 desktop app         Tauri v2 desktop app        mps_server (FastAPI)                 |
|  nanoclaw-tauri-client -----> REST + WebSocket ---------> port 8000                            |
|                                                                   |                             |
|  [Volunteer laptop 2]                                             v                             |
|  Tauri v2 desktop app ---------------------------------------->  Ollama  :11434               |
|  nanoclaw-tauri-client                                     llama3.2:3b (letter drafting)       |
|                                                            nomic-embed-text (semantic search)   |
|                                                                   |                             |
|                                                                   v                             |
|                                                            SQLite  (mps.db)                     |
|                                                            Append-only SHA-256 audit log        |
|                                                                   |                             |
|                                                                   v (Sunday 2am, offline)       |
|                                                            Hermes GEPA                          |
|                                                            Reads /feedback/approved             |
|                                                            Improves SKILL files                 |
|                                                            Human review via hermes-review-app   |
+-------------------------------------------------------------------------------------------------+

MP reviews letters next day in MPS case management platform (separate system).
MPS platform auto-sends approved letters to agencies.
```

**Key design decisions:**

| Decision | Why |
|----------|-----|
| Tauri v2 (not browser) | Native desktop app — works on old laptops, no browser overhead |
| Ollama (not Anthropic API) | Fully air-gapped — zero cloud dependency, no API key risk |
| FastAPI + SQLite | Simple, lightweight, runs on a RM400 mini-PC |
| JWT in memory only | Token is held in JS memory for the session and never written to disk; it is cleared on logout/exit. (It is NOT persisted in an encrypted store — persistence was removed to avoid a plaintext token on disk.) |
| Tamper-evident audit log | Every action is SHA-256 hash-chained; the ORM blocks UPDATE/DELETE and a verification command detects tampering. (DB-role revocation of UPDATE/DELETE and external anchoring are recommended additions — see governance pack.) |
| NRIC masked at entry | Full NRIC never persisted anywhere in the system |
| Frozen letters | Vetter's final text is immutable — what MP sees is exactly what vetter approved |

---

## Component overview

### `mps_server/` — FastAPI backend (Python)

REST + WebSocket API. Runs on the central server. Binds to `127.0.0.1:8000` by default — not reachable from the internet.

#### Modules

| Module | Purpose |
|--------|---------|
| `main.py` | FastAPI app entry point. Auto-creates DB tables on startup. Seeds `admin/admin123` default account (change immediately). |
| `database.py` | SQLAlchemy models: `User`, `Session`, `Resident`, `Case`, `Letter`, `FeedbackEntry`, `AuditLog`. All relationships defined here. |
| `auth.py` | JWT tokens (60-min expiry), bcrypt password hashing, RBAC decorator (`require_role`), account lockout after 5 failed attempts. |
| `services/audit.py` | Tamper-evident audit log. Every action writes a new row with a SHA-256 hash of the previous row, serialised with an advisory lock. The ORM blocks UPDATE/DELETE on audit rows and `verify_audit` detects tampering; revoking UPDATE/DELETE at the database-role level is a recommended hardening step. |
| `services/ollama_client.py` | LLM queue (max 3 concurrent requests), async streaming via Ollama HTTP API. Three system prompts: LETTER (standard draft), REAPPEAL (follow-up to previous rejection), QA (quality check). |
| `routers/auth_router.py` | `POST /auth/login` (OAuth2 form), `/auth/logout`, `/auth/register` (admin only). |
| `routers/sessions_router.py` | `POST /sessions/open`, `POST /sessions/close`. One active session at a time. |
| `routers/residents_router.py` | `GET /residents/search?q=` (by masked NRIC), `POST /residents/` (validates NRIC is masked — rejects unmasked NRICs). |
| `routers/cases_router.py` | Case CRUD. `POST /cases/{id}/volunteer-submit`, `POST /cases/{id}/vetter-submit` (saves final text, freezes letter), `POST /cases/{id}/vetter-return` (return to volunteer). |
| `routers/letters_router.py` | `WS /letters/ws/draft` (streaming draft generation), `WS /letters/ws/qa` (streaming QA check), `PUT /letters/{id}` (save — returns 403 if frozen). |
| `routers/feedback_router.py` | `POST /feedback/` (log correction), `GET /feedback/pending` (vetter validation queue), `POST /feedback/{id}/approve`, `GET /feedback/approved` (Hermes GEPA reads this). |

#### WebSocket streaming protocol

The Tauri client connects to `/letters/ws/draft?token=<jwt>`. Messages flow as JSON:

```json
// Server -> Client:
{ "type": "token",  "content": "Dear " }
{ "type": "token",  "content": "Minister" }
{ "type": "done",   "letter_id": 42 }
{ "type": "error",  "message": "..." }

// Client -> Server:
{ "type": "cancel" }
```

The client's `websocket.js` handles reconnection, cancellation on navigation, and fires `onToken`/`onDone`/`onError` callbacks.

---

### `nanoclaw-tauri-client/` — Desktop app (Tauri v2)

A cross-platform native desktop application built with Tauri v2 (Rust backend) + Vite + vanilla JavaScript (no framework).

#### Why Tauri v2?

- **Cross-platform:** Works on Windows, macOS, Linux from a single codebase
- **Lightweight:** ~10 MB binary, ~50 MB RAM at runtime
- **Secure by default:** Rust backend, CSP enforced, JWT in encrypted Rust store (never JS)
- **Old hardware friendly:** No Electron overhead — uses the OS's native WebView (WebKit on Linux/macOS, WebView2 on Windows)

#### How Tauri v2 works in this app

```
+--------------------------------------------------------------------+
|                        Tauri Process                               |
|                                                                    |
|  +---------------------------------+  +------------------------+  |
|  |  WebView (WebKit / WebView2)    |  |  Rust backend          |  |
|  |                                 |  |                        |  |
|  |  src/main.js                    |  |  5 Rust commands:      |  |
|  |  src/views/login.js             |<->|  get_server_config     |  |
|  |  src/views/mainWindow.js        |IPC|  set_server_config     |  |
|  |  src/views/caseForm.js          |  |  save_session_token    |  |
|  |  src/views/letterView.js        |  |  load_session_token    |  |
|  |  src/views/vetterView.js        |  |  clear_session_token   |  |
|  |  src/views/feedbackView.js      |  |                        |  |
|  |  src/state/store.js             |  |  Plugins:              |  |
|  |  src/api/client.js              |  |  tauri-plugin-store    |  |
|  |  src/api/session.js             |  |  tauri-plugin-http     |  |
|  |  src/api/websocket.js           |  |  tauri-plugin-websocket|  |
|  |  src/api/config.js              |  |  tauri-plugin-window-  |  |
|  +---------------------------------+  |    state               |  |
|                                       |  tauri-plugin-clipboard|  |
|                                       +------------------------+  |
+--------------------------------------------------------------------+
         | HTTP / WebSocket
         v
   mps_server (FastAPI) on LAN
```

The JavaScript frontend makes REST calls through `tauri-plugin-http` (not `fetch`) and WebSocket connections through `tauri-plugin-websocket`. Both are scoped in `src-tauri/capabilities/default.json` — the app cannot call any URL outside the configured LAN.

#### Source files explained

**`src/api/client.js`** — REST API wrapper

All HTTP calls go through this file. Key functions:

```javascript
login(username, password)              // returns JWT token
logout()                               // invalidates token server-side
searchResidents(query)                 // search by masked NRIC
createResident(nricMasked, name, ...)  // register new resident
createCase(residentId, agency, ...)    // open a new case
getCases()                             // fetch case list for current session
volunteerSubmit(caseId)                // mark case ready for vetting
vetterSubmitToMp(caseId, finalText)    // save final letter text + freeze
vetterReturn(caseId, comment)          // return case to volunteer
saveLetter(letterId, content)          // save draft (403 if frozen)
logFeedback({ agency, incorrect_claim, correct_answer, case_id })
getApprovedFeedback()                  // Hermes-ready corrections (vetter only)
```

On any 401 response, `client.js` calls `clearSession()` automatically — user is returned to the login screen.

**`src/api/session.js`** — JWT session management

JWT is stored in **two places only:**
1. In-memory variable (`currentToken`) — cleared on window close
2. Tauri's encrypted store plugin — survives app restart on the same machine

It is **never stored in** `localStorage`, `sessionStorage`, `indexedDB`, or cookies.

```javascript
// Flow:
// 1. User logs in -> client.login() returns token
// 2. session.js saves it:
//    setCurrentToken(token)                    // in-memory
//    invoke('save_session_token', { token })   // Rust encrypted store
// 3. On app restart, session.js calls:
//    invoke('load_session_token')              // restore from Rust store
// 4. On logout / 401:
//    clearSession()  -> clears memory + invoke('clear_session_token')
```

`onSessionChange(fn)` is a pub/sub callback — `login.js` and `mainWindow.js` subscribe to know when auth state changes.

**`src/api/websocket.js`** — Streaming letter generation

Connects to the server's WebSocket endpoint for real-time letter streaming. Token is passed in the query string.

```javascript
// Usage in letterView.js:
const stream = await connectLetterStream({
  caseId: 42,
  token: getToken(),
  onToken: (text) => appendToEditor(text),
  onDone: (letterId) => { currentLetterId = letterId; },
  onError: (msg) => showError(msg),
});

// Cancel if user navigates away:
stream.cancel();
```

**`src/api/config.js`** — Server address persistence

Server IP:port entered on first launch is saved via the Rust store and pre-filled on subsequent launches.

**`src/state/store.js`** — App-wide state (pub/sub)

A minimal framework-free state container. No Redux, no Zustand — ~40 lines of JavaScript.

```javascript
// State shape:
{
  serverAddress: "192.168.1.50:8000",
  token: null,
  user: null,           // { id, username, role, full_name }
  cases: [],
  selectedCaseId: null,
  activeView: "login",  // "login"|"main"|"case-form"|"letter"|"vetter"|"feedback"
}

// Update state:
setState({ selectedCaseId: 7 });

// Subscribe to changes:
// IMPORTANT: subscribe() receives only ONE argument (current state).
// Track previous values yourself:
let prevCaseId = getState().selectedCaseId;
subscribe((state) => {
  if (state.selectedCaseId !== prevCaseId) {
    prevCaseId = state.selectedCaseId;
    openCaseDetail(state.selectedCaseId);
  }
});
```

**`src/views/login.js`** — Two-step login

Step 1: Enter server address (e.g. `192.168.1.50:8000`). Address is validated and saved to Rust store. Step 2: Enter username and password. On success, navigates to `mainWindow`.

**`src/views/mainWindow.js`** — Main split-pane layout

Left panel: case list filtered to current session. Each case shows resident name (masked), agency, status, and urgency indicator.

Right panel renders one of: `letterView` (volunteer), `vetterView` (vetter), or a placeholder — based on role and selected case.

The subscribe pattern tracks `selectedCaseId` changes using a local `prevSelectedCaseId` variable (because `subscribe()` only passes current state, not previous state).

**`src/views/caseForm.js`** — New Case modal

- **Resident search:** debounced search-as-you-type against `/residents/search`. Results show masked NRIC + name.
- **NRIC masking:** enforced client-side with regex `^([A-Z])\d{4}(\d{3}[A-Z])$` — displays as `S****567A`. Raw input is never sent to the server.
- **Register new resident:** inline form if not found. Masked NRIC is sent to `/residents/` — server rejects unmasked NRICs.
- **Agency selector:** HDB / CPF / MSF / MOH / MOM / ICA
- **Case type:** Grant / Appeal / Enquiry / Re-appeal
- **Urgency:** Normal / Urgent / Critical
- **Re-appeal toggle:** flags follow-ups to previous rejections (switches LLM system prompt to REAPPEAL mode)
- **Case notes:** free text — the resident's situation in the volunteer's own words

**`src/views/letterView.js`** — Core volunteer tool

1. Case notes shown at top for reference.
2. **Generate Draft** connects WebSocket, streams letter token-by-token into a `contenteditable` div.
3. Stream can be cancelled mid-way by navigating away — `websocket.js` sends `{ "type": "cancel" }`.
4. Volunteer edits freely.
5. **Copy to Clipboard** — uses `@tauri-apps/plugin-clipboard-manager`.
6. **Save** — `PUT /letters/{id}` saves current draft.
7. **Submit for Vetting** — `POST /cases/{id}/volunteer-submit` puts case in vetter queue.

**`src/views/vetterView.js`** — Vetter tool

1. Volunteer's draft in a `contenteditable` div — fully editable.
2. Original case notes in a collapsed sidebar.
3. **Submit to MP** — double confirmation:
   - First click: "Are you sure? This will freeze the letter."
   - Second click: "Confirm — submit vetter's final text to the MP."
   - On confirm: `vetterSubmitToMp(caseId, finalText)` — server saves `final_content`, sets `is_frozen=True`, case → `pending_mp`.
4. **Return to Volunteer** — opens a comment text area, calls `vetterReturn(caseId, comment)`.
5. After submission, view becomes read-only with a "Frozen — submitted to MP" banner.

**`src/views/feedbackView.js`** — Feedback and corrections

Allows volunteers and vetters to log policy corrections noticed during the session. Fields: Agency, Incorrect claim, Correct answer. These are **anonymised** — no resident data is required.

Fields sent to server:
```javascript
{ agency, incorrect_claim, correct_answer, case_id }
```

Vetters also see a **validation queue** — pending corrections from volunteers. Vetters approve or reject each. Only approved corrections reach Hermes GEPA.

#### `src-tauri/src/main.rs` — Rust backend

The Rust side handles:

1. **Plugin registration:** store, http, websocket, window-state, clipboard
2. **5 custom Tauri commands:**

```rust
// Persist server address
#[tauri::command]
async fn get_server_config(store: State<'_, Store<Wry>>) -> Result<String, String>

#[tauri::command]
async fn set_server_config(store: State<'_, Store<Wry>>, address: String) -> Result<(), String>

// JWT in Rust encrypted store (never in JS)
#[tauri::command]
async fn save_session_token(store: State<'_, Store<Wry>>, token: String) -> Result<(), String>

#[tauri::command]
async fn load_session_token(store: State<'_, Store<Wry>>) -> Result<Option<String>, String>

#[tauri::command]
async fn clear_session_token(store: State<'_, Store<Wry>>) -> Result<(), String>
```

3. **CSP in `tauri.conf.json`:**

```
connect-src 'self'
  http://127.0.0.1:8000  ws://127.0.0.1:8000
  http://192.168.0.0/16  ws://192.168.0.0/16
  ipc: http://ipc.localhost
```

Any call to an external URL is blocked by the CSP — the app physically cannot exfiltrate data even if the JS were compromised.

4. **`src-tauri/capabilities/default.json`** — Tauri v2 permission model:

```json
{
  "identifier": "default",
  "description": "Default capabilities for nanoClaw client",
  "windows": ["main"],
  "permissions": [
    "core:default",
    "store:default", "store:allow-get", "store:allow-set", "store:allow-save",
    "store:allow-load", "store:allow-delete", "store:allow-clear",
    "window-state:default", "window-state:allow-restore-state", "window-state:allow-save-window-state",
    "clipboard-manager:allow-read-text", "clipboard-manager:allow-write-text",
    "http:default", "http:allow-fetch", "http:allow-fetch-send",
    "http:allow-fetch-read-body", "http:allow-fetch-cancel",
    "websocket:default", "websocket:allow-connect", "websocket:allow-send"
  ]
}
```

Only listed permissions are available to JS. Any permission not listed is denied at the Rust layer.

---

## Data model

### Tables

```
User
  id, username, hashed_password, role (volunteer/vetter/admin), full_name
  failed_attempts, locked_until

Session  (one per MPS night)
  id, date, status (open/closed), opened_by, opened_at, closed_at

Resident  (permanent across sessions)
  id, nric_masked (S****567A — never full NRIC), name, address, phone
  created_at

Case  (one per resident visit)
  id, session_id, resident_id, assigned_to (volunteer user_id)
  agency (HDB/CPF/MSF/MOH/MOM/ICA)
  case_type (grant/appeal/enquiry/reappeal)
  urgency (normal/urgent/critical)
  is_reappeal (bool)
  notes (volunteer's text — never contains full NRIC)
  status: new -> assigned -> drafted -> pending_vetter -> pending_mp -> approved -> sent
          ^_________ returned __________^  (volunteer revises)

Letter  (one active per case)
  id, case_id, content (current draft), final_content (vetter's frozen version)
  is_frozen (bool — set True when vetter submits to MP)
  version, created_at, updated_at

FeedbackEntry  (policy corrections — anonymised)
  id, case_id (optional), agency, incorrect_claim, correct_answer
  submitted_by, status (pending/approved/rejected)
  approved_by, approved_at

AuditLog  (append-only — never updated or deleted)
  id, user_id, action, entity_type, entity_id
  details (JSON), timestamp, prev_hash, hash (SHA-256 chain)
```

### Case status flow

```
new
 |
 v  (admin assigns / volunteer picks up)
assigned
 |
 v  (volunteer generates + edits draft)
drafted
 |
 v  (volunteer clicks "Submit for Vetting")
pending_vetter <------------------------------+
 |                                            |
 v  (vetter submits to MP)    (vetter returns)|
pending_mp                               returned
 |                                            |
 v  (MP approves in MPS platform)        volunteer revises -> re-submits
approved
 |
 v  (MPS platform sends to agency)
sent
```

---

## Roles

| Role | What they can do |
|------|-----------------|
| `volunteer` | Log in, search/register residents, create cases, generate letter drafts, edit drafts, copy to clipboard, submit for vetting, log feedback |
| `vetter` | Everything a volunteer can do, plus: view all pending-vetter cases, edit letter drafts, submit to MP (freezes letter), return to volunteer, validate feedback corrections |
| `admin` | Everything a vetter can do, plus: open/close sessions, register new users, view all cases across all volunteers, view audit log |
| *(MP)* | Does not use nanoClaw. Reviews frozen letters in the MPS platform the next day. |

---

## Security

All security controls are non-negotiable. No constituent data leaves the LAN.

| Control | Implementation |
|---------|---------------|
| **No cloud AI** | Ollama runs on-premises. `llama3.2:3b` / `llama3.1:8b`. No API key anywhere in the codebase. |
| **NRIC masking** | Full NRIC never stored. `S****567A` format enforced at the Tauri client (regex) AND at the API layer (`POST /residents/` rejects unmasked NRICs). |
| **JWT in Rust store** | Token stored in Tauri's encrypted Rust store — never in `localStorage`, `sessionStorage`, or cookies. Cleared on logout and on 401. |
| **LAN-only CSP** | Tauri `connect-src` restricts all network calls to `127.0.0.1:8000` and `192.168.*.*:8000`. External calls blocked at the WebView level. |
| **Tauri capabilities** | `src-tauri/capabilities/default.json` explicitly lists every permission. No permission = no access. |
| **JWT auth** | 60-minute tokens, bcrypt passwords, account lockout after 5 failed attempts. |
| **RBAC** | `require_role` decorator on every endpoint. Volunteers cannot access vetter or admin endpoints. |
| **Append-only audit log** | SHA-256 hash chain. Every action appends a new row. Tampering is detectable by hash verification. No UPDATE or DELETE. |
| **LAN-only server binding** | `mps_server` binds to `127.0.0.1:8000` by default — not reachable from the internet. |
| **Frozen letters** | Once a vetter submits to MP, `is_frozen=True`. Any further `PUT /letters/{id}` returns `403 Forbidden`. |
| **Feedback isolation** | Only vetter-validated, anonymised corrections (no NRIC, no names, no case content) reach Hermes GEPA. |
| **No full-NRIC storage** | API rejects any NRIC not matching the masked pattern at `POST /residents/`. |
| **Double-confirm on freeze** | Vetter's "Submit to MP" requires two separate confirmation clicks. |
| **Signed audit checkpoints + durable outbox** | Each audit head is Ed25519-signed; forwarding to the external append-only sink is durable (outbox), HTTPS-only in production, host-allowlisted, idempotent, and owner-token CAS-acknowledged. |
| **Fail-closed dependency scanning** | grype (pinned, fresh-DB-enforced) + pip-audit `--strict` + SBOM + gitleaks; installers checksum-verified, images digest-pinned, actions SHA-pinned. A stale or vulnerable result fails CI. |
| **Signed release record + eval gate** | A signed record binds commit + model + prompt + policy + validator + scans + eval result; a `v*` release tag fails CI without a model-evaluation result. |
| **PostgreSQL concurrency gate** | A mandatory CI job exercises real concurrent job claiming and audit delivery on PostgreSQL 16 and fails the build if it skips. |

> **On prompt injection:** Acknowledged open problem. RBAC and LAN isolation significantly limit the blast radius. Do not connect this system to external services without rate-limiting and human review.

---

## Installation and setup

### Prerequisites

- **Server:** Linux machine (Ubuntu 22.04 recommended), 4GB+ RAM, 20GB+ disk
- **Client laptops:** Windows 10+, macOS 11+, or Ubuntu 22.04+
- **Build environment (for Tauri):** Linux with WSL2 (if Windows) or native Linux/macOS

### 1. Server setup (central machine)

```bash
# Install Python dependencies
sudo apt-get update
sudo apt-get install -y python3 python3-pip git curl

# Clone the repo
cd ~
git clone https://github.com/J-Dheeraj/MPS-AI-Agent-_nanoClaw.git nanoclaw
cd nanoclaw

# Install Python server dependencies
pip3 install -r mps_server/requirements.txt --user

# Run hardening script — generates SECRET_KEY, sets file permissions
bash harden.sh
# Creates mps_server/.env with a random SECRET_KEY

# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull the language models
ollama pull llama3.2:3b          # 2GB — works on any modern hardware (4GB RAM min)
# ollama pull llama3.1:8b        # 4.7GB — better quality (8GB RAM recommended)
ollama pull nomic-embed-text     # 274MB — for semantic search

# Verify Ollama is running
ollama list
# Should show: llama3.2:3b, nomic-embed-text

# Start the server
bash start-server.sh
# Server starts at http://127.0.0.1:8000

# For systemd (recommended for production):
systemctl --user start mps-server
systemctl --user enable mps-server

# Verify server is up
curl http://127.0.0.1:8000/health
# Expected: { "status": "ok", "ollama": "connected" }
```

#### Create user accounts

The server seeds `admin / admin123` on first start. **Change this immediately.**

```bash
# Get an admin token
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/auth/login \
  -d 'username=admin&password=admin123' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Change admin password
curl -X POST http://127.0.0.1:8000/auth/change-password \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"old_password": "admin123", "new_password": "YOUR_STRONG_PASSWORD"}'

# Create a volunteer account
curl -X POST http://127.0.0.1:8000/auth/register \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"username":"ali","password":"STRONG_PW","role":"volunteer","full_name":"Ali Bin Ahmad"}'

# Create a vetter account
curl -X POST http://127.0.0.1:8000/auth/register \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"username":"siti","password":"STRONG_PW","role":"vetter","full_name":"Siti Binte Rahmat"}'

# Open tonight's session
curl -X POST http://127.0.0.1:8000/sessions/open \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"date":"2026-06-08"}'
```

#### Make server reachable from LAN laptops

By default the server binds to `127.0.0.1`. To allow other laptops to connect:

```bash
# Edit mps_server/.env and set:
HOST=0.0.0.0
PORT=8000

# Restart the server.
# Volunteers and vetters can now connect to http://192.168.1.50:8000
```

---

### 2. Tauri client setup (volunteer / vetter laptops)

#### Option A: Use a pre-built binary (recommended for deployment)

Distribute the `.deb` (Linux), `.msi` (Windows), or `.dmg` (macOS) from the GitHub Releases page.

```bash
# Linux:
sudo dpkg -i nanoclaw-client_0.1.0_amd64.deb
nanoclaw-client
```

#### Option B: Build from source

```bash
# Install Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source ~/.cargo/env

# Install Node.js 22 via nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
source ~/.nvm/nvm.sh
nvm install 22
nvm use 22

# Install Tauri system dependencies (Ubuntu 22.04)
sudo apt-get update
sudo apt-get install -y \
  libwebkit2gtk-4.1-dev libssl-dev libayatana-appindicator3-dev \
  librsvg2-dev libgtk-3-dev build-essential \
  gstreamer1.0-plugins-good libgstreamer-plugins-good1.0-0

# Install npm dependencies
cd nanoclaw/nanoclaw-tauri-client
npm install

# Build production binary
npm run tauri build
# Output: src-tauri/target/release/bundle/
```

---

### 3. Running in development mode

```bash
cd nanoclaw/nanoclaw-tauri-client

# Ensure Cargo is in PATH
source ~/.cargo/env

# Kill any leftover dev server on port 1420
fuser -k 1420/tcp 2>/dev/null

# Start Tauri dev mode (hot-reload)
npm run tauri dev
```

What happens:
1. Vite starts on `http://localhost:1420` with hot-reload
2. Cargo compiles the Rust backend (~90 seconds on first build, ~5 seconds after)
3. The Tauri window opens
4. Frontend changes auto-reload; Rust changes trigger recompile

---

### 4. Building for production

```bash
npm run tauri build

# Outputs (Linux):
#   src-tauri/target/release/nanoclaw-client           (standalone binary)
#   src-tauri/target/release/bundle/deb/               (Debian package)
#   src-tauri/target/release/bundle/appimage/          (AppImage)
```

---

## Running the full stack

```bash
# 1. On the SERVER machine:
cd ~/nanoclaw
bash start-server.sh

# 2. Open a session (once per MPS night):
curl -X POST http://127.0.0.1:8000/sessions/open \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"date":"2026-06-08"}'

# 3. On each VOLUNTEER / VETTER laptop:
./nanoclaw-client              # production binary
# OR
npm run tauri dev              # development mode

# In the app:
#   Step 1: Enter server address -> 192.168.1.50:8000
#   Step 2: Enter username and password
#   -> App opens to the main case list

# 4. At end of session:
curl -X POST http://127.0.0.1:8000/sessions/close \
  -H "Authorization: Bearer <admin_token>"
```

---

## Hermes GEPA integration

After each session, corrections are logged in the **Feedback** tab. Vetters validate them. Every Sunday at 2am, Hermes GEPA reads approved corrections from `GET /feedback/approved` and improves the SKILL files. The **hermes-review-app** (in the companion Hermes repo) is used for the human review step.

```
Volunteer logs correction -> Vetter validates in Tauri Feedback tab
  -> GET /feedback/approved  (Hermes reads Sunday 2am)
  -> Hermes generates updated SKILL files in skills/auto/
  -> Human opens hermes-review-app, sees diffs, approves/rejects
  -> Approved files committed to Hermes repo
  -> nanoClaw loads updated SKILL files at next session
```

Full setup: [MPS-AI-Agent-Hermes](https://github.com/J-Dheeraj/MPS-AI-Agent-Hermes)

---

## Security verification checklist

Run before every MPS night:

```bash
# 1. No cloud API keys anywhere
grep -r "sk-ant\|OPENAI\|api_key" ~/nanoclaw/ 2>/dev/null
# Expected: no output

# 2. Ollama is serving locally
curl http://localhost:11434/api/tags
# Expected: JSON list including llama3.2:3b

# 3. Server is LAN-only
ss -tlnp | grep 8000
# Expected: shows the binding address (127.0.0.1 or LAN IP, NOT 0.0.0.0 on internet-facing machines)

# 4. DB file permissions
ls -la mps_server/mps.db
# Expected: -rw------- (owner only)

# 5. SECRET_KEY is not a placeholder
grep "CHANGE_THIS\|secret\|placeholder" mps_server/.env
# Expected: a random key, not a placeholder

# 6. No full NRIC in the database
sqlite3 mps_server/mps.db "SELECT nric_masked FROM residents;"
# Expected: all rows in S****567A format

# 7. Frozen letters return 403
curl -X PUT http://127.0.0.1:8000/letters/{frozen_id} \
  -H "Authorization: Bearer <volunteer_token>" \
  -H "Content-Type: application/json" \
  -d '{"content": "test"}'
# Expected: 403 Forbidden

# 8. Audit log is growing
sqlite3 mps_server/mps.db "SELECT COUNT(*) FROM audit_log;"
# Expected: number increases with each action

# 9. JWT is not in browser storage (in Tauri DevTools console)
#    window.localStorage.getItem('token')  -> null
#    window.sessionStorage.getItem('token') -> null
# Expected: null (token is in Rust encrypted store)
```

---

## Project structure

```
nanoclaw/
|
+-- mps_server/                        <- FastAPI backend
|   +-- main.py                        # App entry, table creation, admin seed
|   +-- database.py                    # SQLAlchemy models
|   +-- auth.py                        # JWT, bcrypt, RBAC, lockout
|   +-- .env                           # Secrets (not committed)
|   +-- requirements.txt
|   +-- services/
|   |   +-- audit.py                   # SHA-256 hash-chained audit log
|   |   +-- ollama_client.py           # Async LLM queue, streaming, 3 system prompts
|   +-- routers/
|       +-- auth_router.py
|       +-- sessions_router.py
|       +-- residents_router.py
|       +-- cases_router.py
|       +-- letters_router.py
|       +-- feedback_router.py
|
+-- nanoclaw-tauri-client/             <- Tauri v2 desktop app
|   +-- index.html
|   +-- package.json
|   +-- vite.config.js
|   +-- src/
|   |   +-- main.js                    # App entry
|   |   +-- style.css
|   |   +-- api/
|   |   |   +-- client.js              # All REST API calls
|   |   |   +-- session.js             # JWT management (Rust store)
|   |   |   +-- websocket.js           # WebSocket streaming
|   |   |   +-- config.js              # Server address persistence
|   |   +-- state/
|   |   |   +-- store.js               # Pub/sub state
|   |   +-- views/
|   |       +-- login.js
|   |       +-- mainWindow.js
|   |       +-- caseForm.js
|   |       +-- letterView.js
|   |       +-- vetterView.js
|   |       +-- feedbackView.js
|   +-- src-tauri/
|       +-- tauri.conf.json            # Window config, CSP, bundle settings
|       +-- Cargo.toml
|       +-- build.rs
|       +-- capabilities/
|       |   +-- default.json           # Tauri v2 permission model
|       +-- icons/                     # App icons
|       +-- src/
|           +-- main.rs                # Rust: 5 commands + plugin registration
|
+-- groups/
|   +-- main/                          # MP private group (WhatsApp/Telegram)
|   +-- mps-volunteers/                # Hermes GEPA config + SKILL files
|   +-- mps-vetters/
|
+-- start-server.sh
+-- mps-start.sh
+-- mps-stop.sh
+-- harden.sh
+-- MPS_DEPLOY.md
```

---

## Troubleshooting

**`cargo: command not found` when running `npm run tauri dev`**
```bash
source ~/.cargo/env
echo 'source ~/.cargo/env' >> ~/.bashrc
```

**`Port 1420 is already in use`**
```bash
fuser -k 1420/tcp
npm run tauri dev
```

**`libwebkit2gtk-4.1-dev: not found` during build**
```bash
sudo apt-get update
sudo apt-get install -y gstreamer1.0-plugins-good libgstreamer-plugins-good1.0-0
sudo dpkg --configure -a
sudo apt-get install -y libwebkit2gtk-4.1-dev
```

**Tauri window opens but shows blank screen**

Check the browser console (right-click inside the Tauri window, select "Inspect"). Common causes:
- Vite dev server not started
- CSP blocking a resource — check for Content Security Policy errors

**`403 Forbidden` on letter save**

The letter is frozen — a vetter already submitted it to the MP. Expected behaviour.

**Server reachable from localhost but not from other laptops**

Edit `mps_server/.env`, set `HOST=0.0.0.0`, restart server. If there is a firewall: `sudo ufw allow 8000`.

**Ollama is slow / timing out**

`llama3.2:3b` requires ~4GB RAM. If the server is low on memory, switch to a smaller model:
```bash
ollama pull phi3:mini
# Edit mps_server/services/ollama_client.py to use phi3:mini
```

---

## Important notes

1. **No cloud AI.** Ollama runs entirely on-premises. `llama3.2:3b` works on machines with 4GB RAM. Use `llama3.1:8b` for better quality if 8GB+ RAM is available.
2. **Sessions run until all cases are done.** Common to run past midnight.
3. **MP does not use this system.** The MP reviews frozen letters in the MPS platform the next day.
4. **Vetter owns the final text.** The volunteer's draft may be heavily modified. What the MP sees is exactly what the vetter submitted.
5. **Policy accuracy is your responsibility.** Singapore policies change at Budget (February) and COS (March). Always verify thresholds with the official agency before sending a letter under the MP's name.
6. **Back up the database.** Before each MPS night: `cp mps_server/mps.db mps_server/mps.db.backup-$(date +%Y%m%d)`

---

## References

- [MPS-AI-Agent-Hermes](https://github.com/J-Dheeraj/MPS-AI-Agent-Hermes) — companion GEPA skill engine + Hermes Review App
- [MPS_DEPLOY.md](./MPS_DEPLOY.md) — full deployment guide
- [Tauri v2 docs](https://v2.tauri.app)
- [Ollama](https://ollama.com)
- [HDB](https://www.hdb.gov.sg) | [CPF](https://www.cpf.gov.sg) | [MOM](https://www.mom.gov.sg) | [MOH](https://www.moh.gov.sg) | [MSF](https://www.msf.gov.sg) | [ICA](https://www.ica.gov.sg)
- [SupportGoWhere](https://supportgowhere.life.gov.sg)

---

## License

MIT
