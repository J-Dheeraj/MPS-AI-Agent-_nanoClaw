// Vetter view -- replaces mps_client/widgets/vetter_view.py.
//
// Per the README, the vetter OWNS the final text:
//   "The vetter edits the letter directly in the GTK4 client and clicks
//    Submit to MP -- this saves final_content, freezes the letter
//    (is_frozen=True), and marks the case pending_mp."
//
// This is the most safety-critical screen in the app -- a frozen letter
// cannot be edited afterwards (server returns 403 per the security table),
// and it's the vetter's text the MP will see and may send under their name.
// Always confirm before the irreversible "Submit to MP" action.

import { vetterSubmitToMp, returnCaseToVolunteer, getVetterQueue } from "../api/client";

export async function renderVetterQueue(container, { onOpenCase }) {
  container.innerHTML = "<div class='toolbar'><strong>Vetting queue</strong></div>";
  const list = document.createElement("div");
  container.appendChild(list);

  let cases;
  try {
    const payload = await getVetterQueue();
    cases = payload?.cases ?? [];
  } catch (e) {
    list.innerHTML = `<div class="error-banner" style="margin:16px">Couldn't load queue: ${e.message ?? e}</div>`;
    return;
  }

  if (!cases.length) {
    list.innerHTML = `<p class="muted" style="padding:16px">Nothing waiting for review.</p>`;
    return;
  }

  for (const c of cases) {
    const row = document.createElement("div");
    row.className = "case-row";
    row.innerHTML = `<strong>${c.case_type}</strong> <span class="badge ${c.status}">${c.status}</span>
                     <div class="muted" style="font-size:12px">${c.agency} • ${c.resident_name ?? "resident"} • ${c.urgency}</div>`;
    row.addEventListener("click", () => onOpenCase(c));
    list.appendChild(row);
  }
}

export function renderVetterCaseReview(container, { caseRecord, onResolved }) {
  container.innerHTML = "";

  const wrap = document.createElement("div");
  wrap.innerHTML = `
    <div class="toolbar">
      <strong>${caseRecord.case_type}</strong>
      <span class="badge ${caseRecord.status}">${caseRecord.status}</span>
      <span class="muted">${caseRecord.agency} • ${caseRecord.resident_name ?? ""}</span>
    </div>
    <div style="padding:16px">
      <p class="muted" style="font-size:13px">
        This is the volunteer's AI-assisted draft. Edit it directly below --
        whatever is here when you click <strong>Submit to MP</strong> becomes the
        frozen final text the MP reviews tomorrow.
      </p>

      <label class="muted" style="font-size:13px">Draft letter (fully editable)</label>
      <div class="draft-stream" id="vetter-draft" contenteditable="true" spellcheck="true">${escapeHtml(caseRecord.draft_content ?? "")}</div>

      <div class="field mt-16">
        <label>Comment to volunteer (required if returning for revision)</label>
        <textarea id="return-comment" rows="2"></textarea>
      </div>

      <div class="error-banner" id="vetter-error" style="display:none"></div>

      <div style="display:flex;gap:8px;margin-top:8px">
        <button id="return-btn">Return to volunteer</button>
        <div class="spacer"></div>
        <button class="primary" id="submit-mp">Submit to MP</button>
      </div>
      <p class="muted" style="font-size:12px;margin-top:6px">
        "Submit to MP" freezes this letter -- it cannot be edited afterwards.
      </p>
    </div>
  `;
  container.appendChild(wrap);

  const errorBanner = wrap.querySelector("#vetter-error");
  const showError = (msg) => { errorBanner.textContent = msg; errorBanner.style.display = "block"; };

  wrap.querySelector("#return-btn").addEventListener("click", async () => {
    const comment = wrap.querySelector("#return-comment").value.trim();
    if (!comment) { showError("Add a comment so the volunteer knows what to revise."); return; }
    if (!confirm("Return this case to the volunteer for revision?")) return;
    try {
      await returnCaseToVolunteer(caseRecord.id, comment);
      onResolved?.();
    } catch (e) { showError(`Couldn't return case: ${e.body?.detail ?? e.message ?? e}`); }
  });

  wrap.querySelector("#submit-mp").addEventListener("click", async () => {
    const finalText = wrap.querySelector("#vetter-draft").textContent;
    if (!finalText.trim()) { showError("The letter is empty."); return; }
    if (!confirm(
      "Submit this letter to the MP?\n\n" +
      "This FREEZES the letter -- it cannot be edited by anyone afterwards, " +
      "and this is the exact text the MP will review tomorrow."
    )) return;
    try {
      await vetterSubmitToMp(caseRecord.id, finalText);
      onResolved?.();
    } catch (e) { showError(`Couldn't submit to MP: ${e.body?.detail ?? e.message ?? e}`); }
  });
}

function escapeHtml(s) {
  return (s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
