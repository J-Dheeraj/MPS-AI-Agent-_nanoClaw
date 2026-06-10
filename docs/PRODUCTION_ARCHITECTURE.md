# Production Architecture

## Canonical boundary

The supported MPS production path is:

`Tauri client -> HTTPS/WSS Caddy gateway -> FastAPI workflow service -> PostgreSQL`

`FastAPI -> internal Ollama endpoint`

`FastAPI -> read-only, manifested policy release`

Hermes is a separate, offline content-governance subsystem. It may consume approved, PII-screened feedback batches and produce review proposals. It has no direct access to live constituent records and cannot modify active policy. A named reviewer must approve a proposal before the promotion command creates a new manifested policy release.

The generic TypeScript channel runtime, GTK client, Telegram profiles, and direct Hermes CRM integration are not supported production components. They remain reference or development code and must not be deployed with constituent data.

## Trust boundaries

- Client devices hold bearer tokens in memory only.
- Caddy is the only network-exposed service and terminates TLS.
- PostgreSQL, Ollama, Prometheus, and FastAPI use an internal container network.
- Policy releases are mounted read-only and verified against SHA-256 hashes before use.
- Model output is untrusted until deterministic blocking checks pass.
- Vetter-approved final text is validated again and frozen as an immutable revision.
- Hermes CRM writes are disabled by default and require payload-bound, short-lived approval tokens when explicitly enabled for testing.

## Availability model

The deployment is a single-site architecture. PostgreSQL has durable storage, but Caddy, FastAPI, Ollama, and the host remain a site-level failure domain. Multi-site or high-availability use requires redundant gateways, replicated PostgreSQL, independently scalable model workers, tested failover, and tenant-specific keys.
