import path from 'path';
import fs from 'fs';
import { router } from './router';
import { startWebUI } from './channels/webui';
import { startCLI } from './channels/cli';
import { startDelivery } from './delivery';
import { startScheduler } from './scheduler';
import { logger } from './logger';

const DATA_DIR = path.join(process.env.HOME || '/root', 'nanoclaw', 'data');
const GROUPS_DIR = path.join(process.env.HOME || '/root', 'nanoclaw', 'groups');

[DATA_DIR, GROUPS_DIR, path.join(DATA_DIR, 'ipc')].forEach(d => {
  if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true });
});

async function main() {
  logger.info('NanoClaw v2 starting...');

  startDelivery();
  startScheduler();
  startWebUI(router);
  startCLI(router);

  // WhatsApp and Telegram start lazily via /add-whatsapp and /add-telegram commands
  logger.info('NanoClaw v2 ready. Web UI: http://localhost:3080');
}

main().catch(err => {
  logger.error(err, 'Fatal startup error');
  process.exit(1);
});
