// Session/token storage -- thin wrapper around the Rust commands in
// src-tauri/src/main.rs. The JWT is never written to localStorage/JS-land
// persistent storage (per Tauri artifact rules and basic good hygiene);
// it's held in memory for the life of the webview and persisted via the
// Rust-side encrypted store plugin between launches.

import { invoke } from "@tauri-apps/api/core";

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

/** Call once on app launch to restore a previous session, if any. */
export async function restoreSession() {
  const result = await invoke("load_session_token");
  if (result) {
    [memoryToken, memoryRole] = result;
  }
  notify();
  return { token: memoryToken, role: memoryRole };
}

/** Call after a successful POST /auth/login. */
export async function setSession(token, role) {
  memoryToken = token;
  memoryRole = role;
  await invoke("save_session_token", { token, role });
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
  await invoke("clear_session_token");
  notify();
}
