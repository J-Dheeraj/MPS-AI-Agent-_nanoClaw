// Bug 9 fixed: voice notes are downloaded and transcribed via whisper.cpp.
// Bug 7 (partial): Telegram registered as a delivery channel sender.

import TelegramBot from 'node-telegram-bot-api';
import { v4 as uuidv4 } from 'uuid';
import path from 'path';
import os from 'os';
import fs from 'fs';
import { execFileSync } from 'child_process';
import { InboundMessage } from '../router';
import { registerSender } from '../delivery';
import { logger } from '../logger';

const WHISPER_BIN = process.env.WHISPER_BIN || 'whisper-cpp';
const WHISPER_MODEL = process.env.WHISPER_MODEL || '/app/models/ggml-base.bin';

async function transcribeOggBuffer(buffer: Buffer): Promise<string> {
  const tmpId = uuidv4();
  const audioPath = path.join(os.tmpdir(), `tg-voice-${tmpId}.ogg`);
  const wavPath = path.join(os.tmpdir(), `tg-voice-${tmpId}.wav`);
  try {
    fs.writeFileSync(audioPath, buffer);
    try {
      execFileSync('ffmpeg', ['-i', audioPath, '-ar', '16000', '-ac', '1', wavPath, '-y'], {
        stdio: 'pipe', timeout: 30_000,
      });
    } catch {
      fs.copyFileSync(audioPath, wavPath);
    }
    const result = execFileSync(WHISPER_BIN, [
      '-m', WHISPER_MODEL,
      '-f', wavPath,
      '--output-txt', '--no-timestamps', '--language', 'auto',
    ], { encoding: 'utf8', timeout: 60_000 });
    return result.trim() || '[voice note — empty transcription]';
  } catch (err: any) {
    logger.warn({ err: err.message }, 'Telegram voice transcription failed');
    return '[voice note — transcription failed]';
  } finally {
    try { fs.unlinkSync(audioPath); } catch {}
    try { fs.unlinkSync(wavPath); } catch {}
  }
}

export function startTelegram(token: string, router: (msg: InboundMessage) => Promise<void>): void {
  const bot = new TelegramBot(token, { polling: true });
  logger.info('Telegram bot started');

  // Bug 7 (partial): register Telegram as a delivery channel sender
  registerSender('telegram', async (recipientId, content) => {
    const [telegramId] = recipientId.split('@');
    await bot.sendMessage(parseInt(telegramId, 10), content);
  });

  bot.on('message', async (msg) => {
    const senderId = `${msg.from?.id}@telegram`;
    const chatRecipient = `${msg.chat.id}@telegram`;
    const groupId = msg.chat.type === 'private'
      ? 'main'
      : `telegram_${Math.abs(msg.chat.id)}`;

    let type: InboundMessage['type'] = 'text';
    let content = msg.text || '';

    if (msg.voice) {
      type = 'voice';
      try {
        const fileLink = await bot.getFileLink(msg.voice.file_id);
        const res = await fetch(fileLink);
        const buffer = Buffer.from(await res.arrayBuffer());
        content = await transcribeOggBuffer(buffer);
      } catch {
        content = '[voice note — download failed]';
      }
    } else if (msg.photo) {
      type = 'image';
      content = '[image]';
    } else if (msg.document) {
      type = 'document';
      content = `[document: ${msg.document.file_name}]`;
    }

    if (!content) return;

    await router({
      id: uuidv4(),
      groupId,
      senderId,
      channel: 'telegram',
      type,
      content,
      timestamp: msg.date * 1000,
    });
  });
}
