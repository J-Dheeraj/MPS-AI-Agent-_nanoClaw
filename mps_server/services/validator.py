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

VALIDATOR_VERSION = "2026-06-11"


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


# ── Factual-support / grounding check (V-C2) ─────────────────────────────────
# A generated letter must not assert a policy threshold figure that is not
# present in the approved policy context retrieved for the case. This catches
# the harmful case the review named: a hallucinated or stale eligibility
# threshold (e.g. an income ceiling) that would otherwise pass privacy checks
# and be frozen. It is deliberately scoped to figures that appear *as policy
# claims* — i.e. near eligibility/threshold language — so a resident's own
# circumstance figure (their income, flat number, household size) is not
# flagged. It is deterministic: no second model call.

# A sentence is treated as a policy claim only if it contains threshold language.
_POLICY_CLAIM_KEYWORDS = re.compile(
    r"\b(threshold|eligib\w*|qualif\w*|income (?:ceiling|limit|cap)|"
    r"ceiling|cap|caps|capped|maximum|up to|must not exceed|cannot exceed|"
    r"not exceed|criteria|quota|subsid\w*|tier|limit)\b",
    re.IGNORECASE,
)
_MONEY = re.compile(r"\$\s?\d[\d,]*(?:\.\d{1,2})?")
_PERCENT = re.compile(r"\d+(?:\.\d+)?\s?%")
# V3-C5: age and duration figures, e.g. "aged 55", "within 21 days", "5 years".
# Normalised to digits+unit (aged N -> "Nyears") so "aged 55" grounds
# "55 years" and vice versa.
_AGE_DURATION = re.compile(
    r"(?:\b(?:aged?|age of)\s+(\d{1,3})\b|\b(\d{1,3})\s+(years?|months?|weeks?|days?)\b)",
    re.IGNORECASE,
)


def _norm_age_duration(m: "re.Match") -> str:
    if m.group(1):  # "aged N" form — treat as years
        return f"{m.group(1)}years"
    unit = m.group(3).lower().rstrip("s") + "s"
    return f"{m.group(2)}{unit}"

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _norm_figure(raw: str) -> str:
    return re.sub(r"[\s,$]", "", raw).rstrip(".")


def _grounded_figures(policy_context: str) -> set:
    figures = set()
    for m in _MONEY.finditer(policy_context):
        figures.add(_norm_figure(m.group()))
    for m in _PERCENT.finditer(policy_context):
        figures.add(_norm_figure(m.group()))
    for m in _AGE_DURATION.finditer(policy_context):
        figures.add(_norm_age_duration(m))
    return figures


def check_factual_support(text: str, policy_context: str) -> list:
    """Flag policy-threshold figures in the letter not grounded in policy_context.

    Returns a list[Warning]. When policy_context is non-empty an ungrounded
    threshold figure is a 'block'; when no policy context was available the
    same figure is an unverifiable 'warn' (we cannot prove or disprove it).
    """
    if not text or not text.strip():
        return []
    grounded = _grounded_figures(policy_context or "")
    have_context = bool((policy_context or "").strip())
    warnings = []
    seen = set()
    for sentence in _SENTENCE_SPLIT.split(text):
        if not _POLICY_CLAIM_KEYWORDS.search(sentence):
            continue
        matches = [(_norm_figure(m.group()), m.group()) for pat in (_MONEY, _PERCENT)
                   for m in pat.finditer(sentence)]
        matches += [(_norm_age_duration(m), m.group()) for m in _AGE_DURATION.finditer(sentence)]
        for fig, raw in matches:
                if fig in grounded or fig in seen:
                    continue
                seen.add(fig)
                if have_context:
                    warnings.append(Warning(
                        "block", "unsupported_policy_figure",
                        f"Letter states policy figure '{raw.strip()}' that is not "
                        f"in the approved policy context for this case. Remove it or "
                        f"cite an approved policy rule."))
                else:
                    warnings.append(Warning(
                        "warn", "unverifiable_policy_figure",
                        f"Letter states policy figure '{raw.strip()}' but no approved "
                        f"policy context was available to verify it."))
    return warnings


def validate_letter_grounded(text: str, policy_context: str = "") -> list:
    """validate_letter + factual-support check. Use this at draft and at the
    final vetter-submit gate so a hallucinated threshold cannot be frozen."""
    return validate_letter(text) + check_factual_support(text, policy_context)


if __name__ == "__main__":
    good = ("Dear Sir/Madam, I write on behalf of my resident to request a review "
            "of the CPF decision. The resident faces financial hardship. We would be "
            "grateful for your consideration. Yours faithfully, MP.")
    bad = ("Dear Sir, This will be approved within 3 days. You wrongly rejected "
           "resident S1234567A. Resolve immediately.")
    for label, t in [("good", good), ("bad", bad)]:
        ws = validate_letter(t)
        print(f"{label}: {[(w.severity, w.code) for w in ws] or 'clean'}")
