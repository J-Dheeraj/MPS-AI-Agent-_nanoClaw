// Bug 19 fixed: FTS5 external content table now has a DELETE trigger to keep the
//   full-text index in sync with the facts table. Without it, deleted rows left stale
//   FTS entries that caused incorrect JOIN results in searchFacts().
//
// Bug 20 fixed: WAL journal mode enabled so the container agent (writer) and any
//   external reader can access mnemon.db concurrently without SQLITE_BUSY errors.
//
// Bun fix: replaced better-sqlite3 (Node native addon) with bun:sqlite (built-in).

import { Database } from 'bun:sqlite';
import path from 'path';

const dbPath = path.join(process.env.GROUP_DIR || '/workspace/group', 'mnemon.db');
const db = new Database(dbPath);

// Bug 20: WAL mode for concurrent read/write access
db.run('PRAGMA journal_mode = WAL');

db.exec(`
  CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity TEXT NOT NULL,
    predicate TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL,
    timestamp INTEGER NOT NULL
  );

  CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts
    USING fts5(entity, predicate, value, content=facts, content_rowid=id);

  -- Bug 19: trigger to remove deleted facts from the FTS index.
  CREATE TRIGGER IF NOT EXISTS facts_fts_delete
    AFTER DELETE ON facts BEGIN
      INSERT INTO facts_fts(facts_fts, rowid, entity, predicate, value)
      VALUES('delete', old.id, old.entity, old.predicate, old.value);
    END;

  -- Trigger to keep FTS in sync on UPDATE as well (update = delete + insert in FTS5)
  CREATE TRIGGER IF NOT EXISTS facts_fts_update_delete
    AFTER UPDATE ON facts BEGIN
      INSERT INTO facts_fts(facts_fts, rowid, entity, predicate, value)
      VALUES('delete', old.id, old.entity, old.predicate, old.value);
    END;

  CREATE TRIGGER IF NOT EXISTS facts_fts_update_insert
    AFTER UPDATE ON facts BEGIN
      INSERT INTO facts_fts(rowid, entity, predicate, value)
      VALUES(new.id, new.entity, new.predicate, new.value);
    END;
`);

export const mnemon = {
  addFact(entity: string, predicate: string, value: string, source: string): void {
    const stmt = db.prepare(
      `INSERT INTO facts (entity, predicate, value, source, timestamp) VALUES (?, ?, ?, ?, ?)`
    );
    const info = stmt.run(entity, predicate, value, source, Date.now());
    db.prepare(
      `INSERT INTO facts_fts(rowid, entity, predicate, value) VALUES (?, ?, ?, ?)`
    ).run(info.lastInsertRowid, entity, predicate, value);
  },

  searchFacts(query: string): string[] {
    if (!query || query.trim() === '') return [];
    try {
      const rows = db.prepare(`
        SELECT f.entity, f.predicate, f.value FROM facts_fts
        JOIN facts f ON f.id = facts_fts.rowid
        WHERE facts_fts MATCH ? LIMIT 10
      `).all(query) as any[];
      return rows.map((r: any) => `${r.entity} ${r.predicate}: ${r.value}`);
    } catch {
      return [];
    }
  },

  deleteFact(id: number): void {
    db.prepare('DELETE FROM facts WHERE id = ?').run(id);
    // Trigger handles FTS cleanup automatically
  },
};
