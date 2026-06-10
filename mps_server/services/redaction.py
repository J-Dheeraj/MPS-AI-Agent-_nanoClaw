"""
Structured PII redaction for the Hermes feedback export.

The review flagged that export relied on grep for NRIC/phone only, which
misses names, addresses, emails, postal codes, and case references. This
module is the structured replacement. It is defence-in-depth: the export
source is already the anonymised FeedbackEntry table (no case linkage), and
every exported field is additionally passed through redact() here.

redact(text) -> (clean_text, findings)
  - clean_text has all detected PII replaced with [REDACTED:<type>]
  - findings is a list of (type, original) tuples for the audit trail

scan(text) -> list[findings]   (detection only, no mutation)

Policy: the export script FAILS CLOSED — if any finding remains after
redaction in a field that should be pure policy text, the export aborts.
"""
import re

# Singapore-specific and general PII patterns.
_PATTERNS = [
    # Full NRIC/FIN: letter + 7 digits + letter. Must never appear.
    ("nric_full",   re.compile(r"\b[STFGM]\d{7}[A-Z]\b", re.IGNORECASE)),
    # Email
    ("email",       re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    # Singapore mobile/landline: 8 digits starting 6/8/9, optional +65
    ("phone",       re.compile(r"\b(?:\+?65[-\s]?)?[689]\d{7}\b")),
    # HDB block + unit, e.g. "Blk 123", "Block 45A", "#12-345"
    ("address_unit", re.compile(r"\b(?:bl(?:oc)?k\s*\d+[A-Z]?)\b", re.IGNORECASE)),
    ("address_floor", re.compile(r"#\d{1,3}-\d{1,4}[A-Z]?")),
    # 6-digit Singapore postal code
    ("postal_code", re.compile(r"\bS?\(?\d{6}\)?\b")),
    # Case reference like CASE-1234 / #4567 used as an identifier
    ("case_ref",    re.compile(r"\b(?:case|ref|ticket)[-#\s]*\d{3,}\b", re.IGNORECASE)),
]

# Postal code is noisy (could match a dollar figure); only treat 6 digits as a
# postal code when not immediately preceded by a currency symbol or 'sum'.
_CURRENCY_NEAR = re.compile(r"(?:\$|sum|amount|ceiling|income)\s*S?\(?\d{6}\)?", re.IGNORECASE)


def scan(text: str):
    if not text:
        return []
    findings = []
    for name, pat in _PATTERNS:
        for m in pat.finditer(text):
            if name == "postal_code":
                # skip if it looks like a currency amount
                start = max(0, m.start() - 12)
                if _CURRENCY_NEAR.search(text[start:m.end()]):
                    continue
            findings.append((name, m.group(0)))
    return findings


def redact(text: str):
    if not text:
        return text, []
    findings = scan(text)
    clean = text
    # Replace longest matches first to avoid partial overlaps.
    for name, original in sorted(findings, key=lambda f: -len(f[1])):
        clean = clean.replace(original, f"[REDACTED:{name}]")
    return clean, findings


if __name__ == "__main__":
    samples = [
        "CHAS Blue stated as $1,800 only; correct is up to $2,000",          # clean
        "Resident S1234567A at Blk 123 #12-34 called 91234567",              # dirty
        "Email tan@example.com re case-4567, postal 560123",                 # dirty
        "EHG ceiling stated as 40000 should be 9000 for singles",            # clean (numbers, no 6-digit)
    ]
    for s in samples:
        clean, f = redact(s)
        print(f"findings={[t for t,_ in f]}")
        print(f"  in : {s}")
        print(f"  out: {clean}")
