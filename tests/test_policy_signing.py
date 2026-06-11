"""Fail-closed signature verification for the policy manifest (V-C1)."""

import base64
import hashlib
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from mps_server.services.policy_store import PolicyStoreError, load_policy_context


def _write_rule(root):
    rule = {
        "schema_version": 1,
        "rule_id": "hdb-signed-rule",
        "agency": "HDB",
        "statement": "Signed HDB eligibility statement.",
        "source": {
            "title": "Housing policy",
            "url": "https://www.hdb.gov.sg/policy",
            "effective_date": "2026-01-01",
        },
        "review": {"reviewer_id": "reviewer-1"},
    }
    raw = (json.dumps(rule, indent=2, sort_keys=True) + "\n").encode()
    (root / "hdb-signed-rule.json").write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _write_manifest(root, sha, *, private_key, sign=True):
    manifest = {
        "schema_version": 1,
        "generated_at": "2026-06-11T00:00:00+00:00",
        "rules": [{"file": "hdb-signed-rule.json", "sha256": sha}],
    }
    mbytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    (root / "manifest.json").write_bytes(mbytes)
    if sign:
        sig = base64.b64encode(private_key.sign(mbytes)).decode("ascii")
        sidecar = {"schema_version": 1, "algorithm": "ed25519", "signature": sig}
        (root / "manifest.json.sig").write_text(json.dumps(sidecar), encoding="utf-8")


def _public_pem(tmp_path, private_key):
    pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    path = tmp_path / "pub.pem"
    path.write_bytes(pem)
    return path


def test_signed_manifest_loads(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    sha = _write_rule(tmp_path)
    _write_manifest(tmp_path, sha, private_key=key, sign=True)
    monkeypatch.setenv("POLICY_DIR", str(tmp_path))
    monkeypatch.setenv("POLICY_PUBLIC_KEY", str(_public_pem(tmp_path, key)))
    context, sources, _ = load_policy_context("HDB")
    assert "hdb-signed-rule" in context
    assert sources[0]["url"].startswith("https://www.hdb.gov.sg/")


def test_tampered_manifest_rejected(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    sha = _write_rule(tmp_path)
    _write_manifest(tmp_path, sha, private_key=key, sign=True)
    # Tamper with the manifest AFTER signing — signature must no longer verify.
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["rules"][0]["sha256"] = "0" * 64
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    monkeypatch.setenv("POLICY_DIR", str(tmp_path))
    monkeypatch.setenv("POLICY_PUBLIC_KEY", str(_public_pem(tmp_path, key)))
    with pytest.raises(PolicyStoreError, match="signature"):
        load_policy_context("HDB")


def test_unsigned_manifest_rejected_when_key_configured(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    sha = _write_rule(tmp_path)
    _write_manifest(tmp_path, sha, private_key=key, sign=False)
    monkeypatch.setenv("POLICY_DIR", str(tmp_path))
    monkeypatch.setenv("POLICY_PUBLIC_KEY", str(_public_pem(tmp_path, key)))
    with pytest.raises(PolicyStoreError, match="not signed"):
        load_policy_context("HDB")


def test_wrong_key_rejected(tmp_path, monkeypatch):
    signing_key = Ed25519PrivateKey.generate()
    other_key = Ed25519PrivateKey.generate()
    sha = _write_rule(tmp_path)
    _write_manifest(tmp_path, sha, private_key=signing_key, sign=True)
    monkeypatch.setenv("POLICY_DIR", str(tmp_path))
    # Verifier trusts a DIFFERENT key than the one that signed.
    monkeypatch.setenv("POLICY_PUBLIC_KEY", str(_public_pem(tmp_path, other_key)))
    with pytest.raises(PolicyStoreError, match="signature"):
        load_policy_context("HDB")
