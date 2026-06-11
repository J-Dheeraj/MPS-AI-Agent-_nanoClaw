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


# ── V3-C5: age, duration and count claims ────────────────────────────────────

CTX_AGE = (
    '[RULE hdb_senior] Applicants must be aged 55 and above. '
    'Applications are processed within 21 days. '
    'Minimum occupation period is 5 years.'
)


def test_grounded_age_claim_is_clean():
    text = 'To qualify, the applicant must be aged 55 and above.'
    assert check_factual_support(text, CTX_AGE) == []


def test_ungrounded_age_claim_blocks():
    text = 'To be eligible, applicants must be aged 60 and above.'
    out = check_factual_support(text, CTX_AGE)
    assert ('block', 'unsupported_policy_figure') in codes(out)


def test_ungrounded_duration_claim_blocks():
    text = 'Under the eligibility criteria, applications are processed within 3 days.'
    out = check_factual_support(text, CTX_AGE)
    assert ('block', 'unsupported_policy_figure') in codes(out)


def test_grounded_duration_claim_is_clean():
    text = 'Eligible applications are processed within 21 days.'
    assert check_factual_support(text, CTX_AGE) == []


def test_ungrounded_years_claim_blocks():
    text = 'The minimum occupation period required to qualify is 10 years.'
    out = check_factual_support(text, CTX_AGE)
    assert ('block', 'unsupported_policy_figure') in codes(out)


def test_plain_number_outside_claim_sentence_not_flagged():
    text = 'The resident has lived there for 12 years and has 3 children.'
    assert check_factual_support(text, CTX_AGE) == []
