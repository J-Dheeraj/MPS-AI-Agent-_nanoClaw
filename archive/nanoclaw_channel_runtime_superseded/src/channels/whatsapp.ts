// Bug 9 fixed: voice notes are now downloaded and transcribed via whisper.cpp.
// Requires: whisper-cpp binary in PATH inside the container, and ffmpeg for ogg→wav conversion.
// If transcription fails, falls back to a placeholder so the message is not silently dropped.

import { makeWASocket, DisconnectReason, useMultiFileAuthState, downloadMediaMessage } from '@whiskeysockets/baileys';
import qrcode from 'qrcode-terminal';
import path from 'path';
import os from 'os';
import fs from 'fs';
import { execFileSync } from 'child_process';
import { v4 as uuidv4 } from 'uuid';
import { InboundMessage } from '../router';
import { registerSender } from '../delivery';
import { logger } from '../logger';

const AUTH_DIR = path.join(process.env.HOME || '/root', 'nanoclaw', 'data', 'whatsapp-auth');

const WHISPER_BIN = process.env.WHISPER_BIN || 'whisper-cpp';
const WHISPER_MODEL = process.env.WHISPER_MODEL || '/app/models/ggml-base.bin';

async function transcribeAudio(buffer: Buffer, ext = 'ogg'): Promise<string> {
  const tmpId = uuidv4();
  const audioPath = path.join(os.tmpdir(), `voice-${tmpId}.${ext}`);
  const wavPath = path.join(os.tmpdir(), `voice-${tmpId}.wav`);
  try {
    fs.writeFileSync(audioPath, buffer);
    // Convert to wav — whisper.cpp requires 16kHz mono wav
    try {
      execFileSync('ffmpeg', ['-i', audioPath, '-ar', '16000', '-ac', '1', wavPath, '-y'], {
        stdio: 'pipe',
        timeout: 30_000,
      });
    } catch {
      // ffmpeg not available — attempt to pass raw audio directly to whisper
      fs.copyFileSync(audioPath, wavPath);
    }
    const result = execFileSync(WHISPER_BIN, [
      '-m', WHISPER_MODEL,
      '-f', wavPath,
      '--output-txt',
      '--no-timestamps',
      '--language', 'auto',
    ], { encoding: 'utf8', timeout: 60_000 });
    return result.trim() || '[voice note — empty transcription]';
  } catch (err: any) {
    logger.warn({ err: err.message }, 'Voice transcription failed');
    return '[voice note — transcription failed]';
  } finally {
    try { fs.unlinkSync(audioPath); } catch {}
    try { fs.unlinkSync(wavPath); } catch {}
  }
}

export async function startWhatsApp(router: (msg: InboundMessage) => Promise<void>): Promise<void> {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);

  const sock = makeWASocket({ auth: state, printQRInTerminal: false });

  sock.ev.on('creds.update', saveCreds);

  // Bug 7 (partial): register WhatsApp as a delivery channel
  registerSender('whatsapp', async (recipientId, content) => {
    await sock.sendMessage(recipientId, { text: content });
  });

  sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect, qr } = update;
    if (qr) {
      console.log('\nScan this QR code with WhatsApp (Settings → Linked Devices → Link a Device):\n');
      qrcode.generate(qr, { small: true });
    }
    if (connection === 'close') {
      const shouldReconnect = (lastDisconnect?.error as any)?.output?.statusCode !== DisconnectReason.loggedOut;
      logger.info('WhatsApp disconnected. Reconnecting:', shouldReconnect);
      if (shouldReconnect) startWhatsApp(router);
    } else if (connection === 'open') {
      logger.info('WhatsApp connected');
    }
  });

  sock.ev.on('messages.upsert', async ({ messages }) => {
    for (const m of messages) {
      if (m.key.fromMe) continue;
      const remoteJid = m.key.remoteJid || '';
      const senderId = m.key.participant || remoteJid;
      const groupId = remoteJid.endsWith('@g.us')
        ? `whatsapp_${remoteJid.split('@')[0]}`
        : 'main';

      let content = m.message?.conversation || m.message?.extendedTextMessage?.text || '';
      let type: InboundMessage['type'] = 'text';
      let mimeType: string | undefined;

      if (m.message?.audioMessage) {
        type = 'voice';
        mimeType = 'audio/ogg';
        try {
          const buffer = await downloadMediaMessage(m, 'buffer', {}) as Buffer;
          content = await transcribeAudio(buffer, 'ogg');
        } catch {
          content = '[voice note — download failed]';
        }
      } else if (m.message?.imageMessage) {
        type = 'image';
        mimeType = 'image/jpeg';
        content = '[image]';
      }

      if (!content) continue;

      await router({
        id: m.key.id || uuidv4(),
        groupId,
        senderId,
        channel: 'whatsapp',
        type,
        content,
        mimeType,
        timestamp: (m.messageTimestamp as number) * 1000,
      });
    }
  });
}
