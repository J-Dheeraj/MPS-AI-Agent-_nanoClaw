// Feedback view -- lets vetters/admins log policy corrections that feed
// Hermes' weekly GEPA skill-improvement cycle, and lets admins validate
// pending feedback entries before they're folded into the next training run.
//
// Mirrors the feedback endpoints exposed by mps_server: logFeedback,
// validateFeedback, listPendingFeedback (see api/client.js).

import { logFeedback, validateFeedback, listPendingFeedback } from "../api/client";
import { getState } from "../state/store";

const AGENCIES = ["HDB", "CPF", "MSF", "MOH", "MOM", "ICA"];

export async function renderFeedback(container, { caseRecord } = {}) {
  const role = getState().user?.role;
  container.innerHTML = "";

  const wrap = document.createElement("div");
  wrap.innerHTML = `
    <div class="toolbar"><strong>Feedback &amp; Hermes corrections</strong></div>
    <div style="padding:16px">
      <p class="muted" style="font-size:13px">
        Corrections logged here are reviewed weekly and folded into Hermes'
        GEPA skill-improvement cycle -- they help the on-prem model produce
        better drafts for this agency's policies over time.
      </p>

      <div class="field">
        <label>Agency</label>
        <select id="fb-agency">${AGENCIES.map((a) => `<option ${caseRecord?.agency === a ? "selected" : ""}>${a}</option>`).join("")}</select>
      </div>
      <div class="field">
        <label>What the draft got wrong</label>
        <textarea id="fb-issue" rows="2" placeholder="e.g. cited the wrong CPF withdrawal age"></textarea>
      </div>
      <div class="field">
        <label>Corrected guidance</label>
        <textarea id="fb-correction" rows="3" placeholder="What should the model say instead?"></textarea>
      </div>
      <div class="error-banner" id="fb-error" style="display:none"></div>
      <button class="primary" id="fb-submit">Log feedback</button>

      ${role === "admin" ? `
        <h3 style="margin-top:24px">Pending validation</h3>
        <div id="fb-pending"><p class="muted">Loading…</p></div>
      ` : ""}
    </div>
  `;
  container.appendChild(wrap);

  const errorBanner = wrap.querySelector("#fb-error");
  const showError = (msg) => { errorBanner.textContent = msg; errorBanner.style.display = "block"; };

  wrap.querySelector("#fb-submit").addEventListener("click", async () => {
    const agency = wrap.querySelector("#fb-agency").value;
    const issue = wrap.querySelector("#fb-issue").value.trim();
    const correction = wrap.querySelector("#fb-correction").value.trim();
    if (!issue || !correction) { showError("Fill in both the issue and the corrected guidance."); return; }
    try {
      await logFeedback({ agency, incorrect_claim: issue, correct_answer: correction, case_id: caseRecord?.id ?? null });
      wrap.querySelector("#fb-issue").value = "";
      wrap.querySelector("#fb-correction").value = "";
      errorBanner.style.display = "none";
      flashSaved(wrap.querySelector("#fb-submit"));
    } catch (e) { showError(`Couldn't log feedback: ${e.body?.detail ?? e.message ?? e}`); }
  });

  if (role === "admin") {
    await loadPending(wrap);
  }
}

async function loadPending(wrap) {
  const host = wrap.querySelector("#fb-pending");
  try {
    const items = await listPendingFeedback();
    if (!items.length) { host.innerHTML = `<p class="muted">Nothing pending validation.</p>`; return; }
    host.innerHTML = "";
    for (const item of items) {
      const row = document.createElement("div");
      row.className = "case-row";
      row.innerHTML = `
        <strong>${item.agency}</strong>
        <div class="muted" style="font-size:13px">Issue: ${escapeHtml(item.issue)}</div>
        <div class="muted" style="font-size:13px">Correction: ${escapeHtml(item.correction)}</div>
        <div style="margin-top:8px;display:flex;gap:8px">
          <button data-action="reject">Reject</button>
          <button class="primary" data-action="approve">Approve</button>
        </div>
      `;
      row.querySelector('[data-action="approve"]').addEventListener("click", async () => {
        await validateFeedback(item.id, true);
        await loadPending(wrap);
      });
      row.querySelector('[data-action="reject"]').addEventListener("click", async () => {
        await validateFeedback(item.id, false);
        await loadPending(wrap);
      });
      host.appendChild(row);
    }
  } catch (e) {
    host.innerHTML = `<div class="error-banner">Couldn't load pending feedback: ${e.message ?? e}</div>`;
  }
}

function flashSaved(btn) {
  const original = btn.textContent;
  btn.textContent = "Saved ✓";
  setTimeout(() => { btn.textContent = original; }, 1200);
}

function escapeHtml(s) {
  return (s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
