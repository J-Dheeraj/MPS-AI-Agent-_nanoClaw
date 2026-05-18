# MPS-AI-Agent — nanoClaw (Production System)

A self-hosted personal AI agent purpose-built for Singapore Members of Parliament conducting **Meet-the-People Sessions (MPS)** and constituency casework.

The agent acts as a trusted aide — briefing the MP before each constituent meeting, triaging cases to the correct government agency in real time, drafting formal appeal letters, and maintaining a private knowledge graph of policy, cases, and constituent history. All data stays on-device. No constituent information is ever sent to a cloud service.

Built on the **NanoClaw v2** platform with Claude (Anthropic Agent SDK).

> **Combined system:** This repo is the production half of a two-system architecture. The companion repo [MPS-AI-Agent-Hermes](https://github.com/J-Dheeraj/MPS-AI-Agent-Hermes) runs offline as a weekly skill improvement engine (GEPA). See [INTEGRATION.md](./INTEGRATION.md) for the full workflow.

---

## Two-system architecture

```
nanoClaw (this repo) ──────────────────────────────────────────
  Live constituent interactions (WhatsApp, Telegram, Web UI)
  Security: OneCLI vault, Docker isolation, local AI, drop mode
  Knowledge: mnemon graph, 60+ URL ingestion, auto policy watch
  CRM: case logging, letter storage, overdue tracking
                │
                │  Weekly — anonymised correction patterns only
                │  No NRIC. No names. No case IDs.
                ▼
Hermes (companion repo) ───────────────────────────────────────
  Offline skill improvement engine — no live connections
  GEPA processes correction patterns from feedback-log.md
  Generates updated skill files reviewed before applying
                │
                │  Approved improvements → CLAUDE.md update
                ▼
nanoClaw restarts with improved knowledge
```

**Security boundary:** constituent data never crosses to Hermes. See [INTEGRATION.md](./INTEGRATION.md) for the full security rules and weekly workflow.

---

## What the agent does

| Task | Description |
|---|---|
| **Pre-meeting briefing** | Surfaces everything known about a constituent and their case history before the MP walks in |
| **Live case triage** | Given a one-line problem description, identifies the agency, the exact scheme, and eligibility criteria — instantly |
| **Appeal letter drafting** | Produces a formatted MP appeal letter ready for signature; correct tone, correct agency, correct policy citation |
| **Policy lookup** | Answers questions about HDB, CPF, MOM, MOH, MSF, ICA, IRAS, LTA, MOE, PA — with 2025/2026 Budget updates |
| **Historical context** | Explains why policies exist — drawing on 70 years of Singapore policy history from 1955 to 2026 |
| **Pending case digest** | Weekly summary of cases awaiting agency replies |
| **Scheduled briefings** | Morning or pre-MPS summaries of pending matters and recent policy changes |
| **Auto policy updates** | Monitors 8 agency newsrooms daily and ingests new announcements automatically |
| **Self-improvement** | Correction patterns logged via `/feedback` are processed weekly by Hermes GEPA and applied back |

---

## Agency coverage

Built-in knowledge of every agency encountered at MPS:

| Agency | Coverage |
|---|---|
| **HDB** | BTO grants (EHG, PHG, Step-Up), resale eligibility, rental flat appeals, HFE letter, Fresh Start 2026 |
| **CPF** | OA/SA/MA/RA, MediSave, CPF LIFE, MRSS, 2026 OW ceiling ($8,000), quarterly rate updates |
| **MOM** | EP/S Pass/WP/LTVP/LOC, salary disputes, TADM, retrenchment, Workfare |
| **MOH** | MediShield Life, CHAS (Blue/Orange), MediFund, CareShield Life, Pioneer/Merdeka Generation |
| **MSF** | ComCare (Crisis/SMTA/PA), Silver Support, SSO referrals, ComLink+ |
| **ICA** | PR appeals, citizenship, LTVP/LTVP+ extensions |
| **IRAS** | GST Voucher cash/U-Save/S&CC, income tax disputes |
| **LTA** | Senior concessions, WAV subsidy, disabled parking |
| **MOE** | FAS, Edusave, school transfers, DSA, SPED |
| **PA / CDCs** | CDC Vouchers 2026, grassroots referrals |

---

## Architecture

```
MP's devices          Volunteers' devices      Vetters' devices
(WhatsApp/Telegram/   (WhatsApp group)         (WhatsApp group)
 Web UI)
        │                    │                        │
        └────────────────────┼────────────────────────┘
                             ▼
          MPS-AI-Agent host process  (Node.js · src/index.ts)
            ├─ Router          → validates sender allowlist → writes to inbound.db
            ├─ Container runner → one isolated Docker container per group
            ├─ Delivery        → polls outbound.db → sends replies
            ├─ Scheduler       → briefings, digests, policy auto-updates
            └─ OneCLI proxy    → intercepts all container HTTPS → injects credentials
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
  Docker: main         Docker: mps-volunteers  Docker: mps-vetters
  (MP — owner)         (intake — member)       (vetters — member)
  ├─ Claude SDK        ├─ Claude SDK           ├─ Claude SDK
  ├─ mnemon            ├─ mnemon               ├─ mnemon
  ├─ whisper.cpp       ├─ whisper.cpp          ├─ whisper.cpp
  ├─ Ollama client     ├─ Ollama client        ├─ Ollama client
  ├─ MCP: crm-bridge   ├─ MCP: crm-bridge      │  (no CRM access)
  └─ groups/main/      └─ groups/main/         └─ groups/mps-vetters/
     (4 policy files)     (4 policy files)        (CLAUDE.md)
          │                  │
          ▼                  ▼
    inbound.db /       inbound.db /
    outbound.db        outbound.db
          │
          ▼
    mcp-crm-server.py  (FastMCP, stdio)
    └─ SQLite / Google Sheets / REST API / SharePoint / CSV
```

---

## Knowledge base and group identities

### groups/main/ — MP's private channel

All four files are loaded into the MP agent's context at the start of every session.

### `CLAUDE.md` — Agent identity and core knowledge

Defines the agent's identity, roles, and all agency policy knowledge with 2025/2026 updates:

- **5 primary roles:** pre-meeting briefing, live case triage, appeal letter drafting, policy lookup, weekly digests
- **Agency knowledge base:** HDB, CPF, MOM, MOH, MSF, ICA, IRAS, LTA, MOE, PA — eligibility thresholds, scheme names, appeal processes
- **MPS appeal letter format:** standard template used for all formal letters to agencies
- **Behavioural rules:** accuracy-first, strict confidentiality, tone, escalation awareness
- **Quick-reference routing table:** maps constituent complaints to the correct agency

### `singapore-knowledge-ingestion.md` — Current policy URLs

60+ URLs to feed into the knowledge graph, organised by priority:

| Priority | Agency | URLs |
|---|---|---|
| 1 | HDB | Grants, eligibility, BTO/resale process, Fresh Start 2026 |
| 2 | MSF / ComCare | Crisis/SMTA/PA, Silver Support, SSO locator, COS 2026 |
| 3 | CPF | Accounts, CPF LIFE, MediSave, 2026 changes |
| 4 | MOH | CHAS, MediShield Life, MediFund, CareShield Life |
| 5 | MOM | EP/S Pass/WP/LTVP, TADM, retrenchment |
| 6 | ICA | PR/citizenship appeals, LTVP/LTVP+ |
| 7 | IRAS | GST Voucher, income tax |
| 8 | MOE | FAS, Edusave, DSA, SPED |
| 9 | LTA | Senior/disability concessions |
| 10 | CDC/PA | CDC Vouchers 2026, grassroots |
| + | Portals | Budget 2025, COS 2026, SupportGoWhere, LifeSG, OneService |

### `singapore-historical-policies.md` — 70 years of policy history

9-tier archive giving the agent historical depth so it can explain *why* policies exist, not just what they are:

| Tier | Content |
|---|---|
| 1 | Foundational Acts of Parliament (HDA 1959, CPFA 1953, EA 1968, MSHA 2015, ICA 1959 …) |
| 2 | Decade-by-decade milestones 1950s–2020s with context and ingest URLs |
| 3 | Hansard / Pair Search queries for parliamentary debates on housing, CPF, ComCare, MediShield |
| 4 | NLB digitised archives and Singapore Infopedia |
| 5 | Wikipedia policy summaries (housing, CPF, healthcare, immigration, transport) |
| 6 | Agency historical pages (HDB, CPF, MOH, MOM, MSF, PA) |
| 7 | Full Budget archive 2005–2025 |
| 8 | Committee of Supply debate archives |
| 9 | Academic research papers (ADB, SMU, UNRISD, NUS) |

### `singapore-auto-update-tasks.md` — Permanent policy currency

10 copy-paste task blocks to set up automated policy monitoring:

| Block | Task name | Schedule | What it does |
|---|---|---|---|
| 1 | `daily-policy-watch` | Every morning 7am | Checks 8 agency newsrooms; silent if nothing new |
| 2 | `weekly-policy-digest` | Every Monday 8am | Structured 5-point digest of all policy changes |
| 3 | `budget-season-watch` | Feb 1 – Mar 31 daily | Same-day Budget and COS updates |
| 4 | `parliament-sitting-watch` | Every Tuesday 6pm | PQ replies on housing, CPF, healthcare, employment |
| 5 | `monthly-policy-refresh` | 1st of every month | Re-ingests all current policy pages |
| 6 | `cpf-quarterly-rates` | Jan/Apr/Jul/Oct 1 | CPF interest rates + Basic Healthcare Sum |
| 7 | `urgent-policy-alerts` | Every day 12pm | Singapore Press Centre for major announcements |
| 8 | `pre-mps-briefing` | Your MPS evening | Full pre-session policy brief |
| 9 | `annual-policy-calendar` | Key annual dates | CPF rate day, Budget month, COS month, mid-year |
| 10 | Task management | On demand | `/tasks`, pause, resume, stop |

### `feedback-log.md` — Weekly improvement input

Logs anonymised policy corrections after each MPS session for processing by Hermes GEPA. Format:

```
/feedback [wrong thing agent said] → [correct answer] | agency: [HDB/CPF/MOH/MSF/MOM/ICA]
```

No NRIC, no names, no case IDs — anonymised patterns only. Processed weekly by `weekly-skill-update.sh`.

---

### groups/mps-vetters/ — Vetter team channel

**`CLAUDE.md`** defines a focused, read-only review agent that helps vetters quality-check draft letters before the MP approves them. This agent:

- **Does not draft letters from scratch** — that is the volunteer's role
- **Runs 5 checks on every draft:** agency name accuracy, scheme/policy accuracy, request clarity, tone, and missing information
- **Returns a clear verdict:** PASS / NEEDS REVISION / FLAG with line-by-line corrections
- **Carries 2025/2026 policy quick-reference** for HDB, CPF, MOH, MSF, MOM, and ICA
- **Escalates immediately** for child abuse, domestic violence, suicidal ideation, criminal matters, or medical emergencies — with the correct hotline number

---

## Self-improvement via Hermes GEPA

nanoClaw's knowledge base grows through ingestion. Agent reasoning improves through weekly GEPA cycles in the companion Hermes repo.

### During MPS sessions

Type in the main group chat after spotting an error:

```
/feedback EHG ceiling cited as $9,000 → correct ceiling is $8,000 for families | agency: HDB
```

The agent logs an anonymised correction to `groups/main/feedback-log.md`.

### Every Sunday

```bash
bash weekly-skill-update.sh
```

The script:
1. Scans feedback-log.md for NRIC/phone patterns — rejects if found
2. Prompts manual review before any export
3. Sends anonymised patterns to Hermes GEPA
4. Shows generated skill improvements for your review
5. Prompts you to merge approved changes into CLAUDE.md
6. Restarts nanoClaw
7. Archives the week's log

Full workflow: [INTEGRATION.md](./INTEGRATION.md)

---

## CRM Bridge — case management integration

`mcp-crm-server.py` connects the agent to your case records via MCP. Five backends supported:

| Backend | `CRM_BACKEND` value | Best for |
|---|---|---|
| **SQLite** | `sqlite` | Default — no infrastructure, works immediately |
| **Google Sheets** | `google_sheets` | Shared spreadsheet accessible by MP's office team |
| **REST API** | `rest_api` | Existing CRM system with a JSON API |
| **SharePoint** | `sharepoint` | Organisations already on Microsoft 365 |
| **CSV** | `csv` | Read-only import of legacy case exports |

### MCP tools available to the agent

| Tool | What the agent can do |
|---|---|
| `lookup_constituent` | Pull full profile + all past cases + letters before an MP meeting |
| `create_case` | Log a new case with issue type, agency, urgency, and volunteer name |
| `attach_letter` | Store the full text of a drafted appeal letter against its case |
| `update_case_status` | Mark a case as replied / resolved / escalated when agency responds |
| `get_pending_cases` | List all open cases with no reply after N days (default 21) |
| `get_todays_queue` | Show tonight's MPS case list sorted by urgency |

### Wire into NanoClaw

```yaml
# nanoclaw.yaml
mcp_servers:
  crm-bridge:
    type: stdio
    command: python3
    args: [~/nanoclaw/mcp-crm-server.py]
    env:
      CRM_BACKEND: sqlite
      CRM_DATA_DIR: ~/nanoclaw/crm-data

groups:
  main:
    role: owner
    mcp_servers: [crm-bridge]
  mps-volunteers:
    role: member
    mcp_servers: [crm-bridge]
  mps-vetters:
    role: member
    claude_md: groups/mps-vetters/CLAUDE.md
    mcp_servers: []          # No CRM access — policy lookup only
```

---

## Security

Constituent data is highly sensitive. Every security control is non-negotiable.

| Control | What it does |
|---|---|
| **API key isolation** | OneCLI Agent Vault proxies all Anthropic API calls — the container never holds a raw key |
| **Sender allowlist** | Only the MP's verified number can trigger the agent; all others are silently dropped |
| **Container isolation** | Each channel group runs in its own Docker container with its own filesystem and Claude session |
| **Mount allowlist** | Containers can only access explicitly permitted directories — `.ssh`, `.aws`, credentials are blocked |
| **Local-only voice** | whisper.cpp transcribes voice notes on-device; audio bytes never leave the machine |
| **Local-only embeddings** | nomic-embed-text runs in Ollama locally; no document content sent to cloud embedding APIs |
| **Web UI binding** | Web UI binds to `127.0.0.1` only — not accessible from the network |
| **Group name validation** | Group folder names strictly validated (alphanumeric, hyphens, underscores only) |
| **Hermes boundary** | Constituent data never crosses to the Hermes skill engine — only anonymised patterns |

> **On prompt injection:** This is an acknowledged open problem. The sender allowlist is the primary defence. Do not connect the agent to systems whose compromise would be severe.

---

## Prerequisites

Run in your **WSL2 Ubuntu** terminal:

```bash
# 1. Confirm WSL2
wsl.exe --list --verbose   # VERSION must show 2 for Ubuntu

# 2. Build tools
sudo apt-get update && sudo apt-get install -y build-essential python3 git curl

# 3. Docker reachable from WSL
docker ps
# If not: Docker Desktop → Settings → Resources → WSL Integration → enable Ubuntu

# 4. Clone into Linux filesystem (not /mnt/c/ — 10-100x slower)
cd ~
git clone https://github.com/J-Dheeraj/MPS-AI-Agent-_nanoClaw nanoclaw
cd nanoclaw

# 5. Anthropic API key ready (sk-ant-...)
# https://console.anthropic.com/settings/api-keys — add $10–20 credit
```

---

## Installation

```bash
cd ~/nanoclaw
bash nanoclaw.sh
```

The installer:

1. Installs Node 22 (nvm) and pnpm 10
2. Installs **OneCLI Agent Vault** and stores your API key — the agent never sees it directly
3. Builds the Docker agent container image
4. Creates `~/.config/nanoclaw/mount-allowlist.json` and `sender-allowlist.json`
5. Registers a systemd user service

---

## First-time setup

### 1. Customise the agent identity

Edit `groups/main/CLAUDE.md` — replace `[MP NAME]` and `[CONSTITUENCY]` with the MP's actual name and constituency.

### 2. Set your sender allowlist

```json
{
  "defaultMode": "drop",
  "groups": {
    "main": {
      "mode": "drop",
      "allowedSenders": ["6591234567@s.whatsapp.net"]
    }
  }
}
```

Replace `6591234567` with the MP's number in international format.

### 3. Pair your channel

```
/add-whatsapp    → scan QR code in WhatsApp → Settings → Linked Devices
/add-telegram    → create bot via @BotFather, paste token
```

Web UI: available immediately at `http://localhost:3080`.

### 4. Set up local AI

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull nomic-embed-text
# In web UI: /add-ollama
```

### 5. Build the policy knowledge base

Follow `groups/main/singapore-knowledge-ingestion.md` — ingest Priority 1 → 10.

### 6. Set up auto-update tasks

Send each of the 10 task blocks from `singapore-auto-update-tasks.md` to the agent.

### 7. Set up Hermes GEPA (companion repo)

```bash
cd ~
git clone https://github.com/J-Dheeraj/MPS-AI-Agent-Hermes mps-hermes-agent
mkdir -p ~/mps-hermes-agent/skills/auto
chmod +x ~/nanoclaw/weekly-skill-update.sh
```

See [INTEGRATION.md](./INTEGRATION.md) for full setup.

---

## Security verification checklist

```bash
# 1. No API keys in any container
docker inspect $(docker ps -q) | grep -i "sk-ant\|anthropic_api\|api_key"
# Expected: no output

# 2. Sender allowlist active — send from a number not in your allowlist
# Expected: no response, nothing stored

# 3. Mount allowlist enforced
docker run --rm -v ~/.ssh:/test alpine ls /test
# Expected: permission error

# 4. Voice stays on-device
docker logs $(docker ps -q --filter name=whatsapp) --tail 20
# Expected: "whisper transcription complete" — no external audio API calls

# 5. Embeddings local only
ollama list | grep nomic-embed-text
# Expected: model listed; no outbound calls to embedding APIs during ingestion

# 6. Web UI localhost only
# From another machine: curl http://YOUR_PC_IP:3080
# Expected: connection refused

# 7. Hermes boundary — check feedback-log.md before each Sunday export
grep -E '[STFG][0-9]{7}[A-Z]' groups/main/feedback-log.md
# Expected: no output (no NRICs)
```

---

## Project structure

```
nanoclaw/
├── groups/
│   ├── main/
│   │   ├── CLAUDE.md                         ← MP agent identity, roles, agency knowledge
│   │   ├── singapore-knowledge-ingestion.md  ← 60+ current policy URLs, priority 1–10
│   │   ├── singapore-historical-policies.md  ← 70-year policy history, 9 tiers
│   │   ├── singapore-auto-update-tasks.md    ← 10 scheduled monitoring task blocks
│   │   └── feedback-log.md                   ← Anonymised GEPA correction patterns (weekly)
│   └── mps-vetters/
│       └── CLAUDE.md                         ← Vetter: 5-check review, PASS/FAIL verdicts
├── INTEGRATION.md                            ← Combined nanoClaw + Hermes workflow
├── weekly-skill-update.sh                    ← Weekly GEPA pipeline (export → evolve → apply)
├── mps-workflow-integration.md               ← 3-stage MPS workflow, platform comparison
├── mcp-crm-server.py                         ← CRM Bridge MCP server (5 backends)
├── nanoclaw-crm-wiring.yaml                  ← Copy-paste wiring guide (4 blocks)
├── requirements-crm.txt                      ← Python deps for CRM bridge
├── nanoclaw.yaml                             ← Full config: 3 groups, MCP wired
├── src/
│   ├── index.ts                   # Host process orchestrator
│   ├── router/index.ts            # Message routing + sender validation
│   ├── security/
│   │   ├── groupNames.ts          # Strict name validation
│   │   ├── senderAllowlist.ts     # drop / trigger enforcement
│   │   └── mountAllowlist.ts      # Mount path enforcement
│   ├── channels/
│   │   ├── whatsapp.ts            # Baileys connector
│   │   ├── telegram.ts            # Telegram bot
│   │   ├── webui.ts               # Express on 127.0.0.1:3080
│   │   └── cli.ts                 # Terminal interface
│   ├── container/runner.ts        # Docker spawner (no API keys passed)
│   ├── delivery/index.ts          # outbound.db poller
│   └── scheduler/index.ts         # Cron task runner
├── container/
│   ├── Dockerfile                 # Bun/Alpine agent image
│   ├── build.sh
│   └── agent/
│       ├── index.ts               # Claude agentic loop
│       ├── mnemon/index.ts        # SQLite + FTS5 knowledge graph
│       └── tools/
│           ├── ingest.ts          # URL / document ingestion
│           └── search.ts          # Semantic search
├── public/index.html              # Web chat UI
├── nanoclaw.sh                    # Installer
├── start-nanoclaw.sh              # Manual start (no systemd)
└── .env.example
```

---

## Important caveats

1. **Constituent confidentiality is paramount.** The sender allowlist must be configured before pairing any channel. Default mode is `drop` — all unknown senders are silently ignored and not stored.

2. **Hermes boundary.** Only anonymised correction patterns leave nanoClaw for the Hermes GEPA engine. The `weekly-skill-update.sh` script includes a PII scan and requires manual confirmation before any export.

3. **Policy accuracy.** Singapore policies change at Budget (February) and COS (March). The auto-update tasks keep the knowledge base current, but verify with the agency before sending a letter under the MP's name.

4. **Prompt injection is not solved.** Rate limits and the sender allowlist reduce the blast radius but do not eliminate the risk. Do not connect the agent to external systems whose compromise would be severe.

5. **WhatsApp ToS.** Baileys uses the WhatsApp Web protocol, which is against WhatsApp's ToS for automated use. This is for personal/professional use only.

6. **API costs.** Monitor usage at [console.anthropic.com/usage](https://console.anthropic.com/usage). Set a spending limit before going live.

---

## References

- [MPS-AI-Agent-Hermes](https://github.com/J-Dheeraj/MPS-AI-Agent-Hermes) — companion GEPA skill engine
- [INTEGRATION.md](./INTEGRATION.md) — combined system workflow and security boundary
- [Anthropic Console](https://console.anthropic.com)
- [OneCLI Agent Vault](https://github.com/onecli/onecli)
- [NanoClaw platform](https://github.com/nanocoai/nanoclaw)
- [HDB](https://www.hdb.gov.sg) · [CPF](https://www.cpf.gov.sg) · [MOM](https://www.mom.gov.sg) · [MOH](https://www.moh.gov.sg) · [MSF](https://www.msf.gov.sg) · [ICA](https://www.ica.gov.sg) · [IRAS](https://www.iras.gov.sg) · [LTA](https://www.lta.gov.sg) · [MOE](https://www.moe.gov.sg)
- [Singapore Budget Archive](https://singaporebudget.gov.sg)
- [Singapore Parliament Hansard](https://sprs.parl.gov.sg/search/)
- [SupportGoWhere](https://supportgowhere.life.gov.sg)

---

## License

MIT
