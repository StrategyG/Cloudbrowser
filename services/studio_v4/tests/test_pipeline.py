import json
import os
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
from studio.mesh import generate_mesh, validate_png
from studio.gltf_qa import inspect, read_glb
from studio.manifest import Manifest, Shot, plan

@pytest.fixture
def image(tmp_path):
 a=np.zeros((50,50,4),dtype=np.uint8)
 a[8:45,16:35,:3]=[244,120,60]
 a[8:45,16:35,3]=255
 a[9:19,6:16,:3]=[244,120,60]
 a[9:19,6:16,3]=255
 img=tmp_path/'asset.png';Image.fromarray(a,'RGBA').save(img)
 return img

def test_real_watertight_roundtrip(image,tmp_path):
 dest=tmp_path/'test.glb'
 qa=generate_mesh(image,dest,max_side=48)
 assert qa['watertight'] and qa['winding_consistent'] and qa['volume']>0
 assert qa['geometry_kind']=='silhouette_extrusion_2_5D'
 check=inspect(dest)
 assert check['meshes']>=1 and check['vertex_count']>0
 assert dest.read_bytes()[:4]==b'glTF'

def test_reject_opaque_image(tmp_path):
 im=tmp_path/'opaque.png';Image.new('RGB',(32,32),(255,0,0)).save(im)
 with pytest.raises(ValueError):validate_png(im)

def test_prompt_sequence_and_limits():
 p=plan('Kio berjalan di Kota Arusia sunset selama 6 detik lalu melambaikan tangan',fps=24)
 assert [s.action for s in p.shots]==['walk','wave']
 assert p.shots[0].duration==3
 assert p.shots[0].location=='arusia'
 with pytest.raises(ValueError):plan('Kio duduk di bangku')
 with pytest.raises(ValueError):plan('Kio berjalan selama 60 detik')
 with pytest.raises(ValueError):Manifest(shots=[Shot(character='Kio',action='walk',duration=15)],fps=60,width=1920,height=720)

def test_invalid_glb_fails(tmp_path):
 p=tmp_path/'bad.glb';p.write_bytes(b'not glb')
 with pytest.raises(ValueError):read_glb(p)

def test_multi_character_manifest_not_silently_rendered():
 with pytest.raises(ValueError,match='one character'):
  Manifest(shots=[Shot(character='KIO',action='walk',duration=1),
                  Shot(character='Lumi',action='wave',duration=1)])

def test_disconnected_island_reported(tmp_path):
 rgba=Image.new('RGBA',(32,32),(0,0,0,0))
 for x in range(3,10):
  for y in range(3,10):rgba.putpixel((x,y),(200,30,20,255))
 for x in range(20,28):
  for y in range(20,28):rgba.putpixel((x,y),(20,90,200,255))
 path=tmp_path/'island.png';out=tmp_path/'island.glb';rgba.save(path)
 qa=generate_mesh(path,out,max_side=32)
 assert qa['watertight'] and qa['connected_components']==2
