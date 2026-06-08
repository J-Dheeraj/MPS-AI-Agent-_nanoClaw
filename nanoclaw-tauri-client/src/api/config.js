// Server connection config -- replaces the hardcoded SERVER / WS_SERVER
// constants that mps_client/api_client.py required editing per laptop:
//
//   SERVER    = "http://192.168.X.X:8000"
//   WS_SERVER = "ws://192.168.X.X:8000"
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
 * Persist the server address. Accepts a host[:port] like "192.168.1.50:8000"
 * or a full URL, and derives both the http(s) and ws(s) forms from it.
 */
export async function setServerAddress(hostAndPort) {
  const trimmed = hostAndPort.trim().replace(/^https?:\/\//, "").replace(/^wss?:\/\//, "");
  const baseUrl = `http://${trimmed}`;
  const wsUrl = `ws://${trimmed}`;
  await invoke("set_server_config", { config: { base_url: baseUrl, ws_url: wsUrl } });
  cached = { baseUrl, wsUrl };
}

export function clearConfigCache() {
  cached = null;
}
