// Bug 13 fixed: replaced --network host with a dedicated bridge network (nanoclaw-net).
//   --network host gave containers access to every port on the host. nanoclaw-net
//   restricts reachable hosts, while --add-host=host.docker.internal:host-gateway
//   still lets containers reach OneCLI at host.docker.internal:<port>.
//
// Bug 15 fixed: validateGroupName() called inside ensureRunning() as defence-in-depth.
//   Previously the runner trusted that callers had validated the groupId upstream.
//
// Bug 16 fixed: startup lock (this.starting Set) prevents two concurrent callers from
//   racing to spin up the same container. docker rm now uses -f only on confirmed-stopped
//   containers, not unconditionally.

import { execSync } from 'child_process';
import path from 'path';
import { logger } from '../logger';
import { validateMountPath } from '../security/mountAllowlist';
import { validateGroupName } from '../security/groupNames';

const GROUPS_DIR = path.join(process.env.HOME || '/root', 'nanoclaw', 'groups');
<<<<<<< Updated upstream
const ONECLI_PORT = parseInt(process.env.ONECLI_PORT || '4891');
const DOCKER_NETWORK = 'nanoclaw-net';

function ensureDockerNetwork(): void {
  try {
    execSync(`docker network inspect ${DOCKER_NETWORK}`, { stdio: 'pipe' });
  } catch {
    // Network does not exist — create it
    execSync(`docker network create ${DOCKER_NETWORK}`);
    logger.info({ network: DOCKER_NETWORK }, 'Docker bridge network created');
  }
}
=======
const ONECLI_PORT = parseInt(process.env.ONECLI_PORT || '10255');
>>>>>>> Stashed changes

export class ContainerRunner {
  private running = new Map<string, string>(); // groupId -> containerId
  private starting = new Set<string>();         // Bug 16: startup lock per groupId

  constructor() {
    ensureDockerNetwork();
  }

  async ensureRunning(groupId: string): Promise<void> {
    // Bug 15: validate groupId here as defence-in-depth — do not rely solely on router
    if (!validateGroupName(groupId)) {
      throw new Error(`ContainerRunner: invalid group name "${groupId}"`);
    }

    // Bug 16: if another caller is already starting this group's container, do nothing
    if (this.starting.has(groupId)) {
      logger.debug({ groupId }, 'Container startup already in progress — skipping duplicate start');
      return;
    }

    if (this.running.has(groupId)) {
      // Check if still alive
      try {
        const out = execSync(
          `docker inspect -f '{{.State.Running}}' ${this.running.get(groupId)}`,
          { stdio: 'pipe' }
        ).toString().trim();
        if (out === 'true') return;
      } catch {
        this.running.delete(groupId);
      }
    }

    // Acquire startup lock
    this.starting.add(groupId);

    try {
      const groupDir = path.join(GROUPS_DIR, groupId);

      if (!validateMountPath(groupDir)) {
        throw new Error(`Mount denied for group directory: ${groupDir}`);
      }

      const containerName = `nanoclaw-agent-${groupId}`;

      // Bug 16: only remove the container if it exists and is NOT running
      // (avoids killing a just-started container if two callers race)
      try {
        const state = execSync(
          `docker inspect -f '{{.State.Running}}' ${containerName} 2>/dev/null`,
          { stdio: 'pipe' }
        ).toString().trim();
        if (state !== 'true') {
          execSync(`docker rm ${containerName}`, { stdio: 'pipe' });
        }
      } catch {
        // Container does not exist — nothing to remove
      }

      const args = [
        'run', '-d',
        '--name', containerName,
        // Bug 13: dedicated bridge network instead of --network host
        '--network', DOCKER_NETWORK,
        // Allows containers to reach the host (OneCLI) via host.docker.internal on Linux/WSL2
        '--add-host', 'host.docker.internal:host-gateway',
        '--env', `ONECLI_PROXY=http://host.docker.internal:${ONECLI_PORT}`,
        '--env', `GROUP_ID=${groupId}`,
        '--env', `GROUP_DIR=/workspace/group`,
        '--env', `ANTHROPIC_BASE_URL=http://host.docker.internal:${ONECLI_PORT}`,
        '-v', `${groupDir}:/workspace/group`,
        'nanoclaw-agent:latest',
      ];

      logger.info({ groupId, containerName }, 'Spawning agent container');
      const result = execSync(`docker ${args.join(' ')}`).toString().trim();
      this.running.set(groupId, result);
      logger.info({ groupId, containerId: result }, 'Container started');
    } finally {
      // Always release the startup lock
      this.starting.delete(groupId);
    }
<<<<<<< Updated upstream
=======

    const containerName = `nanoclaw-agent-${groupId}`;

    // Remove stopped container if exists
    try { execSync(`docker rm -f ${containerName} 2>/dev/null`); } catch {}

    const args = [
      'run',
      '--add-host', 'host.docker.internal:host-gateway', '-d',
      '--name', containerName,
      '--network', 'host',  // shares host network so OneCLI proxy is reachable
      '--env', `ONECLI_PROXY=http://127.0.0.1:${ONECLI_PORT}`,
      '--env', `GROUP_ID=${groupId}`,
      '--env', `GROUP_DIR=/workspace/group`,
      '--env', `HTTPS_PROXY=http://127.0.0.1:${ONECLI_PORT}`,
      '--env', `HTTP_PROXY=http://127.0.0.1:${ONECLI_PORT}`,
      '--env', 'ANTHROPIC_BASE_URL=https://api.anthropic.com',
      '-v', `${groupDir}:/workspace/group`,
      'nanoclaw-agent:latest',
    ];

    logger.info({ groupId, containerName }, 'Spawning agent container');
    const result = execSync(`docker ${args.join(' ')}`).toString().trim();
    this.running.set(groupId, result);
    logger.info({ groupId, containerId: result }, 'Container started');
>>>>>>> Stashed changes
  }
}
