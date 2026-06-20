// Bug 7 (partial): CLI registered as a delivery channel so scheduler-injected prompts
//   and any replies routed back to 'cli' are printed to stdout.

import readline from 'readline';
import { v4 as uuidv4 } from 'uuid';
import { InboundMessage } from '../router';
import { registerSender } from '../delivery';
import { logger } from '../logger';

export function startCLI(router: (msg: InboundMessage) => Promise<void>): void {
  // Register CLI as a delivery channel — replies from scheduler tasks appear on stdout
  registerSender('cli', async (_recipientId, content) => {
    console.log(`\n[nanoclaw] ${content}\n`);
  });

  if (!process.stdin.isTTY) return;

  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  rl.setPrompt('nanoclaw> ');
  rl.prompt();

  rl.on('line', async (line) => {
    const content = line.trim();
    if (!content) { rl.prompt(); return; }

    const msg: InboundMessage = {
      id: uuidv4(),
      groupId: 'main',
      senderId: 'cli-user',
      channel: 'cli',
      type: 'text',
      content,
      timestamp: Date.now(),
    };

    try {
      await router(msg);
    } catch (err) {
      logger.error(err);
    }
    rl.prompt();
  });
}
