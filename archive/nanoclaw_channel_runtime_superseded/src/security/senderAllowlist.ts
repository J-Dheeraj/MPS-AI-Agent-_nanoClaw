import fs from 'fs';
import path from 'path';
import { logger } from '../logger';

interface GroupAllowlist {
  mode: 'drop' | 'trigger';
  allowedSenders: string[];
}

interface AllowlistConfig {
  defaultMode: 'drop' | 'trigger';
  groups: Record<string, GroupAllowlist>;
}

// Bug 11 fixed: cache config at load time — reload only on SIGHUP, not per message.
let cachedConfig: AllowlistConfig | null | undefined = undefined; // undefined = not yet loaded

function getConfig(): AllowlistConfig | null {
  if (cachedConfig === undefined) {
    cachedConfig = loadConfig();
  }
  return cachedConfig;
}

function loadConfig(): AllowlistConfig | null {
  const configPath = path.join(process.env.HOME || '/root', '.config', 'nanoclaw', 'sender-allowlist.json');
  try {
    return JSON.parse(fs.readFileSync(configPath, 'utf8'));
  } catch {
    logger.warn('sender-allowlist.json not found — all senders allowed (configure before going live)');
    return null;
  }
}

// Reload config on SIGHUP (e.g. after editing sender-allowlist.json without restarting)
process.on('SIGHUP', () => {
  cachedConfig = undefined;
  logger.info('Sender allowlist cache cleared — will reload on next check');
});

// Bug 4 fixed: tri-state return — 'allow' triggers the agent, 'context' stores for context
// only (does not trigger), 'drop' discards the message entirely.
// Previously both 'drop' and 'trigger' modes returned false, making trigger dead code.
export type SenderDecision = 'allow' | 'context' | 'drop';

export function checkSenderAllowed(groupId: string, senderId: string): SenderDecision {
  const config = getConfig();
  if (!config) return 'allow'; // permissive until configured

  const groupConfig = config.groups[groupId];
  const mode = groupConfig?.mode ?? config.defaultMode;
  const allowedSenders = groupConfig?.allowedSenders ?? [];

  if (allowedSenders.includes(senderId)) return 'allow';
  if (mode === 'drop') return 'drop';
  return 'context'; // trigger mode: store for context, do not activate the agent
}
