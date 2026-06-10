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
// Server protocol (mps_server/routers/letters_router.py):
//   { "type": "chunk", "text": "..." }                    -- one streamed chunk
//   { "type": "queue", "queue_position": N, "message" }   -- waiting in LLM queue
//   { "type": "done",  "letter_id", "version", "text" }   -- generation finished
//   { "type": "error", "text": "..." }                    -- auth/queue/Ollama error

import WebSocket from "@tauri-apps/plugin-websocket";
import { getServerConfig } from "./config";
import { getToken } from "./session";

/**
 * Stream a letter draft for a case.
 *
 * @param {object} params
 * @param {number} params.caseId
 * @param {"LETTER"|"REAPPEAL"} [params.kind]
 * @param {(chunk: string) => void} onToken      -- called for each streamed token/chunk
 * @param {(letterId: number) => void} onDone    -- called once when generation completes
 * @param {(message: string) => void} onError    -- called on any error (queue full, Ollama down, etc.)
 * @returns {Promise<() => void>} a `cancel` function that closes the socket early
 */
export async function streamLetterDraft({ caseId, isReappeal = false }, { onToken, onDone, onError, onQueue }) {
  const { wsUrl } = await getServerConfig();
  const token = await getToken();
  if (!wsUrl) throw new Error("Server not configured.");
  if (!token) throw new Error("Not authenticated.");

  const socket = await WebSocket.connect(`${wsUrl}/letters/ws/draft`);

  socket.addListener((message) => {
    const data = parseMessage(message);
    if (!data) return;
    switch (data.type) {
      case "chunk":
        onToken?.(data.text ?? "");
        break;
      case "queue":
        onQueue?.(data.queue_position, data.message);
        break;
      case "done":
        onDone?.(data.letter_id, data.version);
        socket.disconnect();
        break;
      case "error":
        onError?.(data.text ?? "Unknown error from server");
        socket.disconnect();
        break;
      default:
        console.debug("nanoclaw: unhandled draft-stream message", data);
    }
  });

  await socket.send(JSON.stringify({ type: "auth", token }));
  await socket.send(JSON.stringify({
    case_id: caseId,
    is_reappeal: isReappeal,
  }));

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

  const socket = await WebSocket.connect(`${wsUrl}/letters/ws/qa`);

  socket.addListener((message) => {
    const data = parseMessage(message);
    if (!data) return;
    if (data.type === "chunk") onToken?.(data.text ?? "");
    else if (data.type === "done") { onDone?.(); socket.disconnect(); }
    else if (data.type === "error") { onError?.(data.text ?? "Unknown error"); socket.disconnect(); }
  });

  await socket.send(JSON.stringify({ type: "auth", token }));
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
