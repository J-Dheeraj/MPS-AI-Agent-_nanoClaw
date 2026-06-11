// "Security" dialog -- MFA enrolment, recovery codes and disable (V4-I1).
// Mirrors auth_router.py's two-phase enrolment (V3-C1): /mfa/enroll stores a
// pending secret only; MFA is enforced only after /mfa/activate confirms a
// code, so closing this dialog mid-enrolment never locks the user out.

import {
  mfaEnroll, mfaActivate, mfaDisable, mfaRegenerateRecoveryCodes,
} from "../api/client";

function codesBlock(codes) {
  return `
    <p><strong>Recovery codes</strong> — store these safely; they are shown only once.
    Each works one time if your authenticator is unavailable.</p>
    <pre style="background:var(--surface-2,#f4f4f4);padding:12px;border-radius:8px;user-select:all">${codes.join("\n")}</pre>
  `;
}

export function openSecurityDialog() {
  const overlay = document.createElement("div");
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;z-index:50";

  const modal = document.createElement("div");
  modal.style.cssText = "background:var(--surface);border-radius:12px;padding:24px;width:480px;max-height:85vh;overflow:auto";

  const close = () => overlay.remove();
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

  function renderHome() {
    modal.innerHTML = `
      <h2 style="margin-top:0">Security — two-factor authentication</h2>
      <p class="muted">Adds a 6-digit authenticator code to your sign-in.</p>
      <div id="sec-error" style="color:var(--danger,#c0392b);font-size:13px"></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
        <button id="enroll-btn" class="primary">Set up MFA</button>
        <button id="regen-btn">New recovery codes</button>
        <button id="disable-btn">Disable MFA</button>
        <div class="spacer"></div>
        <button id="close-btn">Close</button>
      </div>
      <p class="muted" style="font-size:12px;margin-top:12px">
        "Set up" fails if MFA is already enabled; the other two require MFA
        and a current code. Lost both authenticator and codes? An admin can
        reset MFA on your account.
      </p>
    `;
    modal.querySelector("#close-btn").addEventListener("click", close);
    modal.querySelector("#enroll-btn").addEventListener("click", startEnrolment);
    modal.querySelector("#regen-btn").addEventListener("click", () => askCode(
      "New recovery codes", "Enter a current authenticator code to replace your recovery codes.",
      async (code) => {
        const res = await mfaRegenerateRecoveryCodes(code);
        showResult("Recovery codes replaced", codesBlock(res.recovery_codes));
      }));
    modal.querySelector("#disable-btn").addEventListener("click", () => askCode(
      "Disable MFA", "Enter a current authenticator code to confirm.",
      async (code) => {
        await mfaDisable(code);
        showResult("MFA disabled", "<p>Your account no longer requires a second factor.</p>");
      }));
  }

  async function startEnrolment() {
    const errEl = modal.querySelector("#sec-error");
    let enroll;
    try {
      enroll = await mfaEnroll();
    } catch (e) {
      errEl.textContent = e?.body?.detail ?? String(e.message ?? e);
      return;
    }
    modal.innerHTML = `
      <h2 style="margin-top:0">Set up MFA</h2>
      <p>Add this secret to your authenticator app (Google Authenticator,
      Aegis, 1Password…), then enter the 6-digit code it shows.</p>
      <div class="field"><label>Secret key (or use the otpauth link below)</label>
        <input readonly value="${enroll.secret}" onfocus="this.select()" /></div>
      <p class="muted" style="font-size:12px;word-break:break-all">${enroll.otpauth_uri}</p>
      <div class="field"><label>6-digit code</label>
        <input id="activate-code" inputmode="numeric" maxlength="8" autocomplete="one-time-code" /></div>
      <div id="sec-error" style="color:var(--danger,#c0392b);font-size:13px"></div>
      <div style="display:flex;gap:8px;margin-top:12px">
        <button id="activate-btn" class="primary">Activate</button>
        <button id="cancel-btn">Cancel</button>
      </div>
      <p class="muted" style="font-size:12px">Cancelling is safe: MFA is not
      enforced until you activate.</p>
    `;
    modal.querySelector("#cancel-btn").addEventListener("click", renderHome);
    modal.querySelector("#activate-btn").addEventListener("click", async () => {
      const code = modal.querySelector("#activate-code").value.trim();
      try {
        const res = await mfaActivate(code);
        showResult("MFA enabled", codesBlock(res.recovery_codes));
      } catch (e) {
        modal.querySelector("#sec-error").textContent =
          e?.body?.detail ?? String(e.message ?? e);
      }
    });
  }

  function askCode(title, prompt, action) {
    modal.innerHTML = `
      <h2 style="margin-top:0">${title}</h2>
      <p>${prompt}</p>
      <div class="field"><label>6-digit code (or a recovery code)</label>
        <input id="code-input" autocomplete="one-time-code" /></div>
      <div id="sec-error" style="color:var(--danger,#c0392b);font-size:13px"></div>
      <div style="display:flex;gap:8px;margin-top:12px">
        <button id="ok-btn" class="primary">Confirm</button>
        <button id="cancel-btn">Cancel</button>
      </div>
    `;
    modal.querySelector("#cancel-btn").addEventListener("click", renderHome);
    modal.querySelector("#ok-btn").addEventListener("click", async () => {
      try {
        await action(modal.querySelector("#code-input").value.trim());
      } catch (e) {
        modal.querySelector("#sec-error").textContent =
          e?.body?.detail ?? String(e.message ?? e);
      }
    });
  }

  function showResult(title, html) {
    modal.innerHTML = `
      <h2 style="margin-top:0">${title}</h2>
      ${html}
      <div style="display:flex;gap:8px;margin-top:12px">
        <button id="done-btn" class="primary">Done</button>
      </div>
    `;
    modal.querySelector("#done-btn").addEventListener("click", close);
  }

  renderHome();
  overlay.appendChild(modal);
  document.body.appendChild(overlay);
}
