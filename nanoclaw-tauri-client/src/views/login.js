// Login screen -- replaces mps_client/login_window.py (an Adwaita login UI
// with lockout messaging). Mirrors the same two-step flow:
//   1. First run only: point this laptop at the server (host:port)
//   2. Username + password -> POST /auth/login
//
// auth.py locks an account after 5 failed attempts -- surface that message
// verbatim so volunteers know to find an admin rather than keep retrying.

import { login } from "../api/client";
import { setSession } from "../api/session";
import { getServerConfig, setServerAddress } from "../api/config";

export async function renderLogin(container, { onLoggedIn }) {
  const { baseUrl } = await getServerConfig();
  container.innerHTML = "";

  const wrap = document.createElement("div");
  wrap.className = "login-screen";

  const card = document.createElement("div");
  card.className = "login-card";

  if (!baseUrl) {
    card.innerHTML = `
      <h1>Connect to server</h1>
      <p>Enter the central server's HTTPS origin supplied by an administrator
         (for example <code>https://mps-server.local</code>).</p>
      <div class="field">
        <label>Server address</label>
        <input id="server-addr" placeholder="https://mps-server.local" />
      </div>
      <div class="error-banner" id="login-error" style="display:none"></div>
      <button class="primary" id="server-save" style="width:100%">Continue</button>
    `;
    wrap.appendChild(card);
    container.appendChild(wrap);

    card.querySelector("#server-save").addEventListener("click", async () => {
      const addr = card.querySelector("#server-addr").value;
      const err = card.querySelector("#login-error");
      if (!addr.trim()) return;
      try {
        await setServerAddress(addr);
        renderLogin(container, { onLoggedIn });
      } catch (e) {
        err.textContent = `Couldn't save server address: ${e.message ?? e}`;
        err.style.display = "block";
      }
    });
    return;
  }

  card.innerHTML = `
    <h1>nanoClaw</h1>
    <p>MPS casework -- sign in with your volunteer/vetter/admin account.</p>
    <div class="field">
      <label>Username</label>
      <input id="login-username" autocomplete="username" />
    </div>
    <div class="field">
      <label>Password</label>
      <input id="login-password" type="password" autocomplete="current-password" />
    </div>
    <div class="field" id="totp-field" style="display:none">
      <label>Authenticator code <span class="muted">(if MFA enabled)</span></label>
      <input id="login-totp" type="text" inputmode="numeric" maxlength="8"
             autocomplete="one-time-code" placeholder="6-digit code or recovery code" />
    </div>
    <div class="error-banner" id="login-error" style="display:none"></div>
    <button class="primary" id="login-submit" style="width:100%">Sign in</button>
    <p class="muted mt-16" style="font-size:12px">
      Connected to <code>${baseUrl}</code> --
      <a href="#" id="change-server">change server</a>
    </p>
  `;
  wrap.appendChild(card);
  container.appendChild(wrap);

  const submit = card.querySelector("#login-submit");
  const errorBanner = card.querySelector("#login-error");

  async function doLogin() {
    const username = card.querySelector("#login-username").value.trim();
    const password = card.querySelector("#login-password").value;
    if (!username || !password) return;

    const totpInput = card.querySelector("#login-totp");
    const totpField = card.querySelector("#totp-field");
    const totp = totpInput ? totpInput.value.replace(/\s/g, "") : "";

    submit.disabled = true;
    errorBanner.style.display = "none";
    try {
      const result = await login(username, password, totp);
      await setSession(result.access_token, result.role);
      onLoggedIn({ username, role: result.role, full_name: result.full_name });
    } catch (e) {
      const detail = e.body?.detail ?? e.message ?? "Login failed.";
      // Show the TOTP field when the server asks for MFA so the user
      // can re-submit with a code without having to type credentials again.
      if (typeof detail === "string" && detail.toLowerCase().includes("mfa")) {
        totpField.style.display = "block";
        totpInput.focus();
      }
      // auth.py returns a specific message after repeated failures
      // ("Account locked, try again in N minutes") -- show it as-is.
      errorBanner.textContent = detail;
      errorBanner.style.display = "block";
    } finally {
      submit.disabled = false;
    }
  }

  submit.addEventListener("click", doLogin);
  card.querySelector("#login-password").addEventListener("keydown", (e) => {
    if (e.key === "Enter") doLogin();
  });
  card.querySelector("#login-totp").addEventListener("keydown", (e) => {
    if (e.key === "Enter") doLogin();
  });
  card.querySelector("#change-server").addEventListener("click", async (e) => {
    e.preventDefault();
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("set_server_config", { config: { base_url: "", ws_url: "" } });
    const { clearConfigCache } = await import("../api/config");
    clearConfigCache();
    renderLogin(container, { onLoggedIn });
  });
}
