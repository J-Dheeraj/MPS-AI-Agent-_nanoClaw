// "New Case" dialog -- replaces mps_client/widgets/case_form.py.
// Flow per the README's MPS Night workflow:
//   a. Search / register resident (NRIC stored masked: S****567A)
//   b. Create case (agency, case type, urgency, re-appeal?)
//   c. Enter case notes
//
// IMPORTANT: NRIC masking is enforced server-side too (POST /residents/
// rejects unmasked NRICs per the README's security table), but we mask on
// the client as well so volunteers get instant feedback rather than a
// rejected request mid-interview.

import { searchResidents, createResident, createCase } from "../api/client";

const AGENCIES = ["HDB", "CPF", "MSF", "MOH", "MOM", "ICA"];
const URGENCY = ["normal", "urgent", "critical"];

/** Masks an NRIC-like string to S****567A form. Adjust regex if the real
 *  format differs (this matches the example in the nanoClaw README). */
function maskNric(raw) {
  const cleaned = raw.trim().toUpperCase();
  const match = cleaned.match(/^([A-Z])\d{4}(\d{3}[A-Z])$/);
  if (!match) return null;
  return `${match[1]}****${match[2]}`;
}

export function openCaseFormDialog({ onCreated }) {
  const overlay = document.createElement("div");
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;z-index:50";

  const modal = document.createElement("div");
  modal.style.cssText = "background:var(--surface);border-radius:12px;padding:24px;width:480px;max-height:85vh;overflow:auto";
  modal.innerHTML = `
    <h2 style="margin-top:0">New case</h2>

    <div class="field">
      <label>Resident -- search by name or masked NRIC</label>
      <input id="resident-search" placeholder="Search existing residents..." />
      <div id="resident-results" class="muted" style="font-size:13px;margin-top:6px"></div>
    </div>

    <details style="margin:10px 0">
      <summary class="muted" style="cursor:pointer">Resident not found -- register new</summary>
      <div class="field mt-8"><label>Full name</label><input id="new-name" /></div>
      <div class="field"><label>NRIC (will be masked before saving, e.g. S1234567A → S****567A)</label><input id="new-nric" /></div>
      <div class="field"><label>Contact (phone/address)</label><input id="new-contact" /></div>
      <button id="register-resident">Register resident</button>
    </details>

    <input type="hidden" id="resident-id" />
    <p id="selected-resident" class="muted" style="font-size:13px"></p>

    <div class="field">
      <label>Agency</label>
      <select id="agency">${AGENCIES.map((a) => `<option value="${a}">${a}</option>`).join("")}</select>
    </div>
    <div class="field"><label>Case type</label><input id="case-type" placeholder="e.g. EHG appeal, BTO ceiling, S Pass renewal..." /></div>
    <div class="field">
      <label>Urgency</label>
      <select id="urgency">${URGENCY.map((u) => `<option value="${u}">${u}</option>`).join("")}</select>
    </div>
    <div class="field">
      <label><input type="checkbox" id="is-reappeal" style="width:auto;display:inline-block" /> This is a re-appeal</label>
    </div>
    <div class="field"><label>Case notes (used as the AI drafting prompt)</label><textarea id="notes" rows="4"></textarea></div>

    <div class="error-banner" id="form-error" style="display:none"></div>

    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:8px">
      <button id="cancel">Cancel</button>
      <button class="primary" id="submit">Create case</button>
    </div>
  `;
  overlay.appendChild(modal);
  document.body.appendChild(overlay);

  let selectedResidentId = null;
  const errorBanner = modal.querySelector("#form-error");
  const showError = (msg) => { errorBanner.textContent = msg; errorBanner.style.display = "block"; };

  const close = () => overlay.remove();
  modal.querySelector("#cancel").addEventListener("click", close);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

  // -- resident search (debounced) --
  let searchTimer;
  modal.querySelector("#resident-search").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    const q = e.target.value.trim();
    if (q.length < 2) { modal.querySelector("#resident-results").innerHTML = ""; return; }
    searchTimer = setTimeout(async () => {
      try {
        const results = await searchResidents(q);
        const box = modal.querySelector("#resident-results");
        box.innerHTML = "";
        for (const r of results) {
          const row = document.createElement("div");
          row.style.cssText = "padding:6px 8px;border:1px solid var(--border);border-radius:6px;margin-bottom:4px;cursor:pointer";
          row.textContent = `${r.name} -- ${r.nric_masked}`;
          row.addEventListener("click", () => {
            selectedResidentId = r.id;
            modal.querySelector("#selected-resident").textContent = `Selected: ${r.name} (${r.nric_masked})`;
            box.innerHTML = "";
          });
          box.appendChild(row);
        }
      } catch (e) { showError(`Search failed: ${e.message ?? e}`); }
    }, 250);
  });

  // -- register new resident --
  modal.querySelector("#register-resident").addEventListener("click", async () => {
    const name = modal.querySelector("#new-name").value.trim();
    const nricRaw = modal.querySelector("#new-nric").value.trim();
    const contact = modal.querySelector("#new-contact").value.trim();
    const masked = maskNric(nricRaw);
    if (!name || !masked) {
      showError("Enter a name and a valid NRIC (e.g. S1234567A) -- it will be masked automatically.");
      return;
    }
    try {
      const resident = await createResident({ name, nric_masked: masked, contact });
      selectedResidentId = resident.id;
      modal.querySelector("#selected-resident").textContent = `Selected: ${resident.name} (${resident.nric_masked})`;
    } catch (e) {
      showError(`Couldn't register resident: ${e.body?.detail ?? e.message ?? e}`);
    }
  });

  // -- submit --
  modal.querySelector("#submit").addEventListener("click", async () => {
    if (!selectedResidentId) { showError("Select or register a resident first."); return; }
    const payload = {
      resident_id: selectedResidentId,
      agency: modal.querySelector("#agency").value,
      case_type: modal.querySelector("#case-type").value.trim(),
      urgency: modal.querySelector("#urgency").value,
      is_reappeal: modal.querySelector("#is-reappeal").checked,
      notes: modal.querySelector("#notes").value.trim(),
    };
    if (!payload.case_type || !payload.notes) { showError("Case type and notes are required."); return; }
    try {
      const created = await createCase(payload);
      close();
      onCreated?.(created);
    } catch (e) {
      showError(`Couldn't create case: ${e.body?.detail ?? e.message ?? e}`);
    }
  });
}
