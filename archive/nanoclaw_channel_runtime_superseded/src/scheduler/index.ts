// Bug 8 fixed: scheduler callbacks now inject prompts into inbound.db via the router.
// Tasks are persisted to SQLite so they survive restarts.

import cron from 'node-cron';
import Database from 'better-sqlite3';
import { v4 as uuidv4 } from 'uuid';
import path from 'path';
import { logger } from '../logger';

const DATA_DIR = path.join(process.env.HOME || '/root', 'nanoclaw', 'data');
const db = new Database(path.join(DATA_DIR, 'tasks.db'));
db.pragma('journal_mode = WAL');

db.exec(`CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  cron_expr TEXT NOT NULL,
  group_id TEXT NOT NULL,
  prompt TEXT NOT NULL,
  enabled INTEGER DEFAULT 1,
  created_at INTEGER NOT NULL
)`);

export interface ScheduledTask {
  id: string;
  cronExpr: string;
  groupId: string;
  prompt: string;
}

const activeJobs = new Map<string, cron.ScheduledTask>();

export function startScheduler(): void {
  // Restore persisted tasks that were registered in a previous run
  const saved = db.prepare('SELECT * FROM tasks WHERE enabled = 1').all() as any[];
  for (const t of saved) {
    scheduleJob({ id: t.id, cronExpr: t.cron_expr, groupId: t.group_id, prompt: t.prompt });
  }
  logger.info({ count: saved.length }, 'Task scheduler started — restored persisted tasks');
}

function scheduleJob(task: ScheduledTask): void {
  if (!cron.validate(task.cronExpr)) {
    logger.warn({ task }, 'Invalid cron expression — task not scheduled');
    return;
  }

  const job = cron.schedule(task.cronExpr, async () => {
    logger.info({ taskId: task.id, groupId: task.groupId }, 'Scheduled task triggered');
    try {
      // Lazy import to avoid circular dependency at module load time
      const { router } = await import('../router');
      await router({
        id: uuidv4(),
        groupId: task.groupId,
        senderId: 'scheduler',
        channel: 'cli',
        type: 'text',
        content: task.prompt,
        timestamp: Date.now(),
      });
    } catch (err) {
      logger.error({ err, taskId: task.id }, 'Scheduled task failed to inject prompt');
    }
  });

  activeJobs.set(task.id, job);
  logger.info({ taskId: task.id, cronExpr: task.cronExpr }, 'Task scheduled');
}

export function registerTask(task: ScheduledTask): void {
  // Persist to SQLite
  db.prepare(`INSERT OR REPLACE INTO tasks (id, cron_expr, group_id, prompt, enabled, created_at)
              VALUES (?, ?, ?, ?, 1, ?)`)
    .run(task.id, task.cronExpr, task.groupId, task.prompt, Date.now());

  // Stop existing job if re-registering
  const existing = activeJobs.get(task.id);
  if (existing) existing.stop();

  scheduleJob(task);
  logger.info({ task }, 'Task registered and persisted');
}

export function pauseTask(taskId: string): boolean {
  const job = activeJobs.get(taskId);
  if (!job) return false;
  job.stop();
  db.prepare('UPDATE tasks SET enabled = 0 WHERE id = ?').run(taskId);
  logger.info({ taskId }, 'Task paused');
  return true;
}

export function resumeTask(taskId: string): boolean {
  const row = db.prepare('SELECT * FROM tasks WHERE id = ?').get(taskId) as any;
  if (!row) return false;
  db.prepare('UPDATE tasks SET enabled = 1 WHERE id = ?').run(taskId);
  scheduleJob({ id: row.id, cronExpr: row.cron_expr, groupId: row.group_id, prompt: row.prompt });
  logger.info({ taskId }, 'Task resumed');
  return true;
}

export function stopTask(taskId: string): boolean {
  const job = activeJobs.get(taskId);
  if (job) {
    job.stop();
    activeJobs.delete(taskId);
  }
  db.prepare('DELETE FROM tasks WHERE id = ?').run(taskId);
  logger.info({ taskId }, 'Task deleted');
  return true;
}

export function listTasks(): ScheduledTask[] {
  return (db.prepare('SELECT * FROM tasks WHERE enabled = 1 ORDER BY created_at ASC').all() as any[])
    .map(t => ({ id: t.id, cronExpr: t.cron_expr, groupId: t.group_id, prompt: t.prompt }));
}
