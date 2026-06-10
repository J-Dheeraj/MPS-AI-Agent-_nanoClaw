// Bearer tokens are memory-only. Closing the application ends the local
// session and requires a fresh login, so recoverable tokens are never stored.

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

/** Application launches intentionally start without persisted credentials. */
export async function restoreSession() {
  notify();
  return { token: memoryToken, role: memoryRole };
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
