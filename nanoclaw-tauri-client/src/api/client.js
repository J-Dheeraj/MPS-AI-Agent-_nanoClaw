// REST client for mps_server -- a JS port of mps_client/api_client.py's
// REST half (httpx-based async client in the original).
//
// Endpoints mirrored from mps_server/routers/*:
//   auth_router       -> /auth/login, /auth/logout, /auth/register
//   sessions_router   -> /sessions/open, /sessions/{id}/close, /sessions/current
//   residents_router  -> /residents/search, /residents (create, masked NRIC)
//   cases_router      -> /cases (CRUD), /cases/{id}/submit, /cases/{id}/vetter-submit, /cases/{id}/vetter-return
//   letters_router    -> /letters (save/freeze) -- streaming lives in websocket.js
//   feedback_router   -> /feedback (log), /feedback/approved, /feedback/{id}/validate
//
// All calls go through @tauri-apps/plugin-http's fetch, which is scoped by
// tauri.conf.json's plugins.http.scope to LAN-only addresses -- this is the
// software-side enforcement of the "no constituent data leaves the LAN" rule.

import { fetch } from "@tauri-apps/plugin-http";
import { getServerConfig } from "./config";
import { getToken, clearSession } from "./session";

class ApiError extends Error {
  constructor(status, body) {
    super(`API error ${status}: ${typeof body === "string" ? body : JSON.stringify(body)}`);
    this.status = status;
    this.body = body;
  }
}

async function request(path, { method = "GET", body, auth = true, formEncoded = false } = {}) {
  const { baseUrl } = await getServerConfig();
  if (!baseUrl) throw new Error("Server not configured -- run first-time setup first.");

  const headers = {};
  if (body && !formEncoded) headers["Content-Type"] = "application/json";
  if (formEncoded) headers["Content-Type"] = "application/x-www-form-urlencoded";

  if (auth) {
    const token = await getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${baseUrl}${path}`, {
    method,
    headers,
    body: body ? (formEncoded ? body : JSON.stringify(body)) : undefined,
  });

  // 401 -> token expired or account locked (auth.py locks after 5 failed attempts).
  // Clear the local session so the UI drops back to the login screen instead of
  // silently failing every subsequent call.
  if (res.status === 401 && auth) {
    await clearSession();
    throw new ApiError(401, "Session expired -- please log in again.");
  }

  const text = await res.text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) throw new ApiError(res.status, data ?? text);
  return data;
}

function safeJson(text) {
  try { return JSON.parse(text); } catch { return text; }
}

// ---- auth ----------------------------------------------------------------

// ---- MFA management (V4-I1) ----------------------------------------------
// Two-phase enrolment per auth_router.py (V3-C1): enroll -> pending secret,
// activate -> enforced + recovery codes shown once.

export async function mfaEnroll() {
  return request("/auth/mfa/enroll", { method: "POST" });
}

export async function mfaActivate(code) {
  return request("/auth/mfa/activate", { method: "POST", body: { code } });
}

export async function mfaDisable(code) {
  return request("/auth/mfa/disable", { method: "POST", body: { code } });
}

export async function mfaRegenerateRecoveryCodes(code) {
  return request("/auth/mfa/recovery-codes", { method: "POST", body: { code } });
}


/**
 * POST /auth/login -- OAuth2 password form (matches FastAPI's OAuth2PasswordRequestForm)
 * Returns { access_token, token_type, role, ... } per auth_router.py.
 */
export async function login(username, password, totp = "") {
  // totp is optional -- users without MFA leave it blank; the server ignores it.
  const params = { username, password };
  if (totp && totp.trim()) params.totp = totp.trim();
  const form = new URLSearchParams(params).toString();
  return request("/auth/login", { method: "POST", body: form, formEncoded: true, auth: false });
}

export async function logout() {
  return request("/auth/logout", { method: "POST" });
}

/** Admin-only: POST /auth/register -- create volunteer/vetter/admin accounts */
export async function registerUser({ username, password, role, full_name }) {
  return request("/auth/register", { method: "POST", body: { username, password, role, full_name } });
}

// ---- sessions (MPS night lifecycle) --------------------------------------

export async function openSession(date) {
  return request("/sessions/open", { method: "POST", body: { date } });
}

export async function closeSession(sessionId) {
  return request(`/sessions/${sessionId}/close`, { method: "POST" });
}

export async function getActiveSession() {
  return request("/sessions/current");
}

// ---- residents (NRIC always masked, e.g. S****567A) -----------------------

export async function searchResidents(query) {
  return request(`/residents/search?q=${encodeURIComponent(query)}`);
}

export async function createResident({ name, nric_masked, contact }) {
  return request("/residents", { method: "POST", body: { name, nric_masked, contact } });
}

// ---- cases ----------------------------------------------------------------

export async function listCases(params = {}) {
  const qs = new URLSearchParams(params).toString();
  return request(`/cases${qs ? `?${qs}` : ""}`);
}

export async function getCase(caseId) {
  return request(`/cases/${caseId}`);
}

/** Vetter-only: cases with status "drafted" awaiting review (server: GET /cases/queue) */
export async function getVetterQueue() {
  return request("/cases/queue");
}

export async function createCase({ resident_id, agency, case_type, urgency, is_reappeal, notes }) {
  return request("/cases", {
    method: "POST",
    body: { resident_id, agency, case_type, urgency, is_reappeal, notes },
  });
}

/** Volunteer: submit drafted letter for vetting -- case -> pending vetter queue */
export async function submitCaseForVetting(caseId) {
  return request(`/cases/${caseId}/submit`, { method: "POST" });
}

/**
 * Vetter: final action on a case. Saves `final_content`, sets `is_frozen = true`
 * (server then rejects further edits with 403, per cases_router.py), and moves
 * the case to `pending_mp`. This is the most safety-critical call in the app --
 * confirm with the vetter before sending.
 */
export async function vetterSubmitToMp(caseId, finalContent) {
  return request(`/cases/${caseId}/vetter-submit`, {
    method: "POST",
    body: { final_content: finalContent },
  });
}

/** Vetter: send the case back to the volunteer with a comment for revision */
export async function returnCaseToVolunteer(caseId, comment) {
  return request(`/cases/${caseId}/vetter-return`, { method: "POST", body: { comment } });
}

// ---- letters (non-streaming operations; streaming is in websocket.js) -----

export async function saveLetterDraft(letterId, content) {
  return request(`/letters/${letterId}`, { method: "PUT", body: { content } });
}

export async function getLetter(letterId) {
  return request(`/letters/${letterId}`);
}

// ---- feedback -> Hermes GEPA loop ------------------------------------------

/** Volunteer/vetter logs a policy correction spotted during drafting */
export async function logFeedback({ agency, incorrect_claim, correct_answer }) {
  // Anonymised by design: corrections never carry a case reference.
  return request("/feedback/", {
    method: "POST",
    body: { agency_code: agency, incorrect_claim, correct_answer },
  });
}

/** Vetter validates a logged correction before it can reach Hermes */
export async function validateFeedback(feedbackId, approved, options = {}) {
  return request(`/feedback/${feedbackId}/validate`, {
    method: "POST",
    body: {
      action: approved ? "approve" : "reject",
      reject_reason: options.rejectReason || undefined,
      source_title: options.sourceTitle || undefined,
      source_url: options.sourceUrl || undefined,
      effective_date: options.effectiveDate || undefined,
    },
  });
}

/** Vetter-only: view the queue of corrections awaiting validation */
export async function listPendingFeedback() {
  return request("/feedback/pending");
}

export { ApiError };
