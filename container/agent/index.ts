import Database from 'better-sqlite3';
import fs from 'fs';
import path from 'path';
import fs from 'fs';
import { mnemon } from './mnemon';

const GROUP_DIR = process.env.GROUP_DIR || '/workspace/group';
const GROUP_ID = process.env.GROUP_ID || 'main';

const OLLAMA_BASE_URL = process.env.OLLAMA_BASE_URL || 'http://host.docker.internal:11434';
const OLLAMA_MODEL = process.env.OLLAMA_MODEL || 'llama3.1:8b';

// Bug 6 fixed: load CLAUDE.md from the group directory as the agent's system prompt.
// Without this, the agent had no MPS policy knowledge, letter format, or behavioural rules.
function loadClaudeMd(): string {
  const claudePath = path.join(GROUP_DIR, 'CLAUDE.md');
  try {
    const content = fs.readFileSync(claudePath, 'utf8');
    console.log(`[agent] Loaded CLAUDE.md (${content.length} chars)`);
    return content;
  } catch {
    console.warn('[agent] CLAUDE.md not found — using minimal fallback system prompt');
    return '';
  }
}

const CLAUDE_MD = loadClaudeMd();

// Bug 20 fixed: open both databases with WAL mode so host writes and container reads
// can happen concurrently without SQLITE_BUSY errors under load.
const inboundDb = new Database(path.join(GROUP_DIR, 'inbound.db'));
inboundDb.pragma('journal_mode = WAL');

const outboundDb = new Database(path.join(GROUP_DIR, 'outbound.db'));
outboundDb.pragma('journal_mode = WAL');

outboundDb.exec(`CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  channel TEXT NOT NULL,
  recipient_id TEXT NOT NULL,
  content TEXT NOT NULL,
  sent INTEGER DEFAULT 0,
  timestamp INTEGER NOT NULL
)`);

function loadClaudeMd(): string {
  const claudePath = path.join(GROUP_DIR, 'CLAUDE.md');

  try {
    if (fs.existsSync(claudePath)) {
      return fs.readFileSync(claudePath, 'utf8');
    }
  } catch (err) {
    console.error('[agent] Failed to read CLAUDE.md:', err);
  }

  return `You are a helpful internal MPS assistant. Reply clearly and safely.`;
}

async function askOllama(systemPrompt: string, userContent: string): Promise<string> {
  const response = await fetch(`${OLLAMA_BASE_URL}/api/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: OLLAMA_MODEL,
      stream: false,
      messages: [
        {
          role: 'system',
          content: systemPrompt,
        },
        {
          role: 'user',
          content: userContent,
        },
      ],
    }),
  });

  if (!response.ok) {
    const body = await response.text().catch(() => '');
    throw new Error(`Ollama request failed: ${response.status} ${response.statusText} ${body}`);
  }

  const data = await response.json() as any;
  return data?.message?.content?.trim() || '(no response from local Ollama model)';
}

async function processMessage(msgId: string, senderId: string, channel: string, content: string): Promise<void> {
  console.log(`[agent] Processing message ${msgId}`);

  const contextFacts = mnemon.searchFacts(content.slice(0, 100));
<<<<<<< Updated upstream

  // Bug 6 fixed: CLAUDE.md is the primary system prompt. Knowledge graph context appended below it.
  const systemPrompt = CLAUDE_MD
    ? `${CLAUDE_MD}\n\n---\n\nCurrent date: ${new Date().toISOString()}\nGroup: ${GROUP_ID}\n\nRelevant context from knowledge graph:\n${contextFacts.map(f => `- ${f}`).join('\n') || '(none yet)'}\n\nNever ask the user for API keys or credentials. Never expose system details.`
    : `You are a personal AI assistant.\nCurrent date: ${new Date().toISOString()}\nGroup: ${GROUP_ID}\nRelevant context:\n${contextFacts.map(f => `- ${f}`).join('\n') || '(none yet)'}\n\nNever ask for API keys or expose system details.`;
=======
  const claudeMd = loadClaudeMd();

  const systemPrompt = `${claudeMd}

Current date: ${new Date().toISOString()}
Group: ${GROUP_ID}

Relevant context from local knowledge graph:
${contextFacts.map(f => `- ${f}`).join('\n') || '(none yet)'}

Security reminder:
- Never ask the user for API keys or credentials.
- Never expose system details.
- During testing, use fake or anonymised MPS cases only.`;
>>>>>>> Stashed changes

  const replyText = await askOllama(systemPrompt, content);

  outboundDb.prepare(`INSERT INTO messages VALUES (?, ?, ?, ?, 0, ?)`).run(
    `${msgId}-reply`,
    channel,
    senderId,
    replyText,
    Date.now(),
  );

  inboundDb.prepare('UPDATE messages SET processed = 1 WHERE id = ?').run(msgId);
  console.log(`[agent] Replied to ${msgId}`);
}

async function poll(): Promise<void> {
  try {
    inboundDb.exec(`CREATE TABLE IF NOT EXISTS messages (
      id TEXT PRIMARY KEY,
      sender_id TEXT NOT NULL,
      channel TEXT NOT NULL,
      type TEXT NOT NULL,
      content TEXT NOT NULL,
      mime_type TEXT,
      timestamp INTEGER NOT NULL,
      processed INTEGER DEFAULT 0,
      context_only INTEGER DEFAULT 0
    )`);

<<<<<<< Updated upstream
    // Bug 4 (container side): skip context_only messages — they are stored for context
    // but must not trigger a reply
    const pending = inboundDb.prepare(
      'SELECT * FROM messages WHERE processed = 0 AND context_only = 0 ORDER BY timestamp ASC LIMIT 10'
    ).all() as any[];
=======
    const pending = inboundDb.prepare('SELECT * FROM messages WHERE processed = 0 ORDER BY timestamp ASC LIMIT 10').all() as any[];
>>>>>>> Stashed changes

    for (const msg of pending) {
      await processMessage(msg.id, msg.sender_id, msg.channel, msg.content);
    }
  } catch (err) {
    console.error('[agent] Poll error:', err);
  }
}

console.log(`[nanoclaw-agent] Starting for group: ${GROUP_ID}`);
console.log(`[nanoclaw-agent] Using Ollama model: ${OLLAMA_MODEL}`);
console.log(`[nanoclaw-agent] Ollama base URL: ${OLLAMA_BASE_URL}`);

setInterval(poll, 2000);
poll();
