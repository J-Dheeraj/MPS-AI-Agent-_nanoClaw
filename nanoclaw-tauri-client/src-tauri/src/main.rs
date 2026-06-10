// nanoClaw Tauri client -- Rust shell
//
// Responsibilities kept on the Rust side (deliberately thin):
//   1. Bootstrapping the webview window and plugins
//   2. Persisting the server URL (NOT the JWT) in a local store
//   3. Exposing small commands to the frontend
//
// JWT SECURITY: The bearer token is NEVER written to disk.
// It lives in JS memory (session.js memoryToken) for the life of the webview.
// On app close / restart the user must log in again. This is intentional:
//   - tauri-plugin-store writes plain JSON to the app-data directory.
//   - A stolen machine would expose a persistent token with no OS-level
//     encryption guarantee.
//   - The server issues 60-minute tokens (auth.py). Re-login on a LAN kiosk
//     is cheap; persistent token survival is not worth the storage risk.
//
// Server URL (base_url / ws_url) is not sensitive and IS still persisted so
// operators do not have to re-enter it on every launch.
//
// If persistent login across restarts becomes a requirement, use
// tauri-plugin-stronghold (Argon2-hardened vault) or the OS credential
// manager (Windows Credential Manager / libsecret). Do NOT re-add plain
// tauri-plugin-store writes for the JWT.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use tauri::Manager;
use tauri_plugin_store::StoreExt;

#[derive(Debug, Default, Serialize, Deserialize, Clone)]
struct ServerConfig {
    base_url: String,
    ws_url: String,
}

const STORE_FILE: &str = "nanoclaw-config.json";

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
