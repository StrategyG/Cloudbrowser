"""Security and deterministic state machine for CloudBrowser's Godot adapter."""
from __future__ import annotations
import json, os, re, sqlite3, struct, time, uuid
from pathlib import Path

ROOT = Path(os.getenv('CLOUDBROWSER_DATA', '/data')).resolve()
MAX_GLB_BYTES = 32 * 1024 * 1024
MAX_FRAMES = 900


def connection():
    ROOT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(ROOT / 'jobs.sqlite3', timeout=15, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout = 15000')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('''CREATE TABLE IF NOT EXISTS projects(
      id TEXT PRIMARY KEY, state TEXT NOT NULL, manifest TEXT,
      qa TEXT NOT NULL, error TEXT, created REAL NOT NULL, updated REAL NOT NULL)''')
    return db


def get_project(pid):
    if not re.fullmatch(r'[a-f0-9]{32}', pid):
        raise ValueError('Invalid project ID')
    with connection() as db:
        row = db.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone()
    if row is None: raise LookupError('Project not found')
    value = dict(row)
    value['qa'] = json.loads(value['qa'])
    value['manifest'] = json.loads(value['manifest']) if value['manifest'] else None
    return value


def transition(pid, allowed_states, state, *, manifest=None, error=None):
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT state FROM projects WHERE id=?', (pid,)).fetchone()
        if row is None or row['state'] not in allowed_states:
            db.rollback()
            raise ValueError('Invalid state transition')
        if manifest is not None:
            db.execute('UPDATE projects SET state=?,manifest=?,error=?,updated=? WHERE id=?',
                       (state, json.dumps(manifest), error, time.time(), pid))
        else:
            db.execute('UPDATE projects SET state=?,error=?,updated=? WHERE id=?',
                       (state,error,time.time(),pid))
        db.commit()


def validate_glb(blob):
    if len(blob) > MAX_GLB_BYTES: raise ValueError('GLB exceeds 32 MB')
    if len(blob) < 20 or blob[:4] != b'glTF': raise ValueError('Not a GLB file')
    version, length = struct.unpack_from('<II', blob, 4)
    if version != 2 or length != len(blob): raise ValueError('Invalid GLB header/length')
    size, kind = struct.unpack_from('<I4s', blob, 12)
    if kind != b'JSON' or size > len(blob)-20 or size % 4: raise ValueError('Invalid GLB JSON chunk')
    try: doc = json.loads(blob[20:20+size].decode('utf-8'))
    except Exception as e: raise ValueError('Invalid glTF JSON') from e
    if not isinstance(doc, dict) or doc.get('asset', {}).get('version') != '2.0':
        raise ValueError('Invalid glTF asset version')
    if not doc.get('meshes') or not doc.get('scenes'): raise ValueError('No mesh or scene')
    if not doc.get('skins'): raise ValueError('Rigged GLB with skin required')
    nodes = doc.get('nodes') or []
    for skin in doc['skins']:
        joints = skin.get('joints') or []
        if not joints or any(not isinstance(i, int) or i < 0 or i >= len(nodes) for i in joints):
            raise ValueError('Invalid skin joint references')
    for item in doc.get('buffers', []) + doc.get('images', []):
        if item.get('uri'): raise ValueError('External resource URI disallowed')
    return {'meshes':len(doc['meshes']), 'skins':len(doc['skins']),
            'joints':sum(len(s['joints']) for s in doc['skins']),
            'note':'Structural preflight only; deform/visual QA needs Godot'}


def validate_manifest(data):
    if not isinstance(data, dict): raise ValueError('Manifest must be an object')
    keys = {'action','fps','duration','width','height','character'}
    if set(data) != keys: raise ValueError('Manifest fields must be '+', '.join(sorted(keys)))
    if data['action'] not in ('idle','walk','wave','jump'): raise ValueError('Unsupported action')
    if data['fps'] not in (24,30,60): raise ValueError('Unsupported fps')
    if (data['width'],data['height']) not in ((640,360),(1280,720),(1920,1080)):
        raise ValueError('Unsupported resolution')
    if type(data['duration']) not in (float,int) or not 1 <= data['duration'] <= 15:
        raise ValueError('Duration must be 1–15 sec')
    if int(round(data['fps']*data['duration'])) > MAX_FRAMES:
        raise ValueError('Too many frames')
    if not isinstance(data['character'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',data['character']):
        raise ValueError('Invalid character label')
    return data


def create_project(blob):
    qa = validate_glb(blob)
    pid=uuid.uuid4().hex
    target = ROOT / pid
    target.mkdir(parents=True)
    (target/'actor.glb').write_bytes(blob)
    with connection() as db:
        db.execute('INSERT INTO projects(id,state,qa,created,updated) VALUES(?,?,?,?,?)',
                   (pid,'asset_pending',json.dumps(qa),time.time(),time.time()))
    return pid,qa
