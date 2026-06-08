# Letter knowledge base & prompt guidance

Source: the official "MPS AI AGENT (Tauri)" project proposal (sections 9-11, 13.3).
Wire this directly into nanoClaw's system prompt / RAG templates for letter
generation -- it is the contract for what "correct" output looks like, and the
basis for the agency-specific examples Person 2 is preparing.

## 1. Required letter structure (10 parts)

The AI must be guided to follow this structure every time:

1. **Date**
2. **Agency / Recipient**
3. **Subject heading** -- `RE: Appeal for [Type of Assistance] for [Petitioner / Case Reference]`
4. **Opening** -- state that the letter is written to appeal on behalf of the petitioner
5. **Case background** -- briefly explain the petitioner's situation
6. **Reason for appeal** -- explain why assistance, reconsideration, or review is needed
7. **Supporting circumstances** -- relevant hardship, medical, family, employment, housing, or financial context
8. **Specific request** -- clearly state what the agency is being asked to consider
9. **Closing** -- thank the agency and request kind consideration
10. **Sign-off** -- "Yours faithfully" / "Yours sincerely"

A draft missing (8) "specific request" or (3) "subject heading" should be treated
as incomplete -- these are the two failure modes the proposal calls out by name
("missing request", and unclear RE: lines).

## 2. Agency-specific guidance

| Agency | The draft should cover |
|---|---|
| **HDB** | Housing issue, rental/mortgage difficulty, flat eligibility, request for review or assistance |
| **CPF** | CPF withdrawal issue, financial hardship, medical grounds, request for reconsideration |
| **MSF** | Family difficulty, ComCare assistance, household income issue, request for social support |
| **MOM** | Employment issue, salary dispute, work pass issue, request for investigation or assistance |
| **ICA** | Visit pass, PR/citizenship-related issue, immigration appeal, family circumstances |
| **MOH** | Medical appointment, subsidy, healthcare cost, treatment access, request for assistance |

These six map 1:1 to the `AGENCIES` constant in `src/views/caseForm.js` and
`src/views/feedbackView.js` -- keep them in sync.

## 3. Tone and style rules

The AI should write letters that are: formal, respectful, clear, concise,
compassionate, neutral, and agency-appropriate.

The AI should **not**: be overly emotional, be too casual, make unsupported
claims, exaggerate the petitioner's situation, or include unnecessary personal
information.

> Example rule (quote this in the system prompt verbatim):
> "The AI should not exaggerate the petitioner's situation. It should present
> the facts respectfully and clearly, then make a specific request to the agency."

## 4. Letter knowledge base contents (for RAG / few-shot context)

Per section 8.6, the knowledge base that guides generation should include:
approved sample letters, standard letter templates, common opening/closing
paragraphs, agency-specific formats, appeal wording examples, do-and-don't
rules, tone guidelines, and paired examples of weak drafts vs. improved drafts.
Person 2's deliverables (letter template library, agency-specific drafting
guide, before/after examples) are the source material for this -- store them
under `docs/` or a `knowledge/` directory and load them into nanoClaw's
prompt-construction step.

## 5. Hermes feedback -- what is safe vs. unsafe to send

This is the data-protection contract for `logFeedback` in `src/api/client.js`
and `feedbackView.js`. **Never** let raw case notes, full NRIC, full name,
phone number, home address, or exact financial/medical details reach Hermes --
only the anonymised *learning point*.

| Unsafe (never send) | Safe (send instead) |
|---|---|
| "Mr Tan, NRIC S1234567A, lost his job and cannot pay HDB loan." | "For HDB financial hardship appeals, include employment loss, repayment difficulty, and request for review." |
| "Mdm Lim at Block 123 needs MSF assistance because her husband left." | "For MSF family hardship appeals, explain household difficulty clearly without unnecessary personal identifiers." |
| "Child has specific medical condition and needs MOH subsidy urgently." | "For MOH appeals, include healthcare cost difficulty and the specific assistance requested." |

General correction-pattern examples to seed the feedback UI / Hermes corpus:

| AI draft issue | Vetter correction | Hermes learning point |
|---|---|---|
| Letter too casual | Vetter makes it more formal | Use formal agency-facing tone |
| Missing request | Vetter adds specific appeal request | Always include a clear request |
| Too much detail | Vetter shortens background | Keep background concise |
| Sensitive data included | Vetter removes unnecessary identifiers | Avoid unnecessary personal data |
| Weak closing | Vetter adds respectful closing | End with polite request for consideration |

`feedbackView.js` should ideally validate/nudge submissions toward this
"learning point" shape (agency + issue + correction, no identifiers) before
they ever leave the volunteer/vetter's machine -- consider adding a
client-side NRIC/phone/address regex check alongside the existing
`maskNric()` helper in `caseForm.js`.
