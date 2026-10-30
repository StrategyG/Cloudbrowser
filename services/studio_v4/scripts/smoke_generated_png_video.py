"""CI evidence: owner-reviewed generated PNG -> volumetric GLB -> Blender rig -> Godot MP4.

A synthetic CPU-only render smoke, NOT proof of accurate reconstruction or natural motion.
"""
#"hx
import io
import json
import shutil
import sys
from pathlib import Path

STUDIO_V4_ROOT = Path(__file__).resolve().parent.parent
if str(STUDIO_V4_ROOT) not in sys.path:
    sys.path.insert(0, str(STUDIO_V4_ROOT))

from PIL import Image, ImageDraw
from fastapi.testclient import TestClient
from studio import store, pipeline
from studio.api import app
from studio.settings import DATA_ROOT


def put_png():
    picture = Image.new('RGBA', (64, 96), (0, 0, 0, 0))
    drawing = ImageDraw.Draw(picture)
    drawing.ellipse((17, 7, 47, 35), fill=(240, 128, 55, 255))
    drawing.rectangle((20, 34, 45, 68), fill=(238, 100, 32, 255))
    drawing.rectangle((11, 40, 20, 57), fill=(245, 128, 55, 255))
    drawing.rectangle((45, 40, 54, 57), fill=(245, 128, 55, 255))
    drawing.rectangle((22, 68, 30, 90), fill=(46, 80, 178, 255))
    drawing.rectangle((36, 68, 44, 90), fill=(46, 80, 178, 255))
    output = io.BytesIO()
    picture.save(output, format='PNG')
    return output.getvalue()


def advance(client, pid, stage):
    previous = client.get('/api/projects/' + pid).json()
    needed = {'mesh': 'mesh_review', 'rig': 'rig_review', 'manifest': 'manifest_review'}[stage]
    if previous['state'] != needed:
        raise RuntimeError('Unexpected review state: ' + json.dumps(previous)[-1600:])
    action = client.post('/api/projects/' + pid + '/approve', json={'stage': stage, 'confirm': True})
    if action.status_code != 200 or action.json().get('auto_advance_error'):
        raise RuntimeError('Owner approval/advance failed: ' + action.text)
    return action.json()


def main():
    client = TestClient(app)
    png_bytes = put_png()
    draft = client.post('/api/projects/from_image', files={'file': ('synthetic.png', png_bytes, 'image/png')})
    if draft.status_code != 200:
        raise RuntimeError('Failed to create project from PNG: ' + draft.text)
    pid = draft.json()['project_id']
    advance(client, pid, 'mesh')
    advance(client, pid, 'rig')
    advanced = advance(client, pid, 'manifest')
    output_video = DATA_ROOT / pid / 'generated_3d_draft_video.mp4'
    if not output_video.exists() or output_video.stat().st_size == 0:
        raise RuntimeError('Smoke test failed: generated MP4 missing or empty')
    video_summary = advanced['project']['artifacts'].get('generated_3d_draft_video', {})
    if not video_summary or video_summary.get('status') != 'completed':
        raise RuntimeError('Smoke test failed: artifact metadata not completed')
    print('Generated 3D draft video smoke test passed: ' + str(output_video) + ' (' + str(output_video.stat().st_size) + ' bytes)')


if __name__ == '__main__':
    main()
from studio import store, pipeline
from studio.api import app
from studio.settings import DATA_ROOT


def put_png():
    picture=Image.new('RGBA',(64,96),(0,0,0,0))
    drawing=ImageDraw.Draw(picture)
    drawing.ellipse((17,7,47,35),fill=(240,128,55,255))
    drawing.rectangle((20,34,45,68),fill=(238,100,32,255))
    drawing.rectangle((11,40,20,57),fill=(245,128,55,255))
    drawing.rectangle((45,40,54,57),fill=(245,128,55,255))
    drawing.rectangle((22,68,30,90),fill=(46,80,178,255))
    drawing.rectangle((36,68,44,90),fill=(46,80,178,255))
    output=io.BytesIO()
    picture.save(output,format='PNG')
    return output.getvalue()


def advance(client,pid,stage):
    previous=client.get('/api/projects/'+pid).json()
    needed={'mesh':'mesh_review','rig':'rig_review','manifest':'manifest_review'}[stage]
    if previous['state']!=needed:
        raise RuntimeError('Unexpected review state: '+json.dumps(previous)[-1600:])
    action=client.post('/api/projects/'+pid+'/approve',json={'stage':stage,'confirm':True})
    if action.status_code!=200 or action.json().get('auto_advance_error'):
        raise RuntimeError('Owner approval/advance failed: '+action.text)
    return action.json()


def process(pid,expected):
    job=store.jobs(pid)[0]
    if job['kind']!=expected or job['state']!='queued':
        raise RuntimeError('Wrong queued stage: '+repr(job))
    pipeline.run_job(job)
    project=store.get_project(pid)
    if project['state']=='failed':
        raise RuntimeError('Studio stage failed: '+repr(store.read_metadata(pid).get('last_error')))
    return project['state']


def main():
    client=TestClient(app)
    uploaded=client.post('/api/projects',
        files={'asset':('ARUSIA_test.png',put_png(),'image/png')})
    uploaded.raise_for_status()
    pid=uploaded.json()['id']
    result=client.post('/api/projects/'+pid+'/generate',
        json={'prompt':'KIO berjalan selama 3 detik','mesh_mode':'volumetric_draft_3d',
              'fps':24,'width':640,'height':360,'character':'KIO'})
    result.raise_for_status()
    assert process(pid,'mesh')=='mesh_review'
    advance(client,pid,'mesh')
    assert process(pid,'rig')=='rig_review'
    advance(client,pid,'rig')
    advance(client,pid,'manifest')
    assert process(pid,'render')=='completed'
    final=client.get('/api/projects/'+pid).json()
    assert final['metadata']['mesh_qa']['volumetric_mesh']
    assert final['metadata']['mesh_qa']['full_3d_reconstruction'] is False
    assert final['metadata']['rig_qa']['gltf']['skins']>=1
    assert final['metadata']['render_qa']['mp4_sha256']
    assert final['metadata']['render_qa']['frame_content_qa']['motion_quality_certified'] is False
    media=client.get('/api/projects/'+pid+'/assets/mp4')
    media.raise_for_status()
    assert media.content[:4] != b''
    report={
        'passed':True,'project_id':pid,
        'generator':'single_view_volumetric_loft_draft',
        'full_3d_reconstruction_verified':False,
        'rig':'Blender template','render':'Godot offline',
        'output_mp4_sha256':final['metadata']['render_qa']['mp4_sha256'],
        'motion_quality_certified':False,
        'steps':'PNG→generated volumetric GLB→owner mesh approval→Blender rig→owner rig approval→generated manifest→owner manifest approval→Godot MP4',
    }
    print('PASS GENERATED 3D DRAFT→VIDEO',json.dumps(report))
    destination=Path('/ci-output')
    if destination.is_dir():
        shutil.copyfile(DATA_ROOT/pid/'output.mp4',destination/'generated_png_output.mp4')
        (destination/'generated_png_report.json').write_text(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
