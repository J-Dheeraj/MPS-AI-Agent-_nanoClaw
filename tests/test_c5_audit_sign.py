"""C5: audit checkpoint signing + verification."""
import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _write_keys(tmp_path):
    key = Ed25519PrivateKey.generate()
    priv = tmp_path / "audit-key.pem"
    priv.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()))
    pub = tmp_path / "audit-key.pub.pem"
    pub.write_bytes(key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo))
    return priv, pub


def _reset_key_cache():
    from mps_server.services import audit
    audit._signing_key_cache["loaded"] = False
    audit._signing_key_cache["key"] = None


def test_signed_checkpoint_line_verifies(tmp_path, monkeypatch):
    from mps_server.services import audit
    priv, pub = _write_keys(tmp_path)
    monkeypatch.setenv("AUDIT_CHECKPOINT_SIGNING_KEY", str(priv))
    monkeypatch.setenv("AUDIT_CHECKPOINT_PUBLIC_KEY", str(pub))
    monkeypatch.setenv("AUDIT_CHECKPOINT_FILE", str(tmp_path / "cp.log"))
    monkeypatch.delenv("AUDIT_CHECKPOINT_FORWARD_URL", raising=False)
    _reset_key_cache()

    class _Entry:
        id = "e1"
        entry_hash = "abc123"
    audit._write_checkpoint(None, _Entry())

    lines = (tmp_path / "cp.log").read_text().splitlines()
    assert len(lines) == 1
    assert len(lines[0].split("\t")) == 4              # ts, id, hash, signature
    assert audit.verify_checkpoint_line(lines[0]) is True


def test_tampered_signed_line_fails_verification(tmp_path, monkeypatch):
    from mps_server.services import audit
    priv, pub = _write_keys(tmp_path)
    monkeypatch.setenv("AUDIT_CHECKPOINT_SIGNING_KEY", str(priv))
    monkeypatch.setenv("AUDIT_CHECKPOINT_PUBLIC_KEY", str(pub))
    monkeypatch.setenv("AUDIT_CHECKPOINT_FILE", str(tmp_path / "cp.log"))
    _reset_key_cache()

    class _Entry:
        id = "e2"
        entry_hash = "goodhash"
    audit._write_checkpoint(None, _Entry())
    line = (tmp_path / "cp.log").read_text().splitlines()[0]
    ts, eid, _hash, sig = line.split("\t")
    forged = f"{ts}\t{eid}\tFORGEDHASH\t{sig}"
    assert audit.verify_checkpoint_line(forged) is False


def test_unsigned_line_rejected_when_pubkey_configured(tmp_path, monkeypatch):
    from mps_server.services import audit
    _priv, pub = _write_keys(tmp_path)
    monkeypatch.setenv("AUDIT_CHECKPOINT_PUBLIC_KEY", str(pub))
    _reset_key_cache()
    # A 3-field (unsigned) line is not acceptable once a public key is required.
    assert audit.verify_checkpoint_line("2026-06-20\te3\tsomehash") is False


def test_unsigned_mode_accepts_unsigned_lines(tmp_path, monkeypatch):
    from mps_server.services import audit
    monkeypatch.delenv("AUDIT_CHECKPOINT_PUBLIC_KEY", raising=False)
    _reset_key_cache()
    assert audit.verify_checkpoint_line("2026-06-20\te4\tsomehash") is True
