"""Unit tests for the structured PII redactor and deterministic letter validator.
Run: python3 tests/test_redaction_validator.py
"""
import sys
sys.path.insert(0, ".")
from mps_server.services.redaction import scan, redact
from mps_server.services.validator import validate_letter

# Redaction: clean policy text has no findings
assert scan("CHAS Blue stated as $1,800; correct is $2,000") == []
# Dirty text: NRIC, phone, address, email, postal, case ref all caught
dirty = "Tan S1234567A Blk 99 #12-34 call 91234567 tan@x.com case-4567 postal 560123"
types = {t for t, _ in scan(dirty)}
for expected in ("nric_full", "phone", "address_unit", "address_floor", "email", "case_ref", "postal_code"):
    assert expected in types, f"missed {expected}: got {types}"
clean, _ = redact(dirty)
assert "S1234567A" not in clean and "91234567" not in clean
print("PASS: redaction (clean passes, all PII types caught + replaced)")

# Validator: good letter clean, bad letter flagged with a blocking full NRIC
assert validate_letter("Dear Sir, we request a review for our resident. Yours faithfully.") == []
ws = validate_letter("This will be approved within 3 days. You wrongly rejected S1234567A. Resolve immediately.")
codes = {w.code for w in ws}
sev = {w.severity for w in ws}
assert "full_nric" in codes and "block" in sev, codes
assert "outcome_promise" in codes and "deadline_demand" in codes and "blame_language" in codes
print("PASS: validator (clean passes, bad letter blocks on NRIC + warns)")

print("ALL TESTS PASS")
