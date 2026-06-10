"""
Deterministic post-draft letter validator — the "validate" stage of the
classify -> extract -> retrieve -> draft -> validate pipeline the review
asked for. This is deterministic (no LLM): it checks the generated draft
against the hard rules in the LETTER_SYSTEM prompt and returns structured
warnings the UI can surface to the volunteer/vetter before submission.

validate_letter(text) -> list[Warning]   (empty list = clean)
Each Warning is (severity, code, message). severity in {"block","warn"}.
"block" findings (e.g. a full NRIC) should prevent submission to MP.
"""
import re
from dataclasses import dataclass

_FULL_NRIC = re.compile(r"\b[STFGM]\d{7}[A-Z]\b", re.IGNORECASE)

# Phrases that promise an outcome or set a deadline for the agency — the
# prompt forbids both.
_OUTCOME_PROMISES = [
    r"\bwill be approved\b", r"\bguarantee[ds]?\b", r"\bwe assure you\b",
    r"\bmust be (?:approved|granted|resolved)\b", r"\bwill definitely\b",
]
_DEADLINE_DEMANDS = [
    r"\bwithin \d+ (?:days?|weeks?|hours?)\b", r"\bby (?:tomorrow|next week)\b",
    r"\bno later than\b", r"\bimmediately resolve\b",
]
# "Agency acted wrongly" language — prompt says use "request for review".
_BLAME = [r"\bwrongly (?:rejected|denied|decided)\b", r"\byour error\b",
          r"\bunfair(?:ly)?\b", r"\bmistake on your part\b"]

MAX_WORDS = 600   # ~one page


@dataclass
class Warning:
    severity: str   # "block" | "warn"
    code: str
    message: str

    def __iter__(self):
        return iter((self.severity, self.code, self.message))


def _any(patterns, text):
    return [p for p in patterns if re.search(p, text, re.IGNORECASE)]


def validate_letter(text: str) -> list:
    warnings = []
    if not text or not text.strip():
        return [Warning("block", "empty", "Letter is empty.")]

    if _FULL_NRIC.search(text):
        warnings.append(Warning(
            "block", "full_nric",
            "Letter contains what looks like a full NRIC. NRIC must be masked (S****567A)."))

    if _any(_OUTCOME_PROMISES, text):
        warnings.append(Warning(
            "warn", "outcome_promise",
            "Letter appears to promise an outcome. Letters should request, not guarantee."))

    if _any(_DEADLINE_DEMANDS, text):
        warnings.append(Warning(
            "warn", "deadline_demand",
            "Letter appears to set a deadline for the agency. Avoid demanding timeframes."))

    if _any(_BLAME, text):
        warnings.append(Warning(
            "warn", "blame_language",
            "Letter uses blame language. Use 'request for review' instead of asserting fault."))

    word_count = len(text.split())
    if word_count > MAX_WORDS:
        warnings.append(Warning(
            "warn", "too_long",
            f"Letter is {word_count} words (>{MAX_WORDS}). Aim for one page."))

    return warnings


if __name__ == "__main__":
    good = ("Dear Sir/Madam, I write on behalf of my resident to request a review "
            "of the CPF decision. The resident faces financial hardship. We would be "
            "grateful for your consideration. Yours faithfully, MP.")
    bad = ("Dear Sir, This will be approved within 3 days. You wrongly rejected "
           "resident S1234567A. Resolve immediately.")
    for label, t in [("good", good), ("bad", bad)]:
        ws = validate_letter(t)
        print(f"{label}: {[(w.severity, w.code) for w in ws] or 'clean'}")
