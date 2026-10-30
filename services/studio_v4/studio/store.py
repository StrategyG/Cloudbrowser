"""SQLite-backed assets, immutable stage IDs, durable queued jobs, and approvals."""
import json
import sqlite3
import time
import uuid
from .settings import DATABASE, DATA_ROOT

STATES = ('uploaded','mesh_building','mesh_review','mesh_approved','rig_building','rig_review','rig_approved','manifest_review','manifest_approved','rendering','completed','failed')
TRANSITIONS = {
 'uploaded': {'mesh_building','mesh_review'},
 'mesh_building': {'mesh_review','failed'},
 'mesh_review': {'mesh_approved','mesh_building'},
 'mesh_approved': {'rig_building'},
 'rig_building': {'rig_review','failed'},
 'rig_review': {'rig_approved','rig_building'},
 'rig_approved': {'manifest_review'},
 'manifest_review': {'manifest_approved','rig_approved'},
 'manifest_approved': {'rendering','manifest_review'},
 'rendering': {'completed','failed'},
 'completed': {'manifest_review'},
 'failed': {'mesh_building','rig_building','rendering'},
}

def conn():
 c = sqlite3.connect(DATABASE, timeout=10)
 c.row_factory = sqlite3.Row
 c.execute('PRAGMA journal_mode=WAL')
 c.execute('PRAGMA foreign_keys=ON')
 return c

def init():
 with conn() as c:
  c.execute('''CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, state TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}',
    sha256 TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL)''')
  c.execute('''CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), kind TEXT NOT NULL,
    state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL, updated_at REAL NOT NULL)''')

def create_project(name, sha256):
 pid = uuid.uuid4().hex
 now = time.time()
 (DATA_ROOT / pid).mkdir(parents=True, exist_ok=False)
 with conn() as c:
  c.execute('INSERT INTO projects(id,name,state,sha256,created_at,updated_at) VALUES(?,?,?,?,?,?)',
            (pid,name,'uploaded',sha256,now,now))
 return pid

def get_project(pid):
 with conn() as c:
  row = c.execute('SELECT * FROM projects WHERE id=?',(pid,)).fetchone()
 return dict(row) if row else None

def read_metadata(pid):
 p = get_project(pid)
 if p is None: raise LookupError('project not found')
 return json.loads(p['metadata'])

def update_metadata(pid, **fields):
 with conn() as c:
  row=c.execute('SELECT metadata FROM projects WHERE id=?',(pid,)).fetchone()
  if not row: raise LookupError('project not found')
  d=json.loads(row['metadata']); d.update(fields)
  c.execute('UPDATE projects SET metadata=?,updated_at=? WHERE id=?', (json.dumps(d),time.time(),pid))

def change_state(pid, expected, new):
 if new not in TRANSITIONS.get(expected,set()): raise ValueError('illegal state transition')
 with conn() as c:
  cursor=c.execute('UPDATE projects SET state=?,updated_at=? WHERE id=? AND state=?',(new,time.time(),pid,expected))
  if cursor.rowcount!=1: raise ValueError('project state changed; reload first')

def enqueue(pid, kind, expected, running_state):
 if running_state not in TRANSITIONS.get(expected,set()):raise ValueError('illegal state transition')
 jid=uuid.uuid4().hex; now=time.time()
 with conn() as c:
  changed=c.execute('UPDATE projects SET state=?,updated_at=? WHERE id=? AND state=?',(running_state,now,pid,expected))
  if changed.rowcount!=1:raise ValueError('project state changed; reload first')
  c.execute('INSERT INTO jobs(id,project_id,kind,state,created_at,updated_at) VALUES(?,?,?,?,?,?)',(jid,pid,kind,'queued',now,now))
 return jid

def claim_job():
 with conn() as c:
  c.execute('BEGIN IMMEDIATE')
  row=c.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created_at LIMIT 1").fetchone()
  if row is None: return None
  c.execute("UPDATE jobs SET state='running',attempts=attempts+1,updated_at=? WHERE id=? AND state='queued'",(time.time(),row['id']))
  return dict(row)

def finish_job(jid, ok, message=''):
 with conn() as c:
  c.execute('UPDATE jobs SET state=?,message=?,updated_at=? WHERE id=?',('done' if ok else 'failed',message[:3000],time.time(),jid))

def jobs(pid):
 with conn() as c:
  return [dict(r) for r in c.execute('SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC LIMIT 20',(pid,))]
