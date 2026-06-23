"""Tests for the signed release-record generator (2026-06-23 review)."""
import base64
import importlib.util
import json
import os

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GEN = os.path.join(_ROOT, "deploy", "release", "generate_release_record.py")
_spec = importlib.util.spec_from_file_location("gen_release_record", _GEN)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


class _Args:
    pip_audit = "pip-audit.json"
    sbom = "sbom-python.json"
    eval_result = "eval.json"
    require_eval = False
    out = "release-record.json"


def test_record_is_well_formed():
    rec = gen.build_record(_Args())
    expected_keys = {
        "schema_version", "kind", "commit", "model", "prompt_version",
        "prompt_sha256", "validator_version", "schema_revision",
        "policy_manifest_sha256", "dependency_audit", "sbom_sha256", "model_eval",
    }
    assert set(rec) == expected_keys
    assert rec["kind"] == "nanoclaw-release-record"
    # binds the real production provenance constants
    assert rec["validator_version"] and rec["prompt_sha256"] and rec["model"]
    assert rec["schema_revision"] == "20260621_03"


def test_canonical_bytes_are_deterministic():
    rec = gen.build_record(_Args())
    assert gen.canonical_bytes(rec) == gen.canonical_bytes(dict(reversed(list(rec.items()))))


def test_signature_round_trips(tmp_path, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    key_path = tmp_path / "release.key"
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    monkeypatch.setenv("RELEASE_SIGNING_KEY", str(key_path))

    rec = gen.build_record(_Args())
    body = gen.canonical_bytes(rec)
    sig_b64 = gen.sign(body)
    assert sig_b64
    # verifies against the public key (no exception == valid)
    key.public_key().verify(base64.b64decode(sig_b64), body)


def test_require_eval_fails_without_result(tmp_path):
    out = tmp_path / "rec.json"
    rc = gen.main(["--require-eval", "--out", str(out),
                   "--eval-result", str(tmp_path / "missing.json")])
    assert rc == 1  # release gate blocks a release with no model-eval evidence


def test_require_eval_passes_with_result(tmp_path):
    ev = tmp_path / "eval.json"
    ev.write_text(json.dumps({"result": "pass", "thresholds_met": True}))
    out = tmp_path / "rec.json"
    rc = gen.main(["--require-eval", "--out", str(out), "--eval-result", str(ev)])
    assert rc == 0
    saved = json.loads(out.read_text())
    assert saved["model_eval"] == "pass"
