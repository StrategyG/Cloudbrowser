import io
import json
from PIL import Image
from fastapi.testclient import TestClient
from studio.api import app
from studio import store

client=TestClient(app)

def test_health():
 assert client.get('/api/health').status_code==200

def test_upload_and_review_gates(tmp_path):
 image=Image.new('RGBA',(28,28),(0,0,0,0))
 for x in range(7,21):
  for y in range(3,26):image.putpixel((x,y),(160,170,255,255))
 b=io.BytesIO();image.save(b,format='PNG')
 result=client.post('/api/projects',files={'asset':('person.png',b.getvalue(),'image/png')})
 assert result.status_code==200,result.text
 pid=result.json()['id']
 assert client.post(f'/api/projects/{pid}/rig').status_code==409
 assert client.post(f'/api/projects/{pid}/approve',json={'stage':'mesh','confirm':True}).status_code==409
 assert client.post(f'/api/projects/{pid}/mesh').status_code==200
 assert client.post(f'/api/projects/{pid}/mesh').status_code==409
 job=store.claim_job()
 assert job and job['project_id']==pid
 from studio.pipeline import run_job
 run_job(job)
 project=client.get(f'/api/projects/{pid}').json()
 assert project['state']=='mesh_review',project
 assert project['metadata']['mesh_qa']['watertight']
 assert client.post(f'/api/projects/{pid}/approve',json={'stage':'mesh','confirm':False}).status_code==422
 assert client.post(f'/api/projects/{pid}/approve',json={'stage':'mesh','confirm':True}).status_code==200
 assert client.post(f'/api/projects/{pid}/prompt',json={'prompt':'Kio berjalan'}).status_code==409
