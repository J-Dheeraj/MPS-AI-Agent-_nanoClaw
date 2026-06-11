"""
mps-server — FastAPI entry point
NanoClaw MPS AI Agent
"""
import os
import sys
import logging
import hmac
import time
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse, Response
from prometheus_client import Counter, Gauge, Histogram, CONTENT_TYPE_LATEST, generate_latest
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .config import read_secret

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(
            {
                "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            },
            ensure_ascii=True,
        )


if os.getenv("LOG_FORMAT", "text").lower() == "json":
    for handler in logging.getLogger().handlers:
        handler.setFormatter(JsonFormatter())

log = logging.getLogger("mps-server")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
IS_PRODUCTION = ENVIRONMENT == "production"
HTTP_REQUESTS = Counter(
    "mps_http_requests_total", "HTTP requests", ["method", "route", "status"]
)
HTTP_DURATION = Histogram(
    "mps_http_request_duration_seconds", "HTTP request duration", ["method", "route"]
)
LLM_QUEUE_DEPTH = Gauge("mps_llm_queue_depth", "Current waiting LLM requests")


def _validate_production_config() -> None:
    """Fail closed when production starts with development-grade settings."""
    if not IS_PRODUCTION:
        return
    from .database import DATABASE_URL as database_url
    if not database_url.startswith(("postgresql://", "postgresql+")):
        raise RuntimeError("Production requires PostgreSQL via DATABASE_URL")
    origins = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "").split(",") if origin.strip()]
    if not origins or any(not origin.startswith("https://") for origin in origins):
        raise RuntimeError("Production ALLOWED_ORIGINS must contain HTTPS origins only")
    if not os.getenv("TRUSTED_HOSTS", "").strip():
        raise RuntimeError("Production requires an explicit TRUSTED_HOSTS allowlist")
    force_https = os.getenv("FORCE_HTTPS", "true").lower() in {"1", "true", "yes"}
    proxy_tls = os.getenv("TLS_TERMINATED_BY_PROXY", "false").lower() in {"1", "true", "yes"}
    if not force_https and not proxy_tls:
        raise RuntimeError(
            "Production requires FORCE_HTTPS=true or TLS_TERMINATED_BY_PROXY=true"
        )
    if len(read_secret("METRICS_TOKEN", "") or "") < 32:
        raise RuntimeError("Production requires a METRICS_TOKEN of at least 32 characters")
    policy_dir = os.getenv(
        "POLICY_DIR",
        str((__import__("pathlib").Path(__file__).resolve().parents[1] / "policy" / "active")),
    )
    if not __import__("pathlib").Path(policy_dir, "manifest.json").is_file():
        raise RuntimeError("Production requires a manifested active policy store")
    # Policy manifests must be cryptographically signed by the managed release
    # key in production. Without POLICY_PUBLIC_KEY the manifest signature is not
    # verified and a forged manifest with recomputed hashes would be trusted.
    public_key = os.getenv("POLICY_PUBLIC_KEY", "").strip()
    if not public_key or not __import__("pathlib").Path(public_key).is_file():
        raise RuntimeError("Production requires POLICY_PUBLIC_KEY pointing at the release public key")
    if not __import__("pathlib").Path(policy_dir, "manifest.json.sig").is_file():
        raise RuntimeError("Production policy manifest must be signed (manifest.json.sig)")

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

EXPECTED_SCHEMA_REVISION = "20260610_01"

# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_production_config()
    from sqlalchemy import inspect, text as _sql
    if IS_PRODUCTION:
        inspector = inspect(engine)
        if not inspector.has_table("alembic_version"):
            raise RuntimeError("Database is not migrated; run alembic upgrade head")
        with engine.connect() as conn:
            revision = conn.execute(_sql("SELECT version_num FROM alembic_version")).scalar_one()
        if revision != EXPECTED_SCHEMA_REVISION:
            raise RuntimeError(
                f"Database schema is {revision}; expected {EXPECTED_SCHEMA_REVISION}. "
                "Run alembic upgrade head."
            )
        log.info("Database schema revision verified: %s", revision)
    else:
        # Development convenience only. Production is exclusively Alembic-managed.
        Base.metadata.create_all(bind=engine)
        log.info("Development database tables verified / created")

        if engine.dialect.name == "sqlite":
            with engine.connect() as conn:
                cols = [row[1] for row in conn.execute(_sql("PRAGMA table_info(cases)"))]
                if cols and "notes" not in cols:
                    conn.execute(_sql("ALTER TABLE cases ADD COLUMN notes TEXT"))
                    conn.commit()
                audit_cols = [row[1] for row in conn.execute(_sql("PRAGMA table_info(audit_log)"))]
                if audit_cols and "hash_version" not in audit_cols:
                    conn.execute(_sql("ALTER TABLE audit_log ADD COLUMN hash_version INTEGER NOT NULL DEFAULT 1"))
                    conn.commit()
                feedback_cols = [row[1] for row in conn.execute(_sql("PRAGMA table_info(feedback_entries)"))]
                feedback_additions = {
                    "source_title": "TEXT",
                    "source_url": "TEXT",
                    "effective_date": "TEXT",
                    "exported_at": "DATETIME",
                    "export_batch_id": "TEXT",
                }
                for column, column_type in feedback_additions.items():
                    if feedback_cols and column not in feedback_cols:
                        conn.execute(_sql(f"ALTER TABLE feedback_entries ADD COLUMN {column} {column_type}"))
                        conn.commit()

    # A process restart terminates all in-flight model streams. Return those
    # cases to a draftable state; completed drafts are persisted before delivery.
    from .database import Case
    recovery_db = SessionLocal()
    try:
        interrupted = recovery_db.query(Case).filter(Case.status == "drafting").all()
        for case in interrupted:
            case.status = "assigned"
        if interrupted:
            recovery_db.commit()
            log.warning("Recovered %d interrupted drafting cases", len(interrupted))
    finally:
        recovery_db.close()

    # Seed a default admin account if no users exist
    _seed_admin()

    log.info("mps-server ready")
    yield
    log.info("mps-server shutting down")


def _seed_admin():
    """Create the first admin without leaking production credentials to logs."""
    import secrets
    from .auth import hash_password
    from .database import User

    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            if IS_PRODUCTION:
                one_time_pw = read_secret("BOOTSTRAP_ADMIN_PASSWORD")
                if not one_time_pw or len(one_time_pw) < 16:
                    raise RuntimeError(
                        "Production requires BOOTSTRAP_ADMIN_PASSWORD or "
                        "BOOTSTRAP_ADMIN_PASSWORD_FILE with at least 16 characters"
                    )
            else:
                one_time_pw = secrets.token_urlsafe(12)
            admin = User(
                username=os.getenv("BOOTSTRAP_ADMIN_USERNAME", "admin").strip().lower(),
                hashed_pw=hash_password(one_time_pw),
                role="admin",
                full_name=os.getenv("BOOTSTRAP_ADMIN_FULL_NAME", "System Admin").strip(),
                is_active=True,
            )
            db.add(admin)
            db.commit()
            log.warning("=" * 60)
            log.warning("FIRST RUN - admin account created: %s", admin.username)
            if IS_PRODUCTION:
                log.warning("Use the bootstrap secret, then rotate it immediately")
            else:
                log.warning("Development one-time password: %s", one_time_pw)
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
    docs_url=None if IS_PRODUCTION or os.getenv("DISABLE_DOCS") else "/docs",
    redoc_url=None if IS_PRODUCTION or os.getenv("DISABLE_DOCS") else "/redoc",
)

# Restrict Host headers before routing. Production startup requires this to be
# explicitly configured for the internal DNS name and health-check host.
_trusted_hosts = [
    host.strip()
    for host in os.getenv("TRUSTED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_trusted_hosts)
_proxy_tls = os.getenv("TLS_TERMINATED_BY_PROXY", "false").lower() in {"1", "true", "yes"}
if not _proxy_tls and os.getenv("FORCE_HTTPS", "false").lower() in {"1", "true", "yes"}:
    app.add_middleware(HTTPSRedirectMiddleware)

_allowed_origins = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:8080").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers_and_limits(request: Request, call_next):
    started = time.perf_counter()
    max_body_bytes = int(os.getenv("MAX_REQUEST_BYTES", "1048576"))
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_body_bytes:
                return JSONResponse(status_code=413, content={"detail": "Request body too large"})
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length"})

    response = await call_next(request)
    route = getattr(request.scope.get("route"), "path", "unmatched")
    HTTP_REQUESTS.labels(request.method, route, str(response.status_code)).inc()
    HTTP_DURATION.labels(request.method, route).observe(time.perf_counter() - started)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if IS_PRODUCTION:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(sessions_router)
app.include_router(residents_router)
app.include_router(cases_router)
app.include_router(letters_router)
app.include_router(feedback_router)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health/live", tags=["health"])
async def liveness():
    return {"status": "ok", "service": "mps-server"}


@app.get("/health/ready", tags=["health"])
async def readiness():
    from sqlalchemy import text as _sql
    from .services.ollama_client import llm_queue
    database_ok = True
    try:
        with engine.connect() as connection:
            connection.execute(_sql("SELECT 1"))
    except Exception:
        database_ok = False
    ollama_ok = await llm_queue.health_check()
    status_code = 200 if database_ok and ollama_ok else 503
    return JSONResponse(status_code=status_code, content={
        "status": "ready" if status_code == 200 else "not_ready",
        "service": "mps-server",
        "database": "up" if database_ok else "down",
        "ollama": "up" if ollama_ok else "down",
        "llm_queue_waiting": llm_queue.depth(),
    })


@app.get("/health", include_in_schema=False)
async def health_compatibility():
    return await readiness()


@app.get("/metrics", include_in_schema=False)
async def metrics(request: Request):
    configured = read_secret("METRICS_TOKEN", "") or ""
    supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
    if configured and not hmac.compare_digest(configured, supplied):
        raise HTTPException(status_code=401, detail="Unauthorised")
    LLM_QUEUE_DEPTH.set(__import__("mps_server.services.ollama_client", fromlist=["llm_queue"]).llm_queue.depth())
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


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
        reload=os.getenv("RELOAD", "false").lower() == "true" and not IS_PRODUCTION,
        log_level="info",
    )
