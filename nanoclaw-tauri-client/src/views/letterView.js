// Letter view -- the core volunteer tool, replacing
// mps_client/widgets/letter_view.py.
//
// Flow (per README MPS Night workflow steps d-f):
//   d. Click Generate Draft -> Ollama streams the letter in real time
//   e. Edit draft if needed -> Copy to Clipboard (paste into MPS platform
//      as a working copy) -- nanoClaw is NOT the system of record
//   f. Submit for vetting
//
// Streaming uses streamLetterDraft() from api/websocket.js, which wraps
// /letters/ws/draft (the same endpoint api_client.py streamed from).

import { streamLetterDraft } from "../api/websocket";
import { saveLetterDraft, submitCaseForVetting } from "../api/client";
import { writeText } from "@tauri-apps/plugin-clipboard-manager";

export function renderLetterView(container, { caseRecord, onSubmitted }) {
  container.innerHTML = "";

  const wrap = document.createElement("div");
  wrap.innerHTML = `
    <div class="toolbar">
      <strong>${caseRecord.case_type}</strong>
      <span class="badge ${caseRecord.status}">${caseRecord.status}</span>
      <span class="muted">${caseRecord.agency} • ${caseRecord.urgency}${caseRecord.is_reappeal ? " • re-appeal" : ""}</span>
      <div class="spacer"></div>
      <button id="generate" class="primary">Generate draft</button>
    </div>

    <div style="padding:16px">
      <div class="field">
        <label>Case notes (sent to the AI as drafting context)</label>
        <textarea id="notes" rows="3">${escapeHtml(caseRecord.notes ?? "")}</textarea>
      </div>

      <label class="muted" style="font-size:13px">Draft letter</label>
      <div class="draft-stream" id="draft-text" contenteditable="true" spellcheck="true"></div>

      <div style="display:flex;gap:8px;margin-top:12px">
        <button id="copy">Copy to clipboard</button>
        <div class="spacer"></div>
        <button id="save">Save draft</button>
        <button class="primary" id="submit">Submit for vetting</button>
      </div>
      <p class="muted mt-8" id="status-line" style="font-size:13px"></p>
    </div>
  `;
  container.appendChild(wrap);

  const draftBox = wrap.querySelector("#draft-text");
  const statusLine = wrap.querySelector("#status-line");
  const generateBtn = wrap.querySelector("#generate");
  let cancelStream = null;
  let currentLetterId = caseRecord.letter_id ?? null;

  draftBox.textContent = caseRecord.draft_content ?? "";

  generateBtn.addEventListener("click", async () => {
    const notes = wrap.querySelector("#notes").value.trim();
    if (!notes) { setStatus("Add case notes before generating a draft.", true); return; }

    draftBox.textContent = "";
    generateBtn.disabled = true;
    generateBtn.textContent = "Generating…";
    setStatus("Streaming draft from the on-prem model -- this can take a little while on 3B models.");

    try {
      cancelStream = await streamLetterDraft(
        { caseId: caseRecord.id, notes, isReappeal: !!caseRecord.is_reappeal },
        {
          onToken: (chunk) => {
            draftBox.textContent += chunk;
            draftBox.scrollTop = draftBox.scrollHeight;
          },
          onDone: (letterId) => {
            currentLetterId = letterId;
            generateBtn.disabled = false;
            generateBtn.textContent = "Regenerate draft";
            setStatus("Draft complete. Review, edit, then copy or submit for vetting.");
          },
          onError: (msg) => {
            generateBtn.disabled = false;
            generateBtn.textContent = "Generate draft";
            // ollama_client.py caps concurrent generations at 3 -- surface
            // queue-full errors clearly so volunteers know to wait, not retry immediately.
            setStatus(`Generation failed: ${msg}`, true);
          },
        }
      );
    } catch (e) {
      generateBtn.disabled = false;
      generateBtn.textContent = "Generate draft";
      setStatus(`Couldn't start generation: ${e.message ?? e}`, true);
    }
  });

  wrap.querySelector("#copy").addEventListener("click", async () => {
    await writeText(draftBox.textContent);
    setStatus("Copied to clipboard -- paste into the MPS platform as a working copy.");
  });

  wrap.querySelector("#save").addEventListener("click", async () => {
    if (!currentLetterId) { setStatus("Generate a draft before saving.", true); return; }
    try {
      await saveLetterDraft(currentLetterId, draftBox.textContent);
      setStatus("Draft saved.");
    } catch (e) {
      setStatus(`Couldn't save: ${e.body?.detail ?? e.message ?? e}`, true);
    }
  });

  wrap.querySelector("#submit").addEventListener("click", async () => {
    if (!currentLetterId) { setStatus("Generate (and review) a draft before submitting.", true); return; }
    if (!confirm("Submit this case for vetting? The vetter will review and may edit before sending to the MP.")) return;
    try {
      await saveLetterDraft(currentLetterId, draftBox.textContent);
      await submitCaseForVetting(caseRecord.id);
      setStatus("Submitted for vetting.");
      onSubmitted?.();
    } catch (e) {
      setStatus(`Couldn't submit: ${e.body?.detail ?? e.message ?? e}`, true);
    }
  });

  function setStatus(msg, isError = false) {
    statusLine.textContent = msg;
    statusLine.style.color = isError ? "var(--danger)" : "var(--muted)";
  }

  // Clean up an in-flight stream if the user navigates away mid-generation.
  return () => { if (cancelStream) cancelStream(); };
}

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
