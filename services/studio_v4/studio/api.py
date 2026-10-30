"""Local-first API: explicit approval gates and durable worker queue."""
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from . import store
from .settings import API_TOKEN, DATA_ROOT, MAX_UPLOAD_BYTES
from .mesh import validate_png
from .import_glb import MAX_GLB_UPLOAD_BYTES, validate_imported_glb
from .manifest import Manifest, plan
from .scene_intelligence import inspect_project, motion_preflight

ROOT=Path(__file__).resolve().parent.parent
app=FastAPI(title='Full Pipeline Studio Godot V4.1',version='4.1.0')
store.init()

@app.middleware('http')
async def security(request:Request,call_next):
 if request.url.path not in ('/api/health', '/'):
  if API_TOKEN:
   import secrets
   given=request.headers.get('x-studio-token','')
   if not secrets.compare_digest(API_TOKEN,given):
    from fastapi.responses import JSONResponse
    return JSONResponse({'detail':'Invalid studio access token'},status_code=401)
  else:
   host=request.client.host if request.client else ''
   if host not in ('127.0.0.1','::1','testclient'):
    from fastapi.responses import JSONResponse
    return JSONResponse({'detail':'Configure STUDIO_API_TOKEN before remote access'},status_code=403)
 return await call_next(request)

@app.get('/',response_class=HTMLResponse)
def home():return (ROOT/'web'/'index.html').read_text()

@app.get('/api/health')
def health():return {'ok':True,'version':'4.1.0','worker':'separate process','render_engine':'godot_4',
                      'security':'token' if API_TOKEN else 'loopback_only'}

def project_or_404(pid):
 if not re.fullmatch(r'[a-f0-9]{32}',pid):raise HTTPException(404,'Project not found')
 p=store.get_project(pid)
 if not p:raise HTTPException(404,'Project not found')
 return p

def bad_transition(e):raise HTTPException(409,str(e))

def check_source_integrity(pid, project):
 metadata = json.loads(project['metadata'])
 ext = 'glb' if metadata.get('source', {}).get('type') == 'glb' else 'png'
 source = DATA_ROOT / pid / ('mesh.glb' if ext == 'glb' else 'source.png')
 if not source.is_file():
  raise HTTPException(409, 'Source file is missing')
 with source.open('rb') as handle:
  digest = hashlib.file_digest(handle, 'sha256').hexdigest()
 if digest != project['sha256']:
  raise HTTPException(409, 'Source changed since validation; create a new project')


def check_rig_integrity(pid, metadata):
 expected = metadata.get('rig_qa', {}).get('sha256')
 if not expected:
  return
 path = DATA_ROOT / pid / 'rigged.glb'
 if not path.is_file():
  raise HTTPException(409, 'Approved rig is missing')
 with path.open('rb') as handle:
  current = hashlib.file_digest(handle, 'sha256').hexdigest()
 if current != expected:
  raise HTTPException(409, 'Rig changed after QA; reimport and review')



@app.post('/api/projects')
async def upload_asset(asset: UploadFile = File(...)):
 name = asset.filename or 'asset.png'
 suffix = Path(name).suffix.casefold()
 if suffix not in ('.png', '.glb'):
  raise HTTPException(415, 'PNG or GLB required')
 limit = MAX_GLB_UPLOAD_BYTES if suffix == '.glb' else MAX_UPLOAD_BYTES
 payload = await asset.read(limit + 1)
 if not payload or len(payload) > limit:
  raise HTTPException(413, 'File exceeds format size limit')
 if suffix == '.png' and payload[:8] != b'\x89PNG\r\n\x1a\n':
  raise HTTPException(415, 'Invalid PNG signature')
 if suffix == '.glb' and payload[:4] != b'glTF':
  raise HTTPException(415, 'Invalid GLB signature')
 # Validate untrusted GLB before registering a project; no stale project on rejection.
 if suffix == '.glb':
  try:
   with tempfile.TemporaryDirectory(dir=DATA_ROOT, prefix='glb-check-') as temp:
    candidate = Path(temp) / 'candidate.glb'
    candidate.write_bytes(payload)
    mesh_qa = validate_imported_glb(candidate)
  except Exception as exc:
   raise HTTPException(422, 'GLB QA rejected: ' + str(exc)[:300]) from exc
 pid = store.create_project(Path(name).stem[:70], hashlib.sha256(payload).hexdigest())
 folder = DATA_ROOT / pid
 try:
  if suffix == '.png':
   src = folder / 'source.png'
   src.write_bytes(payload)
   rgba = validate_png(src)
   store.update_metadata(pid, source={'type': 'png', 'width': rgba.width,
                                      'height': rgba.height, 'sha256': hashlib.sha256(payload).hexdigest()})
  else:
   (folder / 'mesh.glb').write_bytes(payload)
   (folder / 'mesh_qa.json').write_text(json.dumps(mesh_qa, indent=2))
   store.update_metadata(pid, source={'type': 'glb', 'sha256': hashlib.sha256(payload).hexdigest()},
                         mesh_qa=mesh_qa)
   # Imported mesh is READY FOR HUMAN REVIEW, not auto-approved or auto-rigged.
   store.change_state(pid, 'uploaded', 'mesh_review')
 except Exception as exc:
  with store.conn() as db:
   db.execute('DELETE FROM projects WHERE id=?', (pid,))
  shutil.rmtree(folder, ignore_errors=True)
  raise HTTPException(422, str(exc)) from exc
 return {'id': pid, 'state': 'mesh_review' if suffix == '.glb' else 'uploaded',
         'source_type': suffix[1:] }

class GeneratedVideoRequest(BaseModel):
 """Opt-in generated workflow with mandatory approval at each asset gate."""
 prompt: str=Field(min_length=1,max_length=1200)
 mesh_mode: Literal['volumetric_draft_3d','silhouette_2_5d']='volumetric_draft_3d'
 fps: Literal[24,30,60]=24
 character: str=Field(default='KIO',pattern=r'^[A-Za-z0-9_-]{1,70}$')
 width: Literal[640,1280,1920]=1280
 height: Literal[360,720,1080]=720


@app.post('/api/projects/{pid}/generate')
def generate_video_draft(pid:str,request:GeneratedVideoRequest):
 """Start generated PNG→mesh→rig→manifest→MP4 with owner approvals."""
 p=project_or_404(pid)
 if p['state']!='uploaded':
  raise HTTPException(409,'Generated workflow can only start from an unprocessed PNG')
 if json.loads(p['metadata']).get('source',{}).get('type')!='png':
  raise HTTPException(409,'Generated workflow requires a PNG source')
 check_source_integrity(pid,p)
 try:
  plan(request.prompt,request.fps,request.character,request.width,request.height)
 except (ValueError,TypeError) as exc:
  raise HTTPException(422,str(exc)) from exc
 config=request.model_dump()
 config['auto_advance']=True
 try:
  jid=store.enqueue(pid,'mesh','uploaded','mesh_building',
                    metadata_updates={'generation':config})
 except ValueError as exc:
  bad_transition(exc)
 return {'id':pid,'state':'mesh_building','job_id':jid,
         'mesh_mode':request.mesh_mode,'requires_owner_approval':True,
         'next_gate':'mesh_review','automatic_after_approval':True,
         'full_3d_reconstruction_verified':False}


@app.get('/api/projects/{pid}')
def get_project(pid:str):
 p=project_or_404(pid)
 return {'id':pid,'name':p['name'],'state':p['state'],'sha256':p['sha256'],
         'metadata':json.loads(p['metadata']),'jobs':store.jobs(pid)}

@app.get('/api/projects/{pid}/scene')
def scene_info(pid:str):
 p=project_or_404(pid)
 try:
  return inspect_project(pid,p)
 except (ValueError, OSError) as exc:
  raise HTTPException(409,'Scene inspection failed: '+str(exc)[:180]) from exc


@app.get('/api/projects/{pid}/motion-qa')
def motion_qa(pid:str):
 scene=scene_info(pid)
 return motion_preflight(scene)


@app.get('/api/projects/{pid}/assets/{asset_type}')
def fetch_asset(pid:str,asset_type:str):
 project=project_or_404(pid)
 # A failed/interrupted render may leave a plausible stale output.mp4 on disk.
 # Do not disclose a video that has not passed this project's final QA.
 if asset_type=='mp4':
  if project['state']!='completed':
   raise HTTPException(409,'Video has not passed final project verification')
  expected=json.loads(project['metadata']).get('render_qa',{}).get('mp4_sha256')
  path=DATA_ROOT/pid/'output.mp4'
  if not expected or not path.is_file():
   raise HTTPException(409,'Missing verified MP4 checksum')
  with path.open('rb') as handle:
   actual=hashlib.file_digest(handle,'sha256').hexdigest()
  if actual!=expected:
   raise HTTPException(409,'Verified MP4 changed since QA')
 items={'png':('source.png','image/png'), 'mesh':('mesh.glb','model/gltf-binary'),
        'rig_rest':('rig_pose_rest.png','image/png'), 'rig_arms':('rig_pose_arms.png','image/png'),
        'rig_legs':('rig_pose_legs.png','image/png'), 'rig_combo':('rig_pose_combo.png','image/png'),
        'rig':('rigged.glb','model/gltf-binary'),
        'manifest':('manifest.json','application/json'),
        'mp4':('output.mp4','video/mp4')}
 if asset_type not in items:raise HTTPException(404,'Unknown asset')
 filename,mime=items[asset_type];path=DATA_ROOT/pid/filename
 if not path.is_file():raise HTTPException(404,'Asset is not available')
 return FileResponse(path,media_type=mime,filename=filename,
                     content_disposition_type='inline' if asset_type in ('png','mp4') else 'attachment',
                     headers={'X-Content-Type-Options':'nosniff'})

@app.post('/api/projects/{pid}/mesh')
def build_mesh(pid:str):
 p=project_or_404(pid)
 if json.loads(p['metadata']).get('source', {}).get('type') == 'glb':
  raise HTTPException(409, 'Imported GLB mesh already awaits review; rebuild is not available')
 if p['state'] not in ('uploaded','mesh_review'):raise HTTPException(409,'Mesh stage unavailable')
 try:jid=store.enqueue(pid,'mesh',p['state'],'mesh_building')
 except ValueError as exc:bad_transition(exc)
 return {'job_id':jid,'state':'mesh_building'}

class Approval(BaseModel):
 stage: str
 confirm: bool

@app.post('/api/projects/{pid}/approve')
def approve(pid:str,item:Approval):
 p=project_or_404(pid)
 if item.confirm is not True:raise HTTPException(422,'Explicit approval required')
 expected={'mesh':('mesh_review','mesh_approved'),
           'rig':('rig_review','rig_approved'),
           'manifest':('manifest_review','manifest_approved')}.get(item.stage)
 if not expected:raise HTTPException(422,'Unknown stage')
 metadata=json.loads(p['metadata'])
 if item.stage=='mesh':
  check_source_integrity(pid, p)
  qa=metadata.get('mesh_qa',{})
  if not (qa.get('watertight') and qa.get('winding_consistent') and qa.get('connected_components')==1
          and qa.get('gltf',{}).get('valid_structure')):
   raise HTTPException(409,'Mesh QA gate failed')
 if item.stage=='rig':
  check_rig_integrity(pid, metadata)
  qa=metadata.get('rig_qa',{})
  if not (qa.get('unweighted_vertices')==0 and qa.get('gltf',{}).get('skins',0)>0 and qa.get('gltf',{}).get('skinned_primitives',0)>0
          and len(qa.get('pose_previews',[]))==4):
   raise HTTPException(409,'Rig QA gate failed')
 if item.stage=='manifest':
  path=DATA_ROOT/pid/'manifest.json'
  if not path.exists():raise HTTPException(409,'Missing manifest')
  manifest=Manifest.model_validate_json(path.read_text())
  if manifest.approval!='pending':raise HTTPException(409,'Manifest needs pending approval')
  path.write_text(manifest.model_copy(update={'approval':'approved'}).model_dump_json(indent=2))
  with path.open('rb') as approved_manifest:
   approved_digest=hashlib.file_digest(approved_manifest,'sha256').hexdigest()
  store.update_metadata(pid,manifest_approved_sha256=approved_digest)
 try:store.change_state(pid,*expected)
 except ValueError as exc:bad_transition(exc)
 result={'state':expected[1],'approval_recorded':True}
 generation=metadata.get('generation',{})
 if generation.get('auto_advance'):
  # Each progression is allowed only after exact owner approval.
  try:
   if item.stage=='mesh':
    result['next']=build_rig(pid)
   elif item.stage=='rig':
    settings={k:generation[k] for k in ('prompt','fps','character','width','height')}
    submit_prompt(pid,PromptRequest(**settings))
    result['next']={'state':'manifest_review','requires_owner_approval':True}
   elif item.stage=='manifest':
    result['next']=render_video(pid)
  except (HTTPException,ValueError,TypeError) as exc:
   result['auto_advance_error']=str(getattr(exc,'detail',exc))[:300]
 return result

@app.post('/api/projects/{pid}/retry')
def retry_project(pid:str):
 p=project_or_404(pid)
 if p['state']!='failed':raise HTTPException(409,'Only failed projects may retry')
 prior=store.jobs(pid)
 if not prior:raise HTTPException(409,'No failure to retry')
 kind=prior[0]['kind']
 if kind not in ('mesh','rig','render'):raise HTTPException(409,'Unknown retry target')
 if sum(1 for j in prior if j['kind']==kind and j['state']=='failed')>=3:
  raise HTTPException(409,'Retry budget exhausted; manual intervention required')
 return {'job_id':store.enqueue(pid,kind,'failed',{'mesh':'mesh_building','rig':'rig_building','render':'rendering'}[kind]),'kind':kind}

@app.post('/api/projects/{pid}/rig')
def build_rig(pid:str):
 p=project_or_404(pid)
 check_source_integrity(pid, p)
 if p['state'] not in ('mesh_approved','rig_review'):raise HTTPException(409,'Rig stage unavailable')
 try:jid=store.enqueue(pid,'rig',p['state'],'rig_building')
 except ValueError as exc:bad_transition(exc)
 return {'job_id':jid,'state':'rig_building'}

class PromptRequest(BaseModel):
 prompt: str=Field(min_length=1,max_length=1200)
 fps: int=24
 character: str='KIO'
 width: int=1280
 height: int=720

@app.post('/api/projects/{pid}/plan-preview')
def preview_scene(pid:str,request:PromptRequest):
 # Does not write a manifest, create jobs, or alter existing approvals.
 p=project_or_404(pid)
 if p['state'] not in ('rig_approved','manifest_review','manifest_approved','completed'):
  raise HTTPException(409,'Approve rig before previewing a production scene')
 try:
  candidate=plan(request.prompt,request.fps,request.character,request.width,request.height)
 except (ValueError,TypeError) as exc:
  raise HTTPException(422,str(exc)) from exc
 current=DATA_ROOT/pid/'manifest.json'
 before=None
 if current.is_file():
  before=hashlib.sha256(current.read_bytes()).hexdigest()
 return {'project_id':pid,'preview':candidate.model_dump(),
         'current_manifest_sha256':before,'writes_performed':False,
         'quality_certified':False,'requires_owner_approval':True}


@app.post('/api/projects/{pid}/prompt')
def submit_prompt(pid:str,request:PromptRequest):
 p=project_or_404(pid)
 if p['state'] not in ('rig_approved','manifest_review','completed','manifest_approved'):
  raise HTTPException(409,'Approve rig before writing scene')
 try:manifest=plan(request.prompt,request.fps,request.character,request.width,request.height)
 except Exception as exc:raise HTTPException(422,str(exc))
 path=DATA_ROOT/pid/'manifest.json'
 path.write_text(manifest.model_dump_json(indent=2))
 store.update_metadata(pid,prompt=request.prompt)
 if p['state']!='manifest_review':
  try:store.change_state(pid,p['state'],'manifest_review')
  except ValueError as exc:bad_transition(exc)
 return manifest.model_dump()

@app.post('/api/projects/{pid}/ai-plan')
def submit_ai_prompt(pid:str,request:PromptRequest):
 p=project_or_404(pid)
 if p['state'] not in ('rig_approved','manifest_review','completed','manifest_approved'):
  raise HTTPException(409,'Approve rig before writing scene')
 from .local_ai import generate
 try:manifest=generate(request.prompt,request.fps,request.character,request.width,request.height)
 except Exception as exc:raise HTTPException(422,str(exc))
 (DATA_ROOT/pid/'manifest.json').write_text(manifest.model_dump_json(indent=2))
 store.update_metadata(pid,prompt=request.prompt)
 if p['state']!='manifest_review':
  try:store.change_state(pid,p['state'],'manifest_review')
  except ValueError as exc:bad_transition(exc)
 return manifest.model_dump()

@app.post('/api/projects/{pid}/manifest')
def structured_manifest(pid:str,manifest:Manifest):
 p=project_or_404(pid)
 if p['state'] not in ('rig_approved','manifest_review','completed','manifest_approved'):
  raise HTTPException(409,'Approve rig first')
 clean=manifest.model_copy(update={'approval':'pending','planner':'structured_user'})
 (DATA_ROOT/pid/'manifest.json').write_text(clean.model_dump_json(indent=2))
 if p['state']!='manifest_review':
  try:store.change_state(pid,p['state'],'manifest_review')
  except ValueError as exc:bad_transition(exc)
 return clean.model_dump()

@app.post('/api/projects/{pid}/render')
def render_video(pid:str):
 p=project_or_404(pid)
 check_rig_integrity(pid, json.loads(p['metadata']))
 if p['state']!='manifest_approved':raise HTTPException(409,'Approve manifest before rendering')
 path=DATA_ROOT/pid/'manifest.json'
 expected=json.loads(p['metadata']).get('manifest_approved_sha256')
 if not expected or not path.is_file():
  raise HTTPException(409,'Missing approved manifest checksum')
 with path.open('rb') as current_manifest:
  actual=hashlib.file_digest(current_manifest,'sha256').hexdigest()
 if actual!=expected:
  raise HTTPException(409,'Manifest modified since approval; review and approve again')
 report=motion_preflight(scene_info(pid))
 if report['blocked']:
  raise HTTPException(409,'Motion preflight failed: '+json.dumps(report['findings'])[:400])
 try:jid=store.enqueue(pid,'render','manifest_approved','rendering')
 except ValueError as exc:bad_transition(exc)
 return {'job_id':jid,'state':'rendering'}
