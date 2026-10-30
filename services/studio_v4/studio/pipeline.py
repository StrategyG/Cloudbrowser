"""Pipeline stage execution. No shell invocation and no user-controlled filesystem paths."""
import hashlib
import json
import os
import subprocess
from pathlib import Path
from . import store
from .settings import DATA_ROOT, BLENDER, FFMPEG
from .mesh import generate_mesh
from .godot_render import render as godot_render
from .render_gate import verify_render_inputs
from .gltf_qa import inspect

ROOT=Path(__file__).resolve().parent.parent

def run(cmd,timeout):
 # Prevent UI/web thread from running arbitrary commands. Arguments originate from trusted code.
 result=subprocess.run(cmd,timeout=timeout,capture_output=True,text=True,check=False,
                       env={**os.environ,'PYTHONUNBUFFERED':'1'})
 output=(result.stdout or '')+'\n'+(result.stderr or '')
 # Godot editor import can return zero even when a scene script did not compile.
 if result.returncode or any(marker in output for marker in ('SCRIPT ERROR:', 'Parse Error:', 'STUDIO_GODOT_ERROR:')):
  raise RuntimeError(f'Process exit {result.returncode}: {output[-3500:]}')

def run_job(job):
 pid=job['project_id']; kind=job['kind'];folder=DATA_ROOT/pid
 try:
  if kind=='mesh':
   qa=generate_mesh(folder/'source.png',folder/'mesh.glb')
   qa['gltf']=inspect(folder/'mesh.glb')
   (folder/'mesh_qa.json').write_text(json.dumps(qa,indent=2))
   store.update_metadata(pid,mesh_qa=qa)
   store.change_state(pid,'mesh_building','mesh_review')
  elif kind=='rig':
   info=store.read_metadata(pid).get('mesh_qa',{})
   existing_skin=info.get('source_type')=='external_glb' and info.get('preexisting_skin',False)
   (folder/'rigged.glb').unlink(missing_ok=True)
   if existing_skin:
    # Review existing weights/bone names; do not silently destroy an authored rig.
    run([BLENDER,'-b','--python-exit-code','1','--python',str(ROOT/'workers'/'review_existing_rig.py'),'--',
         str(folder/'mesh.glb'),str(folder/'rig_qa.json')],900)
    import shutil
    shutil.copyfile(folder/'mesh.glb',folder/'rigged.glb')
   else:
    run([BLENDER,'-b','--python-exit-code','1','--python',str(ROOT/'workers'/'rig_asset.py'),'--',
         str(folder/'mesh.glb'),str(folder/'rigged.glb'),str(folder/'rig_qa.json')],900)
   qa=json.loads((folder/'rig_qa.json').read_text())
   qa['gltf']=inspect(folder/'rigged.glb',require_skin=True)
   with (folder/'rigged.glb').open('rb') as source:
    qa['sha256']=hashlib.file_digest(source,'sha256').hexdigest()
   store.update_metadata(pid,rig_qa=qa)
   store.change_state(pid,'rig_building','rig_review')
  elif kind=='render':
   expected=verify_render_inputs(pid)
   render_qa=godot_render(folder,run)
   # The model/manifest could have changed during a long render. Never publish
   # an artifact with uncertain provenance after a time-of-check/use race.
   if verify_render_inputs(pid)!=expected:
    raise RuntimeError('Render inputs changed during execution')
   with (folder/'output.mp4').open('rb') as output:
    render_qa['mp4_sha256']=hashlib.file_digest(output,'sha256').hexdigest()
   render_qa['input_sha256']=expected
   store.update_metadata(pid,render_qa=render_qa)
   store.change_state(pid,'rendering','completed')
  else: raise ValueError(f'Unknown job kind {kind}')
  store.finish_job(job['id'],True)
 except Exception as exc:
  project=store.get_project(pid)
  if project and project['state'] in ('mesh_building','rig_building','rendering'):
   store.change_state(pid,project['state'],'failed')
  store.update_metadata(pid,last_error=str(exc)[:2500])
  store.finish_job(job['id'],False,str(exc))
