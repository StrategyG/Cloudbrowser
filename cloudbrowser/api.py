"""Authenticated CloudBrowser/Godot gateway. No arbitrary website or shell operations."""
import hmac, os
from pathlib import Path
from fastapi import FastAPI, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from .core import (ROOT, MAX_GLB_BYTES, connection, create_project,
                   get_project, transition, validate_manifest)

app=FastAPI(title='CloudBrowser × Godot',version='0.2.0',docs_url=None,redoc_url=None)
TOKEN=os.getenv('CLOUDBROWSER_API_TOKEN','')


def auth(authorization: str | None=Header(default=None)):
    if not TOKEN or len(TOKEN) < 24: raise HTTPException(503,'Server API token not configured')
    supplied=(authorization or '').removeprefix('Bearer ').strip()
    if not hmac.compare_digest(supplied,TOKEN): raise HTTPException(401,'Invalid bearer token')


class Manifest(BaseModel):
    action:str='idle'
    fps:int=24
    duration:float=5
    width:int=1280
    height:int=720
    character:str='KIO'


def project_or_404(pid):
    try: return get_project(pid)
    except (ValueError,LookupError): raise HTTPException(404,'Project not found')


def set_state(pid,allowed,state,manifest=None):
    try: transition(pid,allowed,state,manifest=manifest)
    except ValueError as e: raise HTTPException(409,str(e))


@app.get('/healthz')
def healthz(): return {'ok':True}


@app.get('/')
def home():
    page=Path(__file__).resolve().parent.parent/'web/index.html'
    return HTMLResponse(page.read_text(encoding='utf-8'))


@app.post('/api/projects',dependencies=[Depends(auth)])
async def upload(asset:UploadFile=File(...)):
    if not asset.filename or not asset.filename.lower().endswith('.glb'):
        raise HTTPException(415,'Only rigged .glb files are accepted')
    chunks=[]; count=0
    while True:
        part=await asset.read(1024*1024)
        if not part: break
        count+=len(part)
        if count>MAX_GLB_BYTES: raise HTTPException(413,'GLB exceeds 32 MB')
        chunks.append(part)
    try: pid, qa=create_project(b''.join(chunks))
    except ValueError as e: raise HTTPException(422,str(e))
    return {'id':pid,'state':'asset_pending','qa':qa}


@app.get('/api/projects',dependencies=[Depends(auth)])
def projects():
    with connection() as db:
        rows=db.execute('SELECT id,state,updated FROM projects ORDER BY updated DESC LIMIT 50').fetchall()
    return {'projects':[dict(r) for r in rows]}


@app.get('/api/projects/{pid}',dependencies=[Depends(auth)])
def project(pid:str):return project_or_404(pid)


@app.post('/api/projects/{pid}/approve-asset',dependencies=[Depends(auth)])
def approve_asset(pid:str):
    project_or_404(pid)
    set_state(pid,{'asset_pending'},'asset_approved')
    return project_or_404(pid)


@app.put('/api/projects/{pid}/manifest',dependencies=[Depends(auth)])
def save_manifest(pid:str,manifest:Manifest):
    project_or_404(pid)
    try: data=validate_manifest(manifest.model_dump())
    except ValueError as e: raise HTTPException(422,str(e))
    set_state(pid,{'asset_approved','manifest_pending','manifest_approved','failed','completed'},
              'manifest_pending',manifest=data)
    return project_or_404(pid)


@app.post('/api/projects/{pid}/approve-manifest',dependencies=[Depends(auth)])
def approve_manifest(pid:str):
    project_or_404(pid)
    set_state(pid,{'manifest_pending'},'manifest_approved')
    return project_or_404(pid)


@app.post('/api/projects/{pid}/render',dependencies=[Depends(auth)])
def enqueue(pid:str):
    project_or_404(pid)
    set_state(pid,{'manifest_approved'},'queued')
    return project_or_404(pid)


@app.get('/api/projects/{pid}/video',dependencies=[Depends(auth)])
def video(pid:str):
    p=project_or_404(pid)
    if p['state']!='completed':raise HTTPException(409,'Rendering not completed')
    path=ROOT/pid/'output.mp4'
    if not path.is_file():raise HTTPException(404,'Video missing')
    return FileResponse(path,media_type='video/mp4',filename='cloudbrowser-godot.mp4')
