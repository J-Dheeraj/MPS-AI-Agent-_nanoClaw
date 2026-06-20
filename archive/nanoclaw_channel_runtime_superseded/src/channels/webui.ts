// Bug 18 fixed: validate `type` and `groupId` at the API boundary, not just inside router.
//   - Unknown `type` values now return HTTP 400 instead of being silently passed through.
//   - Invalid `groupId` now returns HTTP 400 with a clear message instead of HTTP 500.
//   Bug 7 (partial): webui delivery registered so replies can reach the polling endpoint.

import express from 'express';
import cors from 'cors';
import path from 'path';
import { v4 as uuidv4 } from 'uuid';
import { InboundMessage } from '../router';
import { registerSender } from '../delivery';
import { validateGroupName } from '../security/groupNames';
import { logger } from '../logger';

const WEB_HOST = process.env.WEB_HOST || '127.0.0.1';
const WEB_PORT = parseInt(process.env.WEB_PORT || '3080');

const VALID_TYPES: InboundMessage['type'][] = ['text', 'voice', 'image', 'document'];

// Pending replies for long-poll delivery (webui has no persistent connection)
const pendingReplies = new Map<string, string[]>(); // groupId -> queued reply texts

export function startWebUI(router: (msg: InboundMessage) => Promise<void>): void {
  const app = express();
  app.use(cors({ origin: false })); // no CORS — localhost only
  app.use(express.json({ limit: '10mb' }));
  app.use(express.static(path.join(__dirname, '../../public')));

  // Bug 7 (partial): register webui as a delivery channel — replies are queued for polling
  registerSender('webui', async (recipientId, content) => {
    const groupId = recipientId.includes('@') ? recipientId.split('@')[0] : recipientId;
    const queue = pendingReplies.get(groupId) ?? [];
    queue.push(content);
    pendingReplies.set(groupId, queue);
  });

  app.post('/api/message', async (req, res) => {
    const { content, type = 'text', groupId = 'main' } = req.body;

    if (!content || typeof content !== 'string') {
      return res.status(400).json({ error: 'content is required and must be a string' });
    }

    // Bug 18: validate type at API boundary
    if (!VALID_TYPES.includes(type)) {
      return res.status(400).json({ error: `invalid type "${type}" — must be one of: ${VALID_TYPES.join(', ')}` });
    }

    // Bug 18: validate groupId at API boundary with a proper 400, not a 500 from inside router
    if (!validateGroupName(groupId)) {
      return res.status(400).json({ error: `invalid groupId "${groupId}" — only alphanumeric, hyphens, and underscores allowed` });
    }

    const msg: InboundMessage = {
      id: uuidv4(),
      groupId,
      senderId: 'webui-user',
      channel: 'webui',
      type,
      content,
      timestamp: Date.now(),
    };

    try {
      await router(msg);
      res.json({ ok: true, id: msg.id });
    } catch (err) {
      logger.error(err);
      res.status(500).json({ error: 'routing failed' });
    }
  });

  // Long-poll endpoint — web UI calls this to receive queued replies
  app.get('/api/replies/:groupId', (req, res) => {
    const { groupId } = req.params;
    if (!validateGroupName(groupId)) {
      return res.status(400).json({ error: 'invalid groupId' });
    }
    const replies = pendingReplies.get(groupId) ?? [];
    pendingReplies.set(groupId, []);
    res.json({ replies });
  });

  app.listen(WEB_PORT, WEB_HOST, () => {
    logger.info(`Web UI listening on http://${WEB_HOST}:${WEB_PORT}`);
  });
}
