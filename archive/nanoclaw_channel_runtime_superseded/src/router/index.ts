import path from 'path';
import fs from 'fs';
import Database from 'better-sqlite3';
import { logger } from '../logger';
import { validateGroupName } from '../security/groupNames';
import { checkSenderAllowed } from '../security/senderAllowlist';
import { ContainerRunner } from '../container/runner';

const GROUPS_DIR = path.join(process.env.HOME || '/root', 'nanoclaw', 'groups');

const containerRunner = new ContainerRunner();

export interface InboundMessage {
  id: string;
  groupId: string;
  senderId: string;
  channel: 'whatsapp' | 'telegram' | 'webui' | 'cli';
  type: 'text' | 'voice' | 'image' | 'document';
  content: string;         // text content or base64 for binary
  mimeType?: string;
  timestamp: number;
}

export async function router(msg: InboundMessage): Promise<void> {
  // Validate group name
  if (!validateGroupName(msg.groupId)) {
    logger.warn({ groupId: msg.groupId }, 'Rejected: invalid group name');
    return;
  }

  // Bug 4 fixed: handle tri-state sender decision
  const decision = checkSenderAllowed(msg.groupId, msg.senderId);

  if (decision === 'drop') {
    logger.info({ senderId: msg.senderId, groupId: msg.groupId }, 'Dropped: sender not in allowlist (drop mode)');
    return;
  }

  // Ensure group directory exists
  const groupDir = path.join(GROUPS_DIR, msg.groupId);
  if (!fs.existsSync(groupDir)) {
    fs.mkdirSync(groupDir, { recursive: true });
  }

  // Write to inbound.db — context-only messages are stored but won't trigger the agent
  const db = new Database(path.join(groupDir, 'inbound.db'));
  db.pragma('journal_mode = WAL'); // Bug 20 (partial): WAL for concurrent host+container access
  db.exec(`CREATE TABLE IF NOT EXISTS messages (
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

  db.prepare(`INSERT OR IGNORE INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)`)
    .run(
      msg.id, msg.senderId, msg.channel, msg.type, msg.content,
      msg.mimeType ?? null, msg.timestamp,
      decision === 'context' ? 1 : 0,
    );
  db.close();

  if (decision === 'context') {
    logger.info({ senderId: msg.senderId, groupId: msg.groupId }, 'Stored for context: non-trigger sender (trigger mode)');
    return; // Do not start/notify container
  }

  // 'allow' — ensure container is running and will process this message
  await containerRunner.ensureRunning(msg.groupId);
}
