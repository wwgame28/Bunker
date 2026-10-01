"""Single-process SQLite repository. All mutations and outgoing messages are atomic.
Replace this adapter for PostgreSQL; domain/handlers use the same transaction API.
"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA='''
CREATE TABLE IF NOT EXISTS rooms(code TEXT PRIMARY KEY, phase TEXT NOT NULL, chat_id INTEGER, state TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0);
CREATE UNIQUE INDEX IF NOT EXISTS one_live_group ON rooms(chat_id) WHERE phase != 'finished' AND chat_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, reachable INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS processed(key TEXT PRIMARY KEY, result TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, payload TEXT NOT NULL, room TEXT, status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, not_before REAL NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS outbox_due ON outbox(status,not_before,id);
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL);
INSERT INTO schema_version SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM schema_version);
'''

class Repository:
    def __init__(self,path):
        if path!=':memory:': Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path,timeout=10,isolation_level=None)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=10000')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript(SCHEMA)
        if self.db.execute('SELECT version FROM schema_version').fetchone()[0]!=1:
            raise RuntimeError('Unsupported database schema; restore or migrate before startup')

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield self
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK'); raise

    def get(self,code):
        row=self.db.execute('SELECT state FROM rooms WHERE code=?',(code,)).fetchone()
        return json.loads(row[0]) if row else None

    def save(self,r):
        self.db.execute('INSERT INTO rooms(code,phase,chat_id,state) VALUES(?,?,?,?) ON CONFLICT(code) DO UPDATE SET phase=excluded.phase,chat_id=excluded.chat_id,state=excluded.state,version=rooms.version+1',
                        (r['code'],r['phase'],r['chat_id'],json.dumps(r,ensure_ascii=False)))

    def rooms(self,live=False):
        sql='SELECT state FROM rooms'+(" WHERE phase != 'finished'" if live else '')+' ORDER BY rowid DESC'
        return [json.loads(x[0]) for x in self.db.execute(sql)]

    def mark(self,key,result=''):
        self.db.execute('INSERT INTO processed VALUES(?,?)',(key,result))

    def seen(self,key):
        return self.db.execute('SELECT result FROM processed WHERE key=?',(key,)).fetchone()

    def user(self,uid,name):
        self.db.execute('INSERT INTO users(id,name,reachable) VALUES(?,?,1) ON CONFLICT(id) DO UPDATE SET name=excluded.name,reachable=1',(int(uid),name[:40]))

    def reachable(self,uid):
        row=self.db.execute('SELECT reachable FROM users WHERE id=?',(int(uid),)).fetchone()
        return bool(row and row[0])

    def setting(self,key,default):
        row=self.db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self,key,value):
        self.db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(value)))

    def enqueue(self,chat,text,keyboard=None,room=None,kind='message'):
        from bunker.services.views import chunks
        parts=chunks(text)
        # Coalesce obsolete panels, but never narrative messages or character cards.
        if kind=='panel':
            self.db.execute("DELETE FROM outbox WHERE room=? AND chat_id=? AND status='pending' AND json_extract(payload,'$.kind')='panel'",(room,int(chat)))
        for i,part in enumerate(parts):
            payload={'text':part,'keyboard':keyboard if i==len(parts)-1 else None,'kind':kind}
            self.db.execute('INSERT INTO outbox(chat_id,payload,room) VALUES(?,?,?)',(int(chat),json.dumps(payload,ensure_ascii=False),room))

    def due(self,now):
        # One message per chat per pump; preserve ordering through transient failures.
        return self.db.execute("SELECT * FROM outbox o WHERE status='pending' AND not_before<=? AND NOT EXISTS(SELECT 1 FROM outbox older WHERE older.chat_id=o.chat_id AND older.id<o.id AND older.status='pending') ORDER BY id LIMIT 20",(now,)).fetchall()

    def complete(self,oid):
        self.db.execute('DELETE FROM outbox WHERE id=?',(oid,))

    def retry(self,oid,now,delay):
        self.db.execute('UPDATE outbox SET attempts=attempts+1,not_before=? WHERE id=?',(now+delay,oid))

    def dead(self,oid):
        self.db.execute("UPDATE outbox SET status='dead' WHERE id=?",(oid,))

    def close(self): self.db.close()
