// nanoClaw Tauri client -- Rust shell
//
// Responsibilities kept on the Rust side (deliberately thin):
//   1. Bootstrapping the webview window and plugins
//   2. Persisting the non-secret server URL in a local store
//      (replaces the hardcoded SERVER / WS_SERVER constants that the
//      old GTK4 client required editing api_client.py to change)
//   3. Exposing small configuration commands to the frontend
//
// Everything else -- REST calls, WebSocket streaming, UI state, screens --
// lives in the frontend (src/) and talks to mps_server directly via the
// tauri-plugin-http / tauri-plugin-websocket bridges. This mirrors how
// mps_client/api_client.py worked (an async REST + WebSocket client), just
// moved into the webview instead of a GTK4 process.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use tauri::Manager;
use tauri_plugin_store::StoreExt;

#[derive(Debug, Default, Serialize, Deserialize, Clone)]
struct ServerConfig {
    /// e.g. "https://mps-server.local" -- set once per laptop on first run.
    /// Mirrors mps_client/api_client.py SERVER / WS_SERVER, but configurable
    /// from the UI instead of requiring a source edit per machine.
    base_url: String,
    ws_url: String,
}

const STORE_FILE: &str = "nanoclaw-config.json";

/// Read the persisted server config (base_url/ws_url). Returns None if the
/// laptop hasn't been pointed at a server yet -- the UI should show the
/// "connect to server" step before the login screen in that case.
#[tauri::command]
fn get_server_config(app: tauri::AppHandle) -> Result<Option<ServerConfig>, String> {
    let store = app.store(STORE_FILE).map_err(|e| e.to_string())?;
    match store.get("server") {
        Some(value) => serde_json::from_value(value.clone())
            .map(Some)
            .map_err(|e| e.to_string()),
        None => Ok(None),
    }
}

/// Persist the server config. Called once from a "first run" setup screen,
/// or whenever an admin needs to re-point the client at a different server.
#[tauri::command]
fn set_server_config(app: tauri::AppHandle, config: ServerConfig) -> Result<(), String> {
    let store = app.store(STORE_FILE).map_err(|e| e.to_string())?;
    store.set(
        "server",
        serde_json::to_value(&config).map_err(|e| e.to_string())?,
    );
    store.save().map_err(|e| e.to_string())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_store::Builder::default().build())
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_websocket::init())
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .plugin(tauri_plugin_clipboard_manager::init())
        .invoke_handler(tauri::generate_handler![
            get_server_config,
            set_server_config,
        ])
        .setup(|app| {
            #[cfg(debug_assertions)]
            {
                let window = app.get_webview_window("main").unwrap();
                window.open_devtools();
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running nanoClaw client");
}
