> # ⚠️ SUPERSEDED — DO NOT DEPLOY FROM THIS DOCUMENT
>
> This document describes an **early WhatsApp/Telegram multi-channel design that is NOT the supported architecture** and must not be deployed. Cloud messaging channels are disabled for constituent data: Telegram/WhatsApp would route constituent information off-premises, which the privacy model forbids.
>
> The canonical, supported architecture is the **FastAPI service + Tauri desktop client + local web UI**, documented in [`docs/PRODUCTION_ARCHITECTURE.md`](docs/PRODUCTION_ARCHITECTURE.md). Use that document. This file is retained only for historical context.

---

# MPS Workflow Integration

## How NanoClaw works alongside the MPS case management platform

This document explains the relationship between NanoClaw (your AI agent) and your existing MPS case management platform. They are two separate systems that complement each other — NanoClaw never logs into or replaces the platform.

---

## The two systems, side by side

```
┌─────────────────────────────────┐    ┌──────────────────────────────────┐
│       MPS PLATFORM              │    │         NANOCLAW AGENT            │
│  (your existing web system)     │    │  (WhatsApp / Telegram / Web UI)   │
│                                 │    │                                    │
│  • Official record of all cases │    │  • AI-powered policy advisor       │
│  • Login + 2FA (SMS/WhatsApp)   │    │  • Letter drafter                  │
│  • Vetting workflow             │    │  • Case history lookup             │
│  • Agency email dispatch        │    │  • Pre-MPS briefing                │
│  • Audit trail for MP office    │    │  • Overdue case tracker            │
│                                 │    │                                    │
│  WHO USES IT:                   │    │  WHO USES IT:                      │
│  Volunteers, Vetters, MP        │    │  Volunteers (WhatsApp group)       │
│                                 │    │  Vetters (separate group)          │
│                                 │    │  MP (private channel)              │
└─────────────────────────────────┘    └──────────────────────────────────┘
         ↑                                           ↑
         │                                           │
         └──── Humans carry information between ─────┘
               the two systems. No direct API
               connection needed until you
               have the platform URL.
```

---

## Stage-by-stage workflow — where NanoClaw helps

### STAGE 1 — Volunteer intake

**In the MPS hall (physical)**

- Constituent hands volunteer a case slip with their issue  
- Volunteer opens the platform on their PC (logs in with 2FA at start of session)

**In NanoClaw (WhatsApp volunteer group)**

- Volunteer sends a brief description to the agent:

  > Constituent Mdm Tan, 65F, HDB rental flat Toa Payoh.  
  > Received eviction notice. Husband passed away, name only on flat.  
  > Has no income. Very distressed.

- Agent responds instantly with:

  1. Relevant policy (HDB Public Rental Scheme eligibility, widow exception rules)
  2. Which agency owns the issue (HDB Branch or HDB customer service)
  3. A complete draft email the volunteer can paste into the platform
  4. Urgency flag if applicable

- Volunteer copy-pastes the draft email into the platform  
- Volunteer creates the case in the platform, selects the agency, pastes subject and body  
- Case is submitted for vetting

---

### STAGE 2 — Vetter review

**In the MPS platform**

- Vetter opens the case, reads the volunteer's draft  
- Vetter refines wording, checks factual accuracy, adjusts tone

**In NanoClaw (Vetter group — optional)** If vetter is unsure about a policy detail:

> Is a widow eligible to retain the HDB rental flat if her husband was
> the sole tenant? What's the rule exactly?

- Agent answers with the precise policy and cites the source  
- Vetter uses this to strengthen the email before marking it ready for MP

---

### STAGE 3 — MP review and send

**In the MPS platform**

- MP sees the vetted draft  
- MP reads, approves, and sends to the agency directly from the platform

**In NanoClaw (MP private channel)** MP can ask before approving:

> Has this constituent come to MPS before?
> What was the outcome last time?

- Agent checks the local SQLite case history (NanoClaw's own records) and surfaces any prior visits, prior letters, and agency responses  

- After approving in the platform, MP (or volunteer) records the case in NanoClaw:

  > create a case for S9876543B — HDB rental appeal, Toa Payoh, urgent  
  > attach this letter to case 42: [paste the final letter text]

  This keeps NanoClaw's local records in sync with the platform.

---

## NanoClaw group structure for this workflow

```
nanoclaw.yaml
├── groups/
│   ├── main/                ← MP only (private WhatsApp/Telegram)
│   │   └── CLAUDE.md        ← Full policy access, case history, pre-MPS briefing
│   │
│   ├── mps-volunteers/      ← All volunteers (shared WhatsApp group)
│   │   └── CLAUDE.md        ← Draft letters, policy lookup, intake triage
│   │
│   └── mps-vetters/         ← Vetters only (separate WhatsApp group)
│       └── CLAUDE.md        ← Policy verification, draft quality check
```

---

## groups/mps-vetters/CLAUDE.md — vetter-specific agent behaviour

```
You are assisting vetters who review MP appeal letters before
they are sent to government agencies.

Your role:

1. Verify policy facts in draft letters — confirm the scheme name,
   eligibility criteria, income thresholds, and agency contact are correct

2. Flag any statements in the draft that are factually uncertain or
   that may have changed since the last Budget / COS

3. Suggest improvements to tone if the draft is too informal or too
   combative — MP letters must be formal, specific, and never promise
   outcomes the agency cannot deliver

4. Answer policy questions the vetter has while reviewing the case

You do NOT draft full letters from scratch in this channel — that is
the volunteer's role. You verify, fact-check, and improve.

Behavioural rules:
- Always cite the source agency for policy facts
- Flag if a policy may have changed (check against 2025/2026 Budget
  and Committee of Supply announcements)
- Never suggest adding information about the constituent that was not
  provided to you
- Confidentiality applies: do not reference other cases or constituents
```

---

## What to record in NanoClaw (SQLite) vs the platform

| Information | Record in Platform | Record in NanoClaw |
|---|---|---|
| Official case number | ✅ Yes | ✅ Reference only |
| Constituent NRIC + personal details | ✅ Yes | ✅ For lookup |
| Draft and final letter text | ✅ Yes | ✅ For history |
| Agency selected + email subject | ✅ Yes | ✅ For history |
| Agency reply received | ✅ Yes | ✅ For follow-up |
| Overdue case alerts | ❌ Manual | ✅ Automatic |
| Pre-MPS policy briefing | ❌ Not available | ✅ Automatic |
| Historical case pattern for MP | ❌ Manual reports | ✅ Ask the agent |

---

## Playwright integration — when you have the platform URL

Once you can share the platform URL, a Playwright-based MCP tool can be added that automates these steps:

1. **Read case details** — agent navigates to the platform (in an already logged-in browser), reads the petitioner name, NRIC, issue type, and any prior notes, and returns them to the conversation  

2. **Pre-fill the draft** — agent types the drafted letter into the platform's subject and body fields  

3. **Select the agency** — agent selects the correct agency from the platform's dropdown

You still handle login + 2FA manually at the start of each session. The Playwright automation only takes over once you are already logged in.

---

## Immediate next steps (no platform URL needed)

1. Complete NanoClaw core setup (WSL2, Docker, Anthropic API key)  
2. Create the three WhatsApp groups: main, mps-volunteers, mps-vetters  
3. Place the CLAUDE.md files in the correct group folders  
4. Run the knowledge ingestion commands (singapore-knowledge-ingestion.md)  
5. Run the auto-update scheduled tasks (singapore-auto-update-tasks.md)  
6. At your next MPS session, test the volunteer draft workflow manually:
   - Describe a case in the volunteer group  
   - Check the agent's draft letter quality and policy accuracy  
   - Paste the draft into your platform as normal  
7. When platform URL is available, add Playwright read/fill automation

---

## Testing NanoClaw before your first live MPS

Send these to the volunteer WhatsApp group to verify the agent is ready:

> Constituent is a 70-year-old widow living alone in HDB rental flat.
> Husband passed away. She is worried she has to leave the flat.
> Draft an email to HDB on her behalf.

> Constituent says his CPF OA has money but HDB says he cannot use it
> for his flat purchase. He earns $6,500 a month. What is the issue
> and who do we write to?

> Constituent's CHAS blue card was rejected on renewal.
> Household income is $1,600 for 3 people. Should they qualify?
> Draft the appeal letter.

If all three produce accurate, well-structured draft letters with the correct scheme names, income thresholds, and agency addresses — your agent is ready for live MPS.
