import fs from 'fs';
import path from 'path';
import { logger } from '../logger';

interface MountAllowlist {
  allowedPaths: string[];
  blockedPatterns: string[];
}

function loadConfig(): MountAllowlist | null {
  const configPath = path.join(process.env.HOME || '/root', '.config', 'nanoclaw', 'mount-allowlist.json');
  try {
    return JSON.parse(fs.readFileSync(configPath, 'utf8'));
  } catch {
    logger.warn('mount-allowlist.json not found');
    return null;
  }
}

export function validateMountPath(mountPath: string): boolean {
  const config = loadConfig();
  if (!config) return false; // deny by default if no config

  // Bug 10 fixed: use anchored regex to expand only a leading ~
  const home = process.env.HOME || '/root';
  const allowedResolved = config.allowedPaths.map(p => p.replace(/^~/, home));

  // Bug 2 fixed: path-safe prefix check — require trailing slash or exact match
  // Prevents "/home/user/nanoclaw/groups-evil" from matching "/home/user/nanoclaw/groups"
  const isAllowed = allowedResolved.some(allowed => {
    const normalised = allowed.endsWith(path.sep) ? allowed : allowed + path.sep;
    return mountPath === allowed || mountPath.startsWith(normalised);
  });
  if (!isAllowed) return false;

  const isBlocked = config.blockedPatterns.some(pattern => {
    if (pattern.startsWith('*.')) {
      return mountPath.endsWith(pattern.slice(1));
    }
    return mountPath.includes(pattern);
  });

  return !isBlocked;
}
