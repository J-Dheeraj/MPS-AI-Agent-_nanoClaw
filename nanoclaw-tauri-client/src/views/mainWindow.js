// Main window shell -- role-based split-pane layout (case list left, detail
// right). Replaces mps_client/main_window.py. Ties together caseForm,
// letterView (volunteer), vetterView (vetter/admin), and feedbackView.
//
// Roles: volunteer | vetter | admin (per mps_server RBAC).
//   - volunteer: create cases, draft letters (letterView)
//   - vetter:    review/edit drafts, submit to MP or return (vetterView)
//   - admin:     sees everything + feedback validation queue

import { getState, setState, subscribe } from "../state/store";
import { listCases, getCase, openSession, getActiveSession, logout } from "../api/client";
import { clearSession } from "../api/session";
import { openCaseFormDialog } from "./caseForm";
import { renderLetterView } from "./letterView";
import { renderVetterCaseReview } from "./vetterView";
import { renderFeedback } from "./feedbackView";

const STATUS_FILTERS = ["all", "new", "assigned", "drafted", "pending_mp", "returned", "approved", "sent"];

export async function renderMainWindow(root, { onLoggedOut }) {
  const role = getState().user?.role ?? "volunteer";

  root.innerHTML = "";
  const shell = document.createElement("div");
  shell.className = "layout-split";
  shell.innerHTML = `
    <aside class="pane-list">
      <div class="toolbar">
        <strong>${role === "volunteer" ? "My cases" : role === "vetter" ? "Vetting queue" : "All cases"}</strong>
        <div class="spacer"></div>
        <button id="logout-btn" title="Sign out">Sign out</button>
      </div>
      <div style="padding:8px 12px">
        <select id="status-filter">${STATUS_FILTERS.map((s) => `<option value="${s}">${s === "all" ? "All statuses" : s}</option>`).join("")}</select>
        ${role === "volunteer" ? `<button id="new-case-btn" class="primary" style="margin-left:8px">New case</button>` : ""}
      </div>
      <div id="case-list"></div>
    </aside>
    <main class="pane-detail" id="case-detail">
      <p class="muted" style="padding:24px">Select a case to get started.</p>
    </main>
  `;
  root.appendChild(shell);

  shell.querySelector("#logout-btn").addEventListener("click", async () => {
    if (!confirm("Sign out?")) return;
    try { await logout(); } catch { /* best-effort */ }
    clearSession();
    onLoggedOut?.();
  });

  if (role === "volunteer") {
    shell.querySelector("#new-case-btn").addEventListener("click", () => {
      openCaseFormDialog({ onCreated: () => loadCases(shell) });
    });
  }

  shell.querySelector("#status-filter").addEventListener("change", (e) => {
    setState({ statusFilter: e.target.value });
    loadCases(shell);
  });

  // React to selection changes from the store.
  // store.js calls fn(state) with one argument -- track previous id ourselves.
  let prevSelectedCaseId = getState().selectedCaseId;
  subscribe((state) => {
    if (state.selectedCaseId !== prevSelectedCaseId) {
      prevSelectedCaseId = state.selectedCaseId;
      openCaseDetail(shell, state.selectedCaseId);
    }
  });

  await ensureActiveSession(role);
  await loadCases(shell);
}

async function ensureActiveSession(role) {
  if (role !== "volunteer") return;
  try {
    const active = await getActiveSession();
    // Server returns { session: null, message } when nothing is open,
    // or a flat { id, date, status, ... } object when a session exists.
    if (!active || !active.id) {
      // No open session for today -- silently open one so the volunteer
      // can start logging cases (mirrors the GTK client's startup check).
      const today = new Date().toISOString().slice(0, 10);
      await openSession(today);
    }
  } catch {
    // Non-fatal -- the server will reject case creation with a clear error
    // if a session really is required and missing.
  }
}

async function loadCases(shell) {
  const list = shell.querySelector("#case-list");
  list.innerHTML = `<p class="muted" style="padding:16px">Loading…</p>`;

  const filter = getState().statusFilter ?? "all";
  const params = filter === "all" ? {} : { status: filter };

  try {
    const payload = await listCases(params);
    const cases = payload?.cases ?? [];
    setState({ cases });
    if (!cases.length) {
      list.innerHTML = `<p class="muted" style="padding:16px">No cases here yet.</p>`;
      return;
    }
    list.innerHTML = "";
    for (const c of cases) {
      const row = document.createElement("div");
      row.className = "case-row" + (c.id === getState().selectedCaseId ? " selected" : "");
      row.innerHTML = `
        <strong>${escapeHtml(c.case_type)}</strong> <span class="badge ${escapeHtml(c.status)}">${escapeHtml(c.status)}</span>
        <div class="muted" style="font-size:12px">${escapeHtml(c.agency)} • ${escapeHtml(c.resident?.name ?? "resident")} • ${escapeHtml(c.urgency)}${c.is_reappeal ? " • re-appeal" : ""}</div>
      `;
      row.addEventListener("click", () => setState({ selectedCaseId: c.id }));
      list.appendChild(row);
    }
  } catch (e) {
    list.innerHTML = `<div class="error-banner" style="margin:16px">Couldn't load cases: ${e.message ?? e}</div>`;
  }
}

let detailCleanup = null;

async function openCaseDetail(shell, caseId) {
  const host = shell.querySelector("#case-detail");
  if (detailCleanup) { try { detailCleanup(); } catch {} detailCleanup = null; }
  if (!caseId) {
    host.innerHTML = `<p class="muted" style="padding:24px">Select a case to get started.</p>`;
    return;
  }

  host.innerHTML = `<p class="muted" style="padding:24px">Loading case…</p>`;
  let caseRecord;
  try {
    caseRecord = await getCase(caseId);
  } catch (e) {
    host.innerHTML = `<div class="error-banner" style="margin:24px">Couldn't load case: ${e.message ?? e}</div>`;
    return;
  }

  const role = getState().user?.role ?? "volunteer";

  if (role === "volunteer") {
    detailCleanup = renderLetterView(host, {
      caseRecord,
      onSubmitted: () => { setState({ selectedCaseId: null }); loadCases(shell); },
    });
  } else if (role === "vetter" || role === "admin") {
    if (caseRecord.is_frozen || caseRecord.status === "pending_mp" || caseRecord.status === "approved" || caseRecord.status === "sent") {
      renderFrozenReadOnly(host, caseRecord);
    } else {
      renderVetterCaseReview(host, {
        caseRecord,
        onResolved: () => { setState({ selectedCaseId: null }); loadCases(shell); },
      });
    }
  }
}

function renderFrozenReadOnly(host, caseRecord) {
  host.innerHTML = `
    <div class="toolbar">
      <strong>${caseRecord.case_type}</strong>
      <span class="badge ${caseRecord.status}">${caseRecord.status}</span>
    </div>
    <div style="padding:16px">
      <div class="frozen-banner">This letter is frozen -- it was submitted to the MP and can no longer be edited.</div>
      <div class="draft-stream" style="margin-top:12px">${escapeHtml(caseRecord.final_content ?? caseRecord.draft_content ?? "")}</div>
    </div>
  `;
}

function escapeHtml(s) {
  return (s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
