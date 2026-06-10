import hashlib
import json

import pytest

from mps_server.services.policy_store import PolicyStoreError, load_policy_context


def write_policy_store(root):
    rule = {
        "schema_version": 1,
        "rule_id": "hdb-test-rule",
        "agency": "HDB",
        "statement": "Use the reviewed HDB eligibility statement.",
        "source": {
            "title": "Housing policy",
            "url": "https://www.hdb.gov.sg/policy",
            "effective_date": "2026-01-01",
        },
        "review": {"reviewer_id": "reviewer-1"},
    }
    raw = (json.dumps(rule, indent=2, sort_keys=True) + "\n").encode()
    (root / "hdb-test-rule.json").write_bytes(raw)
    manifest = {
        "schema_version": 1,
        "generated_at": "2026-06-10T00:00:00+00:00",
        "rules": [
            {
                "file": "hdb-test-rule.json",
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        ],
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_policy_store_loads_only_manifested_rules(tmp_path, monkeypatch):
    write_policy_store(tmp_path)
    monkeypatch.setenv("POLICY_DIR", str(tmp_path))
    context, sources, version = load_policy_context("HDB")
    assert "hdb-test-rule" in context
    assert sources[0]["url"].startswith("https://www.hdb.gov.sg/")
    assert version


def test_policy_store_fails_closed_on_tampering(tmp_path, monkeypatch):
    write_policy_store(tmp_path)
    monkeypatch.setenv("POLICY_DIR", str(tmp_path))
    (tmp_path / "hdb-test-rule.json").write_text("{}", encoding="utf-8")
    with pytest.raises(PolicyStoreError, match="hash mismatch"):
        load_policy_context("HDB")
