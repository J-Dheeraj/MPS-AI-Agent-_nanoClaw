// NanoClaw agent — Bun runtime, Ollama LLM, no API key required

import OpenAI from "openai";
import { Database } from "bun:sqlite";
import fs from "fs";
import path from "path";
import { mnemon } from "./mnemon";
import { ingestTool } from "./tools/ingest";

const GROUP_DIR    = process.env.GROUP_DIR    || "/workspace/group";
const GROUP_ID     = process.env.GROUP_ID     || "main";
const OLLAMA_URL   = process.env.OLLAMA_URL   || "http://host.docker.internal:11434";
const OLLAMA_MODEL = process.env.OLLAMA_MODEL || "llama3.2:3b";

const client = new OpenAI({
  baseURL: OLLAMA_URL + "/v1",
  apiKey:  "ollama",
  timeout: 10 * 60 * 1000, // 10 minutes — overcome Bun fetch default 5min
  maxRetries: 0,
});

function loadClaudeMd(): string {
  try {
    const c = fs.readFileSync(path.join(GROUP_DIR, "CLAUDE.md"), "utf8");
    console.log("[agent] Loaded CLAUDE.md (" + c.length + " chars)");
    return c;
  } catch {
    console.warn("[agent] No CLAUDE.md — using fallback prompt");
    return "";
  }
}

const CLAUDE_MD = loadClaudeMd();

const inboundDb  = new Database(path.join(GROUP_DIR, "inbound.db"));
const outboundDb = new Database(path.join(GROUP_DIR, "outbound.db"));
inboundDb.run("PRAGMA journal_mode = WAL");
outboundDb.run("PRAGMA journal_mode = WAL");

outboundDb.exec(
  "CREATE TABLE IF NOT EXISTS messages (" +
  "id TEXT PRIMARY KEY, channel TEXT NOT NULL, recipient_id TEXT NOT NULL, " +
  "content TEXT NOT NULL, sent INTEGER DEFAULT 0, timestamp INTEGER NOT NULL)"
);

const tools: any[] = [
  {
    type: "function",
    function: {
      name: "search_knowledge",
      description: "Search the local knowledge graph for information on a topic",
      parameters: { type: "object", properties: { query: { type: "string" } }, required: ["query"] },
    },
  },
  {
    type: "function",
    function: {
      name: "ingest_url",
      description: "Fetch and ingest an article or web page into the knowledge graph",
      parameters: { type: "object", properties: { url: { type: "string" } }, required: ["url"] },
    },
  },
];

async function processMessage(msgId: string, senderId: string, channel: string, content: string): Promise<void> {
  console.log("[agent] Processing " + msgId + " via " + OLLAMA_MODEL);

  const facts = mnemon.searchFacts(content.slice(0, 100));
  const ctx   = facts.length ? facts.map(f => "- " + f).join("\n") : "(none yet)";
  const now   = new Date().toISOString();

  const systemPrompt = (CLAUDE_MD ? CLAUDE_MD + "\n\n---\n" : "") +
    "You are a helpful personal AI assistant running fully locally on the user's computer." +
    "\nCurrent date: " + now + "  |  Group: " + GROUP_ID +
    "\n\nRelevant context from knowledge graph:\n" + ctx;

  const messages: any[] = [
    { role: "system", content: systemPrompt },
    { role: "user",   content },
  ];

  let response: any = await client.chat.completions.create({
    model: OLLAMA_MODEL,
    messages,
    tools,
    tool_choice: "auto",
  });

  while (response.choices[0]?.finish_reason === "tool_calls") {
    const assistantMsg = response.choices[0].message;
    messages.push(assistantMsg);
    for (const tc of (assistantMsg.tool_calls ?? [])) {
      const args = JSON.parse(tc.function.arguments || "{}");
      let result = "";
      if (tc.function.name === "search_knowledge") {
        const found = mnemon.searchFacts(args.query ?? "");
        result = found.length ? found.join("\n") : "No relevant information found.";
      } else if (tc.function.name === "ingest_url") {
        result = await ingestTool(args.url ?? "", mnemon);
      }
      messages.push({ role: "tool", tool_call_id: tc.id, content: result });
    }
    response = await client.chat.completions.create({
      model: OLLAMA_MODEL, messages, tools, tool_choice: "auto",
    });
  }

  const replyText = response.choices[0]?.message?.content || "(no response)";

  outboundDb.prepare("INSERT INTO messages VALUES (?, ?, ?, ?, 0, ?)").run(
    msgId + "-reply", channel, senderId, replyText, Date.now()
  );
  inboundDb.prepare("UPDATE messages SET processed = 1 WHERE id = ?").run(msgId);
  console.log("[agent] Replied to " + msgId);
}

async function poll(): Promise<void> {
  try {
    inboundDb.exec(
      "CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, sender_id TEXT NOT NULL, " +
      "channel TEXT NOT NULL, type TEXT NOT NULL, content TEXT NOT NULL, mime_type TEXT, " +
      "timestamp INTEGER NOT NULL, processed INTEGER DEFAULT 0, context_only INTEGER DEFAULT 0)"
    );
    const pending = inboundDb.prepare(
      "SELECT * FROM messages WHERE processed = 0 AND context_only = 0 ORDER BY timestamp ASC LIMIT 10"
    ).all() as any[];
    for (const msg of pending) {
      await processMessage(msg.id, msg.sender_id, msg.channel, msg.content);
    }
  } catch (err) {
    console.error("[agent] Poll error:", err);
  }
}

console.log("[nanoclaw-agent] Starting | group: " + GROUP_ID + " | model: " + OLLAMA_MODEL);

async function run(): Promise<void> {
  while (true) {
    await poll();
    await new Promise(r => setTimeout(r, 3000));
  }
}

console.log("[nanoclaw-agent] Starting | group: " + GROUP_ID + " | model: " + OLLAMA_MODEL);
run();
