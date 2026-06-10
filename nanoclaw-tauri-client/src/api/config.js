// Server connection config -- replaces the hardcoded SERVER / WS_SERVER
// constants that mps_client/api_client.py required editing per laptop:
//
//   SERVER    = "https://mps-server.local"
//   WS_SERVER = "wss://mps-server.local"
//
// Here it's a one-time "point this laptop at the server" step stored via
// the Rust-side tauri-plugin-store (see src-tauri/src/main.rs), so admins
// can set it from the UI without touching source code or rebuilding.

import { invoke } from "@tauri-apps/api/core";

let cached = null;

/** Returns { baseUrl, wsUrl } or { baseUrl: null, wsUrl: null } if unset. */
export async function getServerConfig() {
  if (cached) return cached;
  const config = await invoke("get_server_config");
  cached = config
    ? { baseUrl: config.base_url, wsUrl: config.ws_url }
    : { baseUrl: null, wsUrl: null };
  return cached;
}

/**
 * Persist the server origin. HTTPS is mandatory except on loopback for local
 * development. Paths, query strings and embedded credentials are rejected.
 */
export async function setServerAddress(hostAndPort) {
  const trimmed = hostAndPort.trim();
  const candidate = /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed)
    ? trimmed
    : `https://${trimmed}`;
  const parsed = new URL(candidate);
  const isLoopback = ["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname);

  if (!['https:', 'http:'].includes(parsed.protocol)) {
    throw new Error("Server address must use HTTPS.");
  }
  if (parsed.protocol === 'http:' && !isLoopback) {
    throw new Error("HTTPS is required for non-local server connections.");
  }
  if (parsed.username || parsed.password || parsed.pathname !== "/" || parsed.search || parsed.hash) {
    throw new Error("Enter only the server origin, without credentials, paths or query parameters.");
  }

  const baseUrl = `${parsed.protocol}//${parsed.host}`;
  const wsUrl = `${parsed.protocol === 'https:' ? 'wss:' : 'ws:'}//${parsed.host}`;
  await invoke("set_server_config", { config: { base_url: baseUrl, ws_url: wsUrl } });
  cached = { baseUrl, wsUrl };
}

export function clearConfigCache() {
  cached = null;
}
