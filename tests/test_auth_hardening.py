"""Login rate limiting, anti-enumeration, and TOTP MFA (V-H5)."""

import pyotp
import pytest
from fastapi import HTTPException

from mps_server.database import Base, User
from mps_server import auth
from mps_server.auth import generate_recovery_codes
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


def _make_user(db, *, totp_secret=None, mfa_enabled=False):
    user = User(id="u1", username="alice", hashed_pw=auth.hash_password("CorrectHorse#1"),
                role="volunteer", full_name="Alice", totp_secret=totp_secret,
                mfa_enabled=mfa_enabled)
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


# ── TOTP MFA (two-phase enrolment, V3-C1) ────────────────────────────────
def test_login_without_mfa_when_disabled(db):
    _make_user(db)
    user = auth.authenticate_user(db, "alice", "CorrectHorse#1")
    assert user.username == "alice"


def _make_user_with_active_mfa(db):
    """Create a user with MFA fully activated (pending cleared, mfa_enabled=True)."""
    secret = pyotp.random_base32()
    user = _make_user(db, totp_secret=secret)
    user.mfa_enabled = True
    user.pending_totp_secret = None
    db.commit()
    return user, secret


def test_incomplete_enrolment_does_not_lock_user_out(db):
    """pending_totp_secret set but mfa_enabled=False must NOT trigger MFA check."""
    user = _make_user(db)
    user.pending_totp_secret = pyotp.random_base32()
    # mfa_enabled stays False
    db.commit()
    # Login without any code must succeed
    result = auth.authenticate_user(db, "alice", "CorrectHorse#1")
    assert result.username == "alice"


def test_mfa_required_when_enabled(db):
    _user, secret = _make_user_with_active_mfa(db)
    # No code -> rejected
    with pytest.raises(HTTPException) as e:
        auth.authenticate_user(db, "alice", "CorrectHorse#1")
    assert e.value.status_code == 401
    # Correct code -> accepted
    code = pyotp.TOTP(secret).now()
    user = auth.authenticate_user(db, "alice", "CorrectHorse#1", totp_code=code)
    assert user.username == "alice"


def test_mfa_wrong_code_rejected(db):
    _make_user_with_active_mfa(db)
    with pytest.raises(HTTPException) as e:
        auth.authenticate_user(db, "alice", "CorrectHorse#1", totp_code="000000")
    assert e.value.status_code == 401


def test_recovery_code_accepted_and_consumed(db):
    _user, _secret = _make_user_with_active_mfa(db)
    # Generate recovery codes
    codes = auth.generate_recovery_codes(db, _user)
    assert len(codes) == 8
    # Use one code
    first = codes[0]
    result = auth.authenticate_user(db, "alice", "CorrectHorse#1", totp_code=first)
    assert result.username == "alice"
    # Using the same code again must fail (consumed)
    with pytest.raises(HTTPException) as e:
        auth.authenticate_user(db, "alice", "CorrectHorse#1", totp_code=first)
    assert e.value.status_code == 401
