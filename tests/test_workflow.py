import json, struct
import pytest
from fastapi.testclient import TestClient


def glb(skin=True):
    data={'asset':{'version':'2.0'},'meshes':[{}], 'scenes':[{'nodes':[0]}], 'nodes':[{'mesh':0},{'name':'RootBone'}]}
    if skin: data['skins']=[{'joints':[1]}]
    raw=json.dumps(data).encode();raw+=b' '*((-len(raw))%4)
    return b'glTF'+struct.pack('<II',2,20+len(raw))+struct.pack('<I4s',len(raw),b'JSON')+raw

@pytest.fixture
def client(monkeypatch,tmp_path):
    import cloudbrowser.core as core, cloudbrowser.api as api
    monkeypatch.setattr(core,'ROOT',tmp_path)
    monkeypatch.setattr(api,'ROOT',tmp_path)
    monkeypatch.setattr(api,'TOKEN','test-secret-01234567890123456789012')
    return TestClient(api.app),{'Authorization':'Bearer '+api.TOKEN}

def test_glb_rejection():
    from cloudbrowser.core import validate_glb
    with pytest.raises(ValueError):validate_glb(b'bad')
    with pytest.raises(ValueError):validate_glb(glb(False))
    assert validate_glb(glb(True))['skins']==1

def test_auth_and_gate(client):
    c,h=client
    assert c.get('/api/projects').status_code==401
    assert c.post('/api/projects',headers=h,files={'asset':('x.png',glb(),'image/png')}).status_code==415
    resp=c.post('/api/projects',headers=h,files={'asset':('x.glb',glb(),'model/gltf-binary')})
    assert resp.status_code==200,resp.text
    q='/api/projects/'+resp.json()['id']
    assert c.post(q+'/render',headers=h).status_code==409
    assert c.post(q+'/approve-asset',headers=h).status_code==200
    m={'character':'KIO','action':'walk','duration':2,'fps':24,'width':640,'height':360}
    assert c.put(q+'/manifest',json={**m,'command':'execute'},headers=h).status_code==422
    assert c.put(q+'/manifest',json=m,headers=h).status_code==200
    assert c.post(q+'/render',headers=h).status_code==409
    assert c.post(q+'/approve-manifest',headers=h).status_code==200
    assert c.post(q+'/render',headers=h).json()['state']=='queued'
    assert c.get(q+'/video',headers=h).status_code==409

def test_manifest_validation():
    from cloudbrowser.core import validate_manifest
    m={'character':'KIO','action':'idle','duration':15,'fps':60,'width':1920,'height':1080}
    assert validate_manifest(m)['duration']==15
    for bad in ({**m,'duration':16},{**m,'character':'../a'},{**m,'command':'ls'}):
        with pytest.raises(ValueError):validate_manifest(bad)

def test_worker_failure(client,monkeypatch):
    c,h=client
    pid=c.post('/api/projects',headers=h,files={'asset':('x.glb',glb(),'application/octet-stream')}).json()['id']
    q='/api/projects/'+pid
    c.post(q+'/approve-asset',headers=h)
    c.put(q+'/manifest',json={'character':'KIO','action':'idle','duration':1,'fps':24,'width':640,'height':360},headers=h)
    c.post(q+'/approve-manifest',headers=h)
    c.post(q+'/render',headers=h)
    from cloudbrowser import engine, api
    monkeypatch.setattr(engine,'ROOT',api.ROOT)
    monkeypatch.setattr(engine,'GODOT','/does-not-exist-godot')
    engine.run_worker(once=True)
    assert c.get(q,headers=h).json()['state']=='failed'
