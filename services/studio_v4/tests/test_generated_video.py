"""Generated single-PNG 3D draft: regression tests for geometry and approval-gated workflow."""
import io
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient
from studio.api import app
from studio import store, pipeline
from studio.gltf_qa import inspect


def png_bytes():
    image=Image.new('RGBA',(64,96),(0,0,0,0))
    draw=ImageDraw.Draw(image)
    draw.ellipse((18,7,47,36),fill=(246,137,40,255))
    draw.rectangle((19,36,46,69),fill=(246,137,40,255))
    draw.rectangle((10,39,19,56),fill=(246,137,40,255))
    draw.rectangle((46,39,55,56),fill=(246,137,40,255))
    draw.rectangle((22,69,29,90),fill=(246,137,40,255))
    draw.rectangle((37,69,44,90),fill=(246,137,40,255))
    output=io.BytesIO()
    image.save(output,format='PNG')
    return output.getvalue()


def project(client):
    response=client.post('/api/projects',files={'asset':('KIO.png',png_bytes(),'image/png')})
    assert response.status_code==200,response.text
    return response.json()['id']


def test_generated_volumetric_png_through_mesh_approval_and_auto_rig():
    client=TestClient(app)
    pid=project(client)
    invalid=client.post('/api/projects/'+pid+'/generate',
        json={'prompt':'KIO duduk selama 5 detik','mesh_mode':'volumetric_draft_3d'})
    assert invalid.status_code==422
    assert store.get_project(pid)['state']=='uploaded'
    response=client.post('/api/projects/'+pid+'/generate',
        json={'prompt':'KIO berjalan selama 5 detik','mesh_mode':'volumetric_draft_3d',
              'width':640,'height':360,'fps':24})
    assert response.status_code==200,response.text
    assert response.json()['full_3d_reconstruction_verified'] is False
    duplicate=client.post('/api/projects/'+pid+'/generate',
        json={'prompt':'KIO berjalan selama 5 detik','mesh_mode':'volumetric_draft_3d'})
    assert duplicate.status_code==409
    job=store.jobs(pid)[0]
    assert job['kind']=='mesh' and job['state']=='queued'
    assert store.read_metadata(pid)['generation']['mesh_mode']=='volumetric_draft_3d'
    pipeline.run_job(job)
    state=client.get('/api/projects/'+pid).json()
    assert state['state']=='mesh_review',state['metadata'].get('last_error')
    qa=state['metadata']['mesh_qa']
    assert qa['volumetric_mesh'] and not qa['full_3d_reconstruction']
    assert qa['volume']>0 and qa['gltf']['valid_structure']
    assert qa['dimensions'][2]>.1
    assert inspect(store.DATA_ROOT/pid/'mesh.glb')['meshes']==1
    reviewed=client.post('/api/projects/'+pid+'/approve',
        json={'stage':'mesh','confirm':True})
    assert reviewed.status_code==200,reviewed.text
    assert reviewed.json()['next']['state']=='rig_building'
    assert store.jobs(pid)[0]['kind']=='rig'


def test_generate_rejects_wrong_dimensions_without_queuing():
    client=TestClient(app)
    pid=project(client)
    rejected=client.post('/api/projects/'+pid+'/generate',
        json={'prompt':'KIO berjalan selama 5 detik','width':1920,'height':720})
    assert rejected.status_code==422
    assert store.jobs(pid)==[]
    assert store.get_project(pid)['state']=='uploaded'
