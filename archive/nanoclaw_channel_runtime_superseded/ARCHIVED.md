# Archived: NanoClaw generic channel runtime (TypeScript)

**Archived 2026-06-20.** Superseded; not part of the supported MPS production boundary.

## What this was

The original NanoClaw personal-agent runtime: a generic TypeScript channel
agent (WhatsApp / Telegram / Web UI / CLI) with its own router, scheduler,
delivery and container runner under `src/`, plus the root `package.json` /
`tsconfig.json`.

## Why it was archived

The supported MPS AI Agent production path is the Python workflow server
(`mps_server/`, FastAPI + PostgreSQL + Ollama) with the Tauri desktop client
(`nanoclaw-tauri-client/`). The generic channel runtime is **not** on that path:

- It is outside the documented production boundary (Tauri → Caddy → FastAPI →
  PostgreSQL), so keeping it live created ownership ambiguity and avoidable
  attack surface (the production-readiness review flagged its npm advisories —
  1 critical / 3 high / 8 moderate — sitting in an active root runtime).
- Constituent casework never flows through these channels; the MPS workflow is
  driven entirely by the authenticated desktop client and the server.

This mirrors the earlier archival of the superseded GTK client
(`archive/mps_client_gtk_superseded/`).

## If you need it again

Restore the tree from git history and bring it under root `npm audit` +
Dependabot and an explicit ownership/security review before running it. Do not
deploy it alongside the MPS production stack without that review.
