from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from ..database import User, get_db
from ..auth import authenticate_user, create_token, hash_password, get_current_user, require_admin, oauth2_scheme, TOKEN_EXPIRE_MINUTES
from ..services.audit import log_event
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
    db: Session = Depends(get_db),
):
    user = authenticate_user(db, form.username, form.password)
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
    existing = db.query(User).filter(User.username == req.username).first()
    if existing:
        raise HTTPException(400, "Username already exists")
    user = User(
        username=req.username,
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
    if not req.password or len(req.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
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
    if len(req.new_password) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")
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
