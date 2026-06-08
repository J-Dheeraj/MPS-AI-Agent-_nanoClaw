// Tiny pub/sub app state -- intentionally not a framework.
//
// The original mps_client used async_bridge.py to marshal results from an
// asyncio loop back onto the GTK main thread via GLib.idle_add. In a webview
// there's no such split (everything runs on one JS thread), so we don't need
// that bridge at all -- this store just centralises shared UI state
// (current user, selected case, active session) so views can react to changes.
//
// Claude Code: if the team prefers React/Svelte/Vue, swap this file out for
// the framework's state primitives and update the views accordingly -- the
// api/ modules underneath are framework-agnostic and don't need to change.

const state = {
  user: null,        // { username, role, full_name }
  activeSession: null,
  cases: [],
  selectedCaseId: null,
};

const listeners = new Set();

export function getState() {
  return state;
}

export function setState(patch) {
  Object.assign(state, patch);
  for (const fn of listeners) fn(state);
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
