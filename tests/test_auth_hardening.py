"""Login rate limiting, anti-enumeration, and TOTP MFA (V-H5)."""

import pyotp
import pytest
from fastapi import HTTPException

from mps_server.database import Base, User
from mps_server import auth
from mps_server.services.ratelimit import SlidingWindowLimiter, RateLimitExceeded


@pytest.fixture
def db(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{tmp_path / 'auth.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _make_user(db, *, totp_secret=None):
    user = User(id="u1", username="alice", hashed_pw=auth.hash_password("CorrectHorse#1"),
                role="volunteer", full_name="Alice", totp_secret=totp_secret)
    db.add(user)
    db.commit()
    return user


# ── rate limiter ──────────────────────────────────────────────────────────
def test_limiter_allows_then_blocks():
    lim = SlidingWindowLimiter(max_events=3, window_seconds=60)
    for _ in range(3):
        lim.check("k")
    with pytest.raises(RateLimitExceeded):
        lim.check("k")


def test_limiter_reset_clears():
    lim = SlidingWindowLimiter(max_events=1, window_seconds=60)
    lim.check("k")
    lim.reset("k")
    lim.check("k")  # no raise


# ── anti-enumeration ──────────────────────────────────────────────────────
def test_unknown_user_and_wrong_password_both_401(db):
    _make_user(db)
    with pytest.raises(HTTPException) as e1:
        auth.authenticate_user(db, "nobody", "whatever")
    with pytest.raises(HTTPException) as e2:
        auth.authenticate_user(db, "alice", "wrong-password")
    assert e1.value.status_code == 401
    assert e2.value.status_code == 401
    assert e1.value.detail == e2.value.detail  # identical message


# ── TOTP MFA ──────────────────────────────────────────────────────────────
def test_login_without_mfa_when_disabled(db):
    _make_user(db)
    user = auth.authenticate_user(db, "alice", "CorrectHorse#1")
    assert user.username == "alice"


def test_mfa_required_when_enabled(db):
    secret = pyotp.random_base32()
    _make_user(db, totp_secret=secret)
    # No code -> rejected
    with pytest.raises(HTTPException) as e:
        auth.authenticate_user(db, "alice", "CorrectHorse#1")
    assert e.value.status_code == 401
    # Correct code -> accepted
    code = pyotp.TOTP(secret).now()
    user = auth.authenticate_user(db, "alice", "CorrectHorse#1", totp_code=code)
    assert user.username == "alice"


def test_mfa_wrong_code_rejected(db):
    secret = pyotp.random_base32()
    _make_user(db, totp_secret=secret)
    with pytest.raises(HTTPException) as e:
        auth.authenticate_user(db, "alice", "CorrectHorse#1", totp_code="000000")
    assert e.value.status_code == 401
