"""Pipeline stage execution. No shell invocation and no user-controlled filesystem paths."""
import json
import os
import subprocess
from pathlib import Path
from . import store
from .settings import DATA_ROOT, BLENDER, FFMPEG
from .mesh import generate_mesh
from .godot_render import render as godot_render
from .gltf_qa import inspect

ROOT=Path(__file__).resolve().parent.parent

def run(cmd,timeout):
 # Prevent UI/web thread from running arbitrary commands. Arguments originate from trusted code.
 result=subprocess.run(cmd,timeout=timeout,capture_output=True,text=True,check=False,
                       env={**os.environ,'PYTHONUNBUFFERED':'1'})
 if result.returncode: raise RuntimeError(f'Process exit {result.returncode}: {(result.stderr or result.stdout)[-3500:]}')

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
   run([BLENDER,'-b','--python',str(ROOT/'workers'/'rig_asset.py'),'--',
       str(folder/'mesh.glb'),str(folder/'rigged.glb'),str(folder/'rig_qa.json')],900)
   qa=json.loads((folder/'rig_qa.json').read_text())
   qa['gltf']=inspect(folder/'rigged.glb',require_skin=True)
   store.update_metadata(pid,rig_qa=qa)
   store.change_state(pid,'rig_building','rig_review')
  elif kind=='render':
   render_qa=godot_render(folder,run)
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
