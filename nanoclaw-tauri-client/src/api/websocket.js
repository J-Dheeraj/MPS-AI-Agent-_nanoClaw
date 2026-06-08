// WebSocket streaming client -- JS port of the streaming half of
// mps_client/api_client.py (the original used the `websockets` package
// to stream tokens from /letters/ws/draft and /letters/ws/qa as Ollama
// generates them).
//
// mps_server/routers/letters_router.py exposes:
//   /letters/ws/draft  -- streams a generated appeal letter token-by-token
//   /letters/ws/qa     -- streams answers to free-form policy questions
//
// Both are plain JSON-message-over-WebSocket protocols. We use
// @tauri-apps/plugin-websocket so the connection is made from the Rust
// side (consistent with the LAN-only scope in tauri.conf.json) while still
// feeling like a normal JS WebSocket to the calling code.
//
// Expected message shape from the server (adjust to match the real
// implementation in ollama_client.py if it differs once you read the code):
//   { "type": "token",  "content": "..." }   -- one chunk of the streamed draft
//   { "type": "done",   "letter_id": 123 }   -- generation finished, includes the saved id
//   { "type": "error",  "message": "..." }   -- queue full (max 3 concurrent), Ollama error, etc.

import WebSocket from "@tauri-apps/plugin-websocket";
import { getServerConfig } from "./config";
import { getToken } from "./session";

/**
 * Stream a letter draft for a case.
 *
 * @param {object} params
 * @param {number} params.caseId
 * @param {string} params.notes        -- volunteer's case notes (the prompt input)
 * @param {"LETTER"|"REAPPEAL"} [params.kind]
 * @param {(chunk: string) => void} onToken      -- called for each streamed token/chunk
 * @param {(letterId: number) => void} onDone    -- called once when generation completes
 * @param {(message: string) => void} onError    -- called on any error (queue full, Ollama down, etc.)
 * @returns {Promise<() => void>} a `cancel` function that closes the socket early
 */
export async function streamLetterDraft({ caseId, notes, kind = "LETTER" }, { onToken, onDone, onError }) {
  const { wsUrl } = await getServerConfig();
  const token = await getToken();
  if (!wsUrl) throw new Error("Server not configured.");
  if (!token) throw new Error("Not authenticated.");

  // Token goes in the query string because the WebSocket handshake can't
  // carry an Authorization header from the browser/webview side. mps_server's
  // letters_router should validate it the same way the REST endpoints do.
  const url = `${wsUrl}/letters/ws/draft?token=${encodeURIComponent(token)}`;
  const socket = await WebSocket.connect(url);

  socket.addListener((message) => {
    const data = parseMessage(message);
    if (!data) return;
    switch (data.type) {
      case "token":
        onToken?.(data.content ?? "");
        break;
      case "done":
        onDone?.(data.letter_id);
        socket.disconnect();
        break;
      case "error":
        onError?.(data.message ?? "Unknown error from server");
        socket.disconnect();
        break;
      default:
        // Unrecognised message -- surface it for debugging rather than
        // failing silently; the Ollama queue (max 3 concurrent per
        // ollama_client.py) can emit status messages we may need to handle.
        console.debug("nanoclaw: unhandled draft-stream message", data);
    }
  });

  await socket.send(JSON.stringify({ case_id: caseId, notes, kind }));

  return () => socket.disconnect();
}

/**
 * Stream a free-form policy Q&A answer (e.g. "what's the EHG ceiling for a
 * family of 4?"). Same shape as the draft stream, against /letters/ws/qa.
 */
export async function streamPolicyQA({ question, agency }, { onToken, onDone, onError }) {
  const { wsUrl } = await getServerConfig();
  const token = await getToken();
  if (!wsUrl) throw new Error("Server not configured.");
  if (!token) throw new Error("Not authenticated.");

  const url = `${wsUrl}/letters/ws/qa?token=${encodeURIComponent(token)}`;
  const socket = await WebSocket.connect(url);

  socket.addListener((message) => {
    const data = parseMessage(message);
    if (!data) return;
    if (data.type === "token") onToken?.(data.content ?? "");
    else if (data.type === "done") { onDone?.(); socket.disconnect(); }
    else if (data.type === "error") { onError?.(data.message ?? "Unknown error"); socket.disconnect(); }
  });

  await socket.send(JSON.stringify({ question, agency }));
  return () => socket.disconnect();
}

function parseMessage(message) {
  // tauri-plugin-websocket delivers { type: "Text" | "Binary" | "Close", data }
  if (message?.type !== "Text") return null;
  try {
    return JSON.parse(message.data);
  } catch {
    console.warn("nanoclaw: non-JSON websocket message", message.data);
    return null;
  }
}
