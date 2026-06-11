"""Factual-support / grounding check on generated letters (V-C2)."""

from mps_server.services.validator import (
    check_factual_support,
    validate_letter_grounded,
)

CTX = "[RULE hdb_rental] Public rental income ceiling is $1,500 per month."


def codes(warnings):
    return [(w.severity, w.code) for w in warnings]


def test_grounded_threshold_is_clean():
    text = "The household income ceiling for this scheme is $1,500 and the resident qualifies."
    assert check_factual_support(text, CTX) == []


def test_ungrounded_threshold_blocks():
    text = "The eligibility threshold is $2,000 per month for this subsidy."
    out = check_factual_support(text, CTX)
    assert ("block", "unsupported_policy_figure") in codes(out)


def test_resident_own_figure_not_flagged():
    # A figure that is the resident's own circumstance, not a policy claim.
    text = "The resident earns $1,200 each month and supports two children."
    assert check_factual_support(text, CTX) == []


def test_ungrounded_percentage_blocks():
    text = "Residents in this tier receive a 75% subsidy."
    out = check_factual_support(text, CTX)
    assert ("block", "unsupported_policy_figure") in codes(out)


def test_no_context_is_unverifiable_warn_not_block():
    text = "The eligibility threshold is $2,000 per month for this subsidy."
    out = check_factual_support(text, "")
    assert codes(out) == [("warn", "unverifiable_policy_figure")]


def test_grounded_wrapper_combines_privacy_and_support():
    # Full NRIC (privacy block) + ungrounded threshold (support block).
    text = "Resident S1234567A qualifies; the income ceiling is $9,999 here."
    out = validate_letter_grounded(text, CTX)
    found = codes(out)
    assert ("block", "full_nric") in found
    assert ("block", "unsupported_policy_figure") in found
