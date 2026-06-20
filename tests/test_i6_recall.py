"""I6: curated policy tags + measured retrieval recall."""
import hashlib
import json

import pytest
from datetime import date


@pytest.fixture
def policy_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("POLICY_DIR", str(tmp_path))
    monkeypatch.delenv("POLICY_PUBLIC_KEY", raising=False)
    return tmp_path


def _rule(policy_dir, rule_id, statement, tags=None):
    rule = {
        "schema_version": 1, "rule_id": rule_id, "agency": "HDB",
        "statement": statement,
        "source": {"title": f"R{rule_id}", "url": "https://www.hdb.gov.sg/x",
                   "effective_date": "2024-01-01"},
    }
    if tags:
        rule["tags"] = tags
    raw = json.dumps(rule, sort_keys=True).encode()
    (policy_dir / f"{rule_id}.json").write_bytes(raw)
    return {"file": f"{rule_id}.json", "sha256": hashlib.sha256(raw).hexdigest()}


def _manifest(policy_dir, entries):
    (policy_dir / "manifest.json").write_text(json.dumps(
        {"schema_version": 1, "generated_at": date.today().isoformat(), "rules": entries}))


def test_tagged_rule_outranks_incidental_word_match(policy_dir):
    from mps_server.services.policy_store import load_policy_context
    # R_INC shares incidental words; R_TAG is curated-tagged for the topic.
    e1 = _rule(policy_dir, "R_INC",
               "The resident should submit a request for review of the appeal.")
    e2 = _rule(policy_dir, "R_TAG",
               "Rental flats are allocated by ballot.", tags=["rental", "eviction"])
    _manifest(policy_dir, [e1, e2])
    _, sources, _ = load_policy_context(
        "HDB", case_text="Resident facing eviction from rental flat needs review")
    assert sources[0]["rule_id"] == "R_TAG"  # tag match wins over word overlap


def test_recall_at_1_on_labelled_cases(policy_dir):
    """Measured recall@1: each labelled case must retrieve its tagged rule first."""
    from mps_server.services.policy_store import load_policy_context
    entries = [
        _rule(policy_dir, "HDB_RENTAL", "Public rental income ceiling rules.",
              tags=["rental", "income", "ceiling"]),
        _rule(policy_dir, "HDB_RESALE", "Resale levy and grant eligibility.",
              tags=["resale", "levy", "grant"]),
        _rule(policy_dir, "HDB_PARKING", "Season parking application terms.",
              tags=["parking", "season"]),
    ]
    _manifest(policy_dir, entries)

    labelled = [
        ("My rental flat income ceiling assessment was rejected", "HDB_RENTAL"),
        ("Question about the resale levy and grant I qualify for", "HDB_RESALE"),
        ("I need a season parking permit for my car", "HDB_PARKING"),
    ]
    hits = 0
    for case_text, expected in labelled:
        _, sources, _ = load_policy_context("HDB", case_text=case_text)
        if sources and sources[0]["rule_id"] == expected:
            hits += 1
    recall_at_1 = hits / len(labelled)
    assert recall_at_1 == 1.0, f"recall@1 was {recall_at_1}"


def test_untagged_rules_still_work(policy_dir):
    from mps_server.services.policy_store import load_policy_context
    e = _rule(policy_dir, "R_PLAIN", "Some HDB rule without tags.")
    _manifest(policy_dir, [e])
    _, sources, _ = load_policy_context("HDB", case_text="anything")
    assert sources[0]["rule_id"] == "R_PLAIN"
