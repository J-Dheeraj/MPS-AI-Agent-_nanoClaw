"""
mps-server — FastAPI entry point
NanoClaw MPS AI Agent
"""
import os
import sys
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("mps-server")

# ── Database init ─────────────────────────────────────────────────────────────
from .database import Base, engine, SessionLocal
from . import database  # noqa: F401 — registers all models

# ── Routers ───────────────────────────────────────────────────────────────────
from .routers.auth_router     import router as auth_router
from .routers.sessions_router import router as sessions_router
from .routers.residents_router import router as residents_router
from .routers.cases_router    import router as cases_router
from .routers.letters_router  import router as letters_router
from .routers.feedback_router import router as feedback_router

# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables if they do not exist (SQLite dev mode)
    Base.metadata.create_all(bind=engine)
    log.info("Database tables verified / created")

    # Lightweight migration: add cases.notes if the DB predates the column
    # (create_all does not alter existing tables).
    with engine.connect() as conn:
        from sqlalchemy import text as _sql
        cols = [row[1] for row in conn.execute(_sql("PRAGMA table_info(cases)"))]
        if cols and "notes" not in cols:
            conn.execute(_sql("ALTER TABLE cases ADD COLUMN notes TEXT"))
            conn.commit()
            log.info("Migrated: added cases.notes column")

    # Seed a default admin account if no users exist
    _seed_admin()

    log.info("mps-server ready")
    yield
    log.info("mps-server shutting down")


def _seed_admin():
    """On first run, create an admin account with a RANDOM one-time password.
    The password is printed to the server console exactly once - it is not
    stored anywhere in plaintext. Change it after first login."""
    import secrets
    from .auth import hash_password
    from .database import User

    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            one_time_pw = secrets.token_urlsafe(12)
            admin = User(
                username="admin",
                hashed_pw=hash_password(one_time_pw),
                role="admin",
                full_name="System Admin",
                is_active=True,
            )
            db.add(admin)
            db.commit()
            log.warning("=" * 60)
            log.warning("FIRST RUN - admin account created")
            log.warning("  username: admin")
            log.warning("  password: %s", one_time_pw)
            log.warning("This password is shown ONCE. Log in and change it")
            log.warning("immediately via PUT /auth/change-password.")
            log.warning("=" * 60)
    finally:
        db.close()


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="MPS AI Agent — Server",
    description="NanoClaw + Hermes backend for Meet-the-People Sessions",
    version="1.0.0",
    lifespan=lifespan,
    # Disable OpenAPI docs in production via env var
    docs_url=None if os.getenv("DISABLE_DOCS") else "/docs",
    redoc_url=None if os.getenv("DISABLE_DOCS") else "/redoc",
)

# Allow GTK4 client running on same machine (localhost only)
_allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:8080").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(sessions_router)
app.include_router(residents_router)
app.include_router(cases_router)
app.include_router(letters_router)
app.include_router(feedback_router)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["health"])
async def health():
    from .services.ollama_client import llm_queue
    ollama_ok = await llm_queue.health_check()
    return {
        "status": "ok",
        "service": "mps-server",
        "ollama": "up" if ollama_ok else "down",
        "llm_queue_waiting": llm_queue.depth(),
    }


@app.get("/", tags=["health"], response_class=HTMLResponse)
async def root():
    return HTMLResponse(content="""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>MPS AI Agent</title>
  <style>
    body{font-family:system-ui,sans-serif;max-width:640px;margin:60px auto;padding:0 20px;background:#f9f9f9;color:#222}
    h1{font-size:1.6rem;margin-bottom:4px}
    .badge{display:inline-block;padding:2px 10px;border-radius:12px;font-size:.75rem;background:#22c55e;color:#fff;vertical-align:middle;margin-left:8px}
    p{color:#555;margin-top:0}
    a.btn{display:inline-block;margin:8px 8px 8px 0;padding:10px 20px;border-radius:8px;text-decoration:none;font-weight:600;font-size:.95rem}
    .primary{background:#2563eb;color:#fff}
    .secondary{background:#e5e7eb;color:#111}
    ul{color:#555;line-height:2}
    code{background:#e5e7eb;padding:2px 6px;border-radius:4px;font-size:.9rem}
  </style>
</head>
<body>
  <h1>MPS AI Agent <span class="badge">&#x2713; running</span></h1>
  <p>FastAPI backend &mdash; LAN only &mdash; Ollama on-premises</p>
  <a class="btn primary" href="/docs">API Docs (Swagger)</a>
  <a class="btn secondary" href="/redoc">ReDoc</a>
  <a class="btn secondary" href="/health">Health check</a>
  <hr style="margin:24px 0;border:none;border-top:1px solid #ddd">
  <ul>
    <li><code>POST /auth/login</code> &mdash; get JWT token</li>
    <li><code>GET /cases/queue</code> &mdash; vetter queue</li>
    <li><code>WS /letters/ws/draft</code> &mdash; streaming draft generation</li>
    <li><code>GET /feedback/approved</code> &mdash; Hermes GEPA feed</li>
  </ul>

</body>
</html>""")


# ── Global error handler ──────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.exception("Unhandled exception for %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error — check server logs"},
    )


# ── Dev entrypoint ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "mps_server.main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("RELOAD", "true").lower() == "true",
        log_level="info",
    )
