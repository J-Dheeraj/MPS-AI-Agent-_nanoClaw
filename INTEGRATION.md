# INTEGRATION.md — nanoClaw + Hermes Combined System

> **Correction (2026-06-11):** Hermes does **not** auto-apply skill changes. The pipeline is deterministic and human-promoted: it generates *proposals* from anonymised approved corrections, a human approves each one in the Hermes Review App, and promotion produces an **Ed25519-signed policy manifest** that NanoClaw verifies fail-closed. References below to auto-running or auto-generating `skills/auto/` describe an earlier design and are retained only for context.


This document describes how the two repos work together for Singapore MPS (Meet-the-People Session) AI assistance.

---

## System overview

```
┌─────────────────────────────────── LAN only ──────────────────────────────────────┐
│                                                                                     │
│  Volunteer laptop(s)        Vetter laptop(s)         Central server                │
│  ┌──────────────┐           ┌──────────────┐         ┌─────────────────────────┐   │
│  │  GTK4 client │           │  GTK4 client │         │  FastAPI  (mps_server)  │   │
│  │  mps_client/ │──────────►│  vetter view │────────►│  port 8000              │   │
│  └──────────────┘           └──────────────┘         │         │               │   │
│   start-client.sh            start-client.sh         │      Ollama             │   │
│                                                       │   llama3.2:3b           │   │
│                                                       │   nomic-embed-text      │   │
│                                                       │         │               │   │
│                                                       │      SQLite             │   │
│                                                       │      mps.db             │   │
│                                                       └─────────────────────────┘   │
│                                                                                     │
│  Every Sunday 2am (automatic, same server):                                        │
│  Hermes GEPA reads GET /feedback/approved → improves SKILL-*.md files              │
└─────────────────────────────────────────────────────────────────────────────────────┘

MP reviews letters next day in MPS platform → approves → platform auto-sends.
```

---

## MPS Night data flow

```
Resident arrives
      │
      ▼
Volunteer opens GTK4 client
      │  Login (JWT)
      ▼
Create case  ──► POST /cases/
  Resident search/register  ──► GET /residents/search?q=
  NRIC masked: S****567A  ──► POST /residents/
      │
      ▼
Enter case notes in GTK4 client
      │
      ▼
Click "Generate Draft"
  WebSocket /letters/ws/draft
      │  Streams from Ollama llama3.2:3b
      ▼
Draft appears token by token in GTK4
      │
      ▼
Volunteer edits draft → "Copy to Clipboard"
      │
      ▼  (manual paste — no API integration)
Volunteer pastes into MPS platform
      │
      ▼
Volunteer clicks "Submit for vetting"  ──► POST /cases/{id}/submit
      │
      ▼
Vetter sees case in queue  ──► GET /cases/queue
      │
      ├── Approve  ──► POST /cases/{id}/vetter-pass
      │
      └── Return   ──► POST /cases/{id}/vetter-return  {"comment": "..."}
                          │
                          ▼
                   Volunteer revises → resubmits
      │
      ▼  (next day)
MP reviews in MPS platform → approves → MPS platform auto-sends
```

---

## Security boundary between nanoClaw and Hermes

```
nanoClaw (mps_server)                    Hermes GEPA
─────────────────────                    ───────────
All constituent data                     No constituent data
Full audit log                           Only approved corrections
NRIC masked in DB                        No NRIC ever
Case details                             Policy patterns only
Letter drafts                            No letter content
                  ╔══════════════════╗
                  ║ GET              ║
                  ║ /feedback/       ║ ── JSON: [{incorrect_claim,
                  ║   approved       ║           correct_answer,
                  ║                  ║           agency_code}]
                  ╚══════════════════╝
                  (LAN call — no internet)
                  (vetter must approve before entry appears here)
```

**What flows from nanoClaw to Hermes:**
- Vetter-approved corrections only
- Fields: `incorrect_claim`, `correct_answer`, `agency_code`
- No case ID, no resident name, no NRIC, no session date

**What never crosses:**
- Any resident data
- Any case data
- Any letter content
- Any NRIC (even masked)

---

## Feedback lifecycle

```
1. Volunteer / vetter notices incorrect agent claim
      │
      ▼
2. Log feedback in GTK4 client (Feedback tab)
   Fields: incorrect_claim, correct_answer, agency_code
   Status: pending
      │
      ▼
3. Vetter reviews feedback queue
   ├── Approve  → status: approved  ✓ flows to Hermes
   └── Reject (with reason) → status: rejected  ✗ archived only
      │
      ▼
4. Sunday 2am: Hermes GEPA reads /feedback/approved
      │
      ▼
5. GEPA generates updated SKILL files in skills/auto/
      │
      ▼
6. Human reviews — verify no fabricated policy numbers
      │
      ▼
7. Approved skills committed to Hermes repo
      │
      ▼
8. nanoClaw loads at next session
```

---

## Session lifecycle

```
Admin: POST /sessions/open
  │
  ▼
Session status: open
  │  Volunteers create cases, generate drafts, submit
  │  Vetters review queue, approve / return
  ▼
All cases vetted?
  │
  ▼
Admin: POST /sessions/{id}/close
  │
  ▼
Session status: pending_mp
  │  (next day)
  ▼
MP reviews in MPS platform → approves letters
  │
  ▼
Session status: approved → sent
```

Sessions have no fixed end time. Common to run past midnight.

---

## Case status flow

```
new ──► assigned ──► drafted ──► vetted ──► approved ──► sent
                        │
                        └──► returned ──► assigned (volunteer revises)
```

---

## Roles

| Role | Can do |
|------|--------|
| `volunteer` | Create cases, generate drafts, edit, copy, submit, log feedback |
| `vetter` | Review queue, approve, return with comment, validate feedback |
| `admin` | All above + open/close sessions, register users |
| *(MP)* | MPS platform only — not in nanoClaw |

---

## Weekly Hermes GEPA schedule

| Day | Action |
|-----|--------|
| MPS night | Volunteers/vetters log feedback corrections in GTK4 client |
| Any day | Vetters validate feedback (approve / reject) |
| Sunday 2am | Hermes GEPA auto-runs, reads /feedback/approved, generates skills/auto/ |
| Sunday morning | Human reviews skills/auto/, commits approved changes to Hermes repo |
| Next MPS night | nanoClaw loads improved SKILL files |

---

## File locations

### nanoClaw repo
```
mps_server/                 FastAPI backend
mps_client/                 GTK4 desktop app
groups/mps-volunteers/      Hermes config + skill stubs
  hermes-config.yaml        GEPA schedule + Ollama config
  skills/                   SKILL file stubs
start-server.sh             Launch server
start-client.sh             Launch GTK4 client
harden.sh                   Generate secrets, set permissions
MPS_DEPLOY.md               Full deployment guide
```

### Hermes repo
```
profiles/mps-volunteers/    GEPA profile
  hermes-config.yaml        Same config (canonical copy)
  skills/                   Evolving SKILL files
SKILL-*.md                  Full policy reference files (v1)
skills/auto/                GEPA-generated improvements (review before apply)
```
