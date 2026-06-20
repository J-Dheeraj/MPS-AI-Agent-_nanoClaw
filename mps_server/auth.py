"""
MPS Server - Authentication and RBAC
JWT tokens, bcrypt password hashing, lockout after 5 failures
"""
import pathlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .database import RevokedToken, User, get_db
from .config import read_secret

import os

def _load_secret_key() -> str:
    """SECRET_KEY must come from the environment (or mps_server/.env).
    The server refuses to start without it - no hardcoded fallback."""
    key = read_secret("SECRET_KEY")
    if not key:
        env_file = pathlib.Path(__file__).parent / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line.startswith("SECRET_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not key or key == "CHANGE_THIS_IN_PRODUCTION_USE_SECRETS_COMMAND":
        raise RuntimeError(
            "SECRET_KEY is not set. Run harden.sh to generate mps_server/.env, "
            "or export SECRET_KEY before starting the server."
        )
    if len(key) < 32:
        raise RuntimeError("SECRET_KEY must contain at least 32 characters")
    return key

SECRET_KEY  = _load_secret_key()
ALGORITHM   = "HS256"
TOKEN_EXPIRE_MINUTES = int(os.getenv("TOKEN_EXPIRE_MINUTES", "30"))
TOKEN_ISSUER = os.getenv("TOKEN_ISSUER", "mps-server")
TOKEN_AUDIENCE = os.getenv("TOKEN_AUDIENCE", "nanoclaw-client")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# A fixed bcrypt hash used to perform a constant-cost password verification when
# the supplied username does not exist. Without this, an unknown username
# returns faster than a known one and the timing difference leaks which
# usernames are valid (V-H5 anti-enumeration). The plaintext is irrelevant.
# Hardcoded (not computed at import) so importing this module never depends on
# the bcrypt backend being callable at import time. bcrypt hashes are portable
# across versions, so verification works regardless of the installed bcrypt.
_DUMMY_HASH = "$2b$12$i3rvghWRqe6KSFcGfYdhbOXE2kubQBHU0vpvG6cVFMTMdxsE6ONXm"

import pyotp


def verify_totp(secret: str, code: str) -> bool:
    """Verify a 6-digit TOTP code against the user's secret (±1 window)."""
    if not secret or not code:
        return False
    try:
        return pyotp.TOTP(secret).verify(str(code).strip(), valid_window=1)
    except Exception:
        return False
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

ROLES = {"volunteer", "vetter", "admin"}

# ── Password ──────────────────────────────────

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def validate_password_strength(password: str, username: str = "") -> None:
    """Apply a length-first password policy suitable for local accounts."""
    if len(password) < 12 or len(password) > 128:
        raise HTTPException(422, detail="Password must be between 12 and 128 characters")
    normalised = password.casefold()
    if username and username.casefold() in normalised:
        raise HTTPException(422, detail="Password must not contain the username")
    if normalised in {
        "password1234",
        "administrator",
        "changeme12345",
        "qwertyuiop12",
    }:
        raise HTTPException(422, detail="Password is too common")

# ── Token ─────────────────────────────────────

def create_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta or timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({
        "exp": expire,
        "iat": now,
        "nbf": now,
        "iss": TOKEN_ISSUER,
        "aud": TOKEN_AUDIENCE,
        "jti": str(uuid.uuid4()),
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            issuer=TOKEN_ISSUER,
            audience=TOKEN_AUDIENCE,
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def resolve_user_from_token(token: str, db: Session) -> User:
    """Resolve a token using the same checks for HTTP and WebSockets."""
    payload = decode_token(token)
    user_id: str = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    jti = payload.get("jti")
    if not jti:
        raise HTTPException(status_code=401, detail="Token is missing its identifier")
    if db.query(RevokedToken).filter(RevokedToken.jti == jti).first():
        raise HTTPException(status_code=401, detail="Token has been revoked")

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    if payload.get("role") != user.role:
        raise HTTPException(status_code=401, detail="Token role is stale")
    return user


import json as _json


def generate_recovery_codes(db, user) -> list[str]:
    """Generate 8 one-time recovery codes for the user. Stores bcrypt hashes."""
    import secrets as _secrets
    codes = [_secrets.token_urlsafe(12) for _ in range(8)]
    user.recovery_codes = _json.dumps([hash_password(c) for c in codes])
    db.commit()
    return codes


def _consume_recovery_code(db, user, code: str) -> bool:
    """Try to consume a recovery code. Returns True and deletes the code if valid."""
    if not user.recovery_codes:
        return False
    try:
        hashes = _json.loads(user.recovery_codes)
    except Exception:
        return False
    for i, h in enumerate(hashes):
        if verify_password(code, h):
            hashes.pop(i)
            user.recovery_codes = _json.dumps(hashes)
            db.commit()
            return True
    return False


# ── Login / lockout ───────────────────────────

def authenticate_user(db: Session, username: str, password: str,
                      totp_code: Optional[str] = None) -> User:
    user = db.query(User).filter(User.username == username).first()
    if not user:
        # Constant-cost verify so an unknown username is indistinguishable, by
        # timing, from a wrong password on a known username (V-H5).
        verify_password(password, _DUMMY_HASH)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Check lockout
    if user.locked_until and datetime.now(timezone.utc) < user.locked_until.replace(tzinfo=timezone.utc):
        remaining = (user.locked_until.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).seconds // 60
        raise HTTPException(status_code=403, detail=f"Account locked. Try again in {remaining} minutes.")

    if not verify_password(password, user.hashed_pw):
        user.failed_logins += 1
        if user.failed_logins >= 5:
            user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=30)
            db.commit()
            raise HTTPException(status_code=403, detail="Account locked for 30 minutes after 5 failed attempts.")
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Second factor: if the account has MFA enabled, a valid TOTP code is
    # mandatory. A failed code counts as a failed attempt (feeds lockout).
    # Gate on mfa_enabled, NOT on totp_secret presence, so that an interrupted
    # enrolment (pending_totp_secret set, mfa_enabled still False) does not
    # lock the user out before /mfa/activate is completed (V3-C1).
    if user.mfa_enabled:
        totp_ok = verify_totp(user.totp_secret, totp_code or "")
        if not totp_ok and totp_code:
            # Try recovery code path: one-time codes stored as bcrypt hashes.
            totp_ok = _consume_recovery_code(db, user, totp_code)
        if not totp_ok:
            user.failed_logins += 1
            db.commit()
            raise HTTPException(status_code=401, detail="Invalid or missing MFA code")

    # Success — reset failure count
    user.failed_logins = 0
    user.locked_until = None
    db.commit()
    return user

# ── Current user dependency ───────────────────

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    return resolve_user_from_token(token, db)

def require_role(*roles: str):
    """Dependency factory — require one of the given roles."""
    def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{current_user.role}' cannot access this endpoint"
            )
        return current_user
    return checker

require_volunteer = require_role("volunteer", "vetter", "admin")
require_vetter    = require_role("vetter", "admin")
require_admin     = require_role("admin")
