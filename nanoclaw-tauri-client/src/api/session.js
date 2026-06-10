// Session/token storage -- in-memory only.
//
// JWT SECURITY: The bearer token is held ONLY in the JS variables below.
// It is never written to disk. tauri-plugin-store writes plain JSON to the
// app-data directory with no OS-level encryption guarantee; storing a JWT
// there creates a plaintext credential file that survives app exit.
//
// The server issues 60-minute tokens (auth.py). On a LAN kiosk, requiring
// re-login after restart is a negligible cost for eliminating persistent
// token theft risk.
//
// If persistent login is ever needed, use tauri-plugin-stronghold
// (Argon2-hardened vault) or the OS credential manager. That is a conscious
// architectural decision requiring the security model to be updated first.
// Do not add invoke("save_session_token", ...) back without that work.


let memoryToken = null;
let memoryRole = null;
const listeners = new Set();

export function onSessionChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notify() {
  for (const fn of listeners) fn({ token: memoryToken, role: memoryRole });
}

/**
 * Call once on app launch. No persistent token exists, so this just notifies
 * listeners that the session is empty and the login screen should be shown.
 */
export async function restoreSession() {
  // No disk restore -- token is in-memory only.
  notify();
  return { token: null, role: null };
}

/** Call after a successful POST /auth/login. */
export async function setSession(token, role) {
  memoryToken = token;
  memoryRole = role;
  notify();
}

export async function getToken() {
  return memoryToken;
}

export function getRole() {
  return memoryRole;
}

export function isAuthenticated() {
  return !!memoryToken;
}

/** Call on logout, or automatically when the API client sees a 401. */
export async function clearSession() {
  memoryToken = null;
  memoryRole = null;
  notify();
}
