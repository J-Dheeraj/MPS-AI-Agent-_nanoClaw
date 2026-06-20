import fs from 'fs';
import path from 'path';
import Database from 'better-sqlite3';
import { logger } from '../logger';
import { validateGroupName } from '../security/groupNames';

const GROUPS_DIR = path.join(process.env.HOME || '/root', 'nanoclaw', 'groups');

// Bug 7 fixed: channel sender registry — channels register themselves here on startup.
// Delivery calls the registered sender rather than logging and marking sent immediately.
type ChannelSender = (recipientId: string, content: string) => Promise<void>;
const channelSenders = new Map<string, ChannelSender>();

export function registerSender(channel: string, fn: ChannelSender): void {
  channelSenders.set(channel, fn);
  logger.info({ channel }, 'Channel sender registered');
}

interface OutboundMessage {
  id: string;
  channel: string;
  recipient_id: string;
  content: string;
  sent: number;
  timestamp: number;
}

export function startDelivery(): void {
  setInterval(() => pollAllGroups(), 1000);
}

function pollAllGroups(): void {
  if (!fs.existsSync(GROUPS_DIR)) return;
  const entries = fs.readdirSync(GROUPS_DIR);
  for (const group of entries) {
    // Bug 3 fixed: validate group name before using as a path component
    if (!validateGroupName(group)) {
      logger.warn({ group }, 'Skipping directory with invalid group name in delivery poll');
      continue;
    }
    const outboundPath = path.join(GROUPS_DIR, group, 'outbound.db');
    if (!fs.existsSync(outboundPath)) continue;
    try {
      deliverPending(group, outboundPath);
    } catch (err) {
      logger.error({ err, group }, 'Delivery error');
    }
  }
}

function deliverPending(groupId: string, dbPath: string): void {
  const db = new Database(dbPath);
  db.pragma('journal_mode = WAL'); // Bug 20 (partial): WAL mode for concurrent access
  db.exec(`CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    recipient_id TEXT NOT NULL,
    content TEXT NOT NULL,
    sent INTEGER DEFAULT 0,
    timestamp INTEGER NOT NULL
  )`);

  const pending = db.prepare('SELECT * FROM messages WHERE sent = 0').all() as OutboundMessage[];
  for (const msg of pending) {
    const sender = channelSenders.get(msg.channel);
    if (!sender) {
      // Channel not yet registered (e.g. WhatsApp not paired) — leave unsent, retry next poll
      logger.debug({ groupId, channel: msg.channel }, 'No sender registered for channel — will retry');
      continue;
    }
    sender(msg.recipient_id, msg.content)
      .then(() => {
        db.prepare('UPDATE messages SET sent = 1 WHERE id = ?').run(msg.id);
        logger.info({ groupId, channel: msg.channel, recipient: msg.recipient_id }, 'Message delivered');
      })
      .catch((err) => {
        logger.error({ err, msgId: msg.id }, 'Failed to deliver message — will retry next poll');
        // Do NOT mark sent=1 — leave it for retry
      });
  }
  db.close();
}
