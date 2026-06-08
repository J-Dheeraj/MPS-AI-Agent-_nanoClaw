// App entry point. Restores any persisted session (token held in the Rust
// store plugin, never localStorage), then renders either the login screen
// or the main window shell depending on auth state.

import "./style.css";
import { restoreSession, isAuthenticated, onSessionChange } from "./api/session";
import { setState } from "./state/store";
import { renderLogin } from "./views/login";
import { renderMainWindow } from "./views/mainWindow";

const app = document.getElementById("app");

async function boot() {
  await restoreSession();
  render();
}

function render() {
  app.innerHTML = "";
  if (isAuthenticated()) {
    renderMainWindow(app, { onLoggedOut: render });
  } else {
    renderLogin(app, { onLoggedIn: (user) => { setState({ user, selectedCaseId: null }); render(); } });
  }
}

// Re-render whenever the session is cleared elsewhere (e.g. a 401 from the
// API client, or "Sign out") so the UI never gets stuck showing stale data.
onSessionChange(() => render());

boot();
