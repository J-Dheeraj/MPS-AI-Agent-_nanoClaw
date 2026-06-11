from datetime import timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from ..database import User, get_db
from ..auth import authenticate_user, create_token, hash_password, get_current_user, require_admin, oauth2_scheme, TOKEN_EXPIRE_MINUTES, validate_password_strength
from ..services.audit import log_event
from ..services.ratelimit import (
    login_ip_limiter, login_user_limiter, RateLimitExceeded,
)
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["auth"])

class RegisterRequest(BaseModel):
    username:  str
    password:  str
    full_name: str
    role:      str  # volunteer / vetter / admin

class TokenResponse(BaseModel):
    access_token: str
    token_type:   str
    role:         str
    full_name:    str
    user_id:      str

@router.post("/login", response_model=TokenResponse)
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    totp: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
):
    # Rate limit by client IP and by username (V-H5). The IP limit throttles an
    # attacker before they can drive a known account into lockout (lockout DoS);
    # the per-username limit bounds credential stuffing against one account.
    client_ip = request.client.host if request.client else "unknown"
    try:
        login_ip_limiter.check(client_ip)
        login_user_limiter.check(form.username.lower())
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(exc.retry_after)},
        )

    user = authenticate_user(db, form.username, form.password, totp_code=totp)
    # Successful login clears the per-username counter so a genuine user is not
    # throttled by their own earlier typos.
    login_user_limiter.reset(form.username.lower())
    token = create_token(
        {"sub": user.id, "role": user.role},
        expires_delta=timedelta(minutes=TOKEN_EXPIRE_MINUTES),
    )
    log_event(db, "login", user_id=user.id, role=user.role,
              client_ip=request.client.host if request.client else None)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        role=user.role,
        full_name=user.full_name,
        user_id=user.id,
    )

@router.post("/logout")
def logout(request: Request,
           token: str = Depends(oauth2_scheme),
           current_user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    # Revoke this token by storing its jti so it can no longer authenticate.
    from ..auth import decode_token
    from ..database import RevokedToken
    try:
        jti = decode_token(token).get("jti")
        if jti and not db.query(RevokedToken).filter(RevokedToken.jti == jti).first():
            db.add(RevokedToken(jti=jti, user_id=current_user.id))
            db.commit()
    except Exception:
        pass
    log_event(db, "logout", user_id=current_user.id, role=current_user.role,
              client_ip=request.client.host if request.client else None)
    return {"message": "Logged out"}

@router.post("/register")
def register(
    req: RegisterRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin only — create new user accounts (enforced by require_admin)."""
    if req.role not in ("volunteer", "vetter", "admin"):
        raise HTTPException(400, "Invalid role")
    username = req.username.strip().lower()
    if len(username) < 3 or len(username) > 64:
        raise HTTPException(422, "Username must be between 3 and 64 characters")
    validate_password_strength(req.password, username)
    if not req.full_name.strip() or len(req.full_name.strip()) > 200:
        raise HTTPException(422, "Full name must be between 1 and 200 characters")
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        raise HTTPException(400, "Username already exists")
    user = User(
        username=username,
        hashed_pw=hash_password(req.password),
        full_name=req.full_name,
        role=req.role,
    )
    db.add(user)
    db.commit()
    return {"user_id": user.id, "username": user.username, "role": user.role}

class SignupRequest(BaseModel):
    username:  str
    password:  str
    full_name: str

@router.post("/signup")
def signup(req: SignupRequest, request: Request, db: Session = Depends(get_db)):
    """Self-registration — DISABLED by default. MPS onboarding is done by an
    admin via /auth/register. Set ALLOW_SIGNUP=1 only if a formal public
    onboarding flow is genuinely required. Creates a volunteer account."""
    import os as _os
    if _os.getenv("ALLOW_SIGNUP", "").lower() not in ("1", "true", "yes"):
        raise HTTPException(403, "Self-registration is disabled. Ask an admin to create your account.")
    username = req.username.strip().lower()
    if not username or len(username) < 3:
        raise HTTPException(400, "Username must be at least 3 characters")
    validate_password_strength(req.password, username)
    if not req.full_name.strip():
        raise HTTPException(400, "Full name is required")
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        raise HTTPException(400, "Username already taken — choose another")
    user = User(
        username=username,
        hashed_pw=hash_password(req.password),
        full_name=req.full_name.strip(),
        role="volunteer",
    )
    db.add(user)
    db.commit()
    log_event(db, "signup", user_id=user.id, role="volunteer",
              client_ip=request.client.host if request.client else None,
              details={"username": username})
    return {"user_id": user.id, "username": user.username, "role": user.role,
            "message": "Account created — you can now log in"}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password:     str

class ChangeUsernameRequest(BaseModel):
    current_password: str
    new_username:     str


@router.put("/change-password")
def change_password(
    req: ChangePasswordRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Any authenticated user can change their own password.
    Requires current password for confirmation.
    """
    from ..auth import verify_password
    if not verify_password(req.current_password, current_user.hashed_pw):
        raise HTTPException(400, "Current password is incorrect")
    validate_password_strength(req.new_password, current_user.username)
    if req.new_password == req.current_password:
        raise HTTPException(400, "New password must differ from current password")
    current_user.hashed_pw = hash_password(req.new_password)
    db.commit()
    log_event(db, "password_changed", user_id=current_user.id, role=current_user.role,
              client_ip=request.client.host if request.client else None)
    return {"message": "Password changed successfully"}


@router.put("/change-username")
def change_username(
    req: ChangeUsernameRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Any authenticated user can change their own username.
    Requires current password for confirmation.
    """
    from ..auth import verify_password
    if not verify_password(req.current_password, current_user.hashed_pw):
        raise HTTPException(400, "Current password is incorrect")
    new_username = req.new_username.strip().lower()
    if len(new_username) < 3:
        raise HTTPException(400, "Username must be at least 3 characters")
    if new_username == current_user.username:
        raise HTTPException(400, "New username must differ from current username")
    taken = db.query(User).filter(
        User.username == new_username,
        User.id != current_user.id,
    ).first()
    if taken:
        raise HTTPException(400, "Username already taken — choose another")
    old_username = current_user.username
    current_user.username = new_username
    db.commit()
    log_event(db, "username_changed", user_id=current_user.id, role=current_user.role,
              client_ip=request.client.host if request.client else None,
              details={"old_username": old_username, "new_username": new_username})
    return {"message": "Username changed successfully", "new_username": new_username}


# ── Multi-factor authentication (TOTP) ───────────────────────────────────────
import pyotp


class MfaActivateRequest(BaseModel):
    code: str


@router.post("/mfa/enroll")
def mfa_enroll(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Begin TOTP enrolment: generate a secret and return the provisioning URI.
    The secret is stored but MFA is only enforced once /mfa/activate confirms a
    valid code, so a half-finished enrolment cannot lock the user out."""
    if current_user.totp_secret:
        raise HTTPException(409, "MFA is already enabled for this account")
    secret = pyotp.random_base32()
    current_user.totp_secret = secret
    db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(
        name=current_user.username, issuer_name="MPS AI Agent"
    )
    return {"secret": secret, "otpauth_uri": uri,
            "note": "Scan in an authenticator app, then POST the 6-digit code to /auth/mfa/activate"}


@router.post("/mfa/activate")
def mfa_activate(req: MfaActivateRequest, request: Request,
                 current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Confirm enrolment by verifying a code against the pending secret."""
    from ..auth import verify_totp
    if not current_user.totp_secret:
        raise HTTPException(400, "Start enrolment via /auth/mfa/enroll first")
    if not verify_totp(current_user.totp_secret, req.code):
        raise HTTPException(401, "Invalid MFA code")
    log_event(db, "mfa_activated", user_id=current_user.id, role=current_user.role,
              client_ip=request.client.host if request.client else None)
    return {"status": "mfa_enabled"}


@router.post("/mfa/disable")
def mfa_disable(req: MfaActivateRequest, request: Request,
                current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Disable MFA. Requires a current valid code so a stolen session cannot
    silently remove the second factor."""
    from ..auth import verify_totp
    if not current_user.totp_secret:
        raise HTTPException(400, "MFA is not enabled")
    if not verify_totp(current_user.totp_secret, req.code):
        raise HTTPException(401, "Invalid MFA code")
    current_user.totp_secret = None
    db.commit()
    log_event(db, "mfa_disabled", user_id=current_user.id, role=current_user.role,
              client_ip=request.client.host if request.client else None)
    return {"status": "mfa_disabled"}
