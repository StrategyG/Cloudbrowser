"""Deterministic, watertight silhouette extrusion. Honest designation: 2.5D, NOT AI 3D reconstruction."""
from pathlib import Path
import numpy as np
from PIL import Image
import trimesh


def validate_png(path, max_pixels=6_000_000):
 with Image.open(path) as im:
  if im.format != 'PNG': raise ValueError('Only genuine PNG files are allowed')
  if im.width * im.height > max_pixels: raise ValueError('Image is too large')
  if im.mode not in ('RGBA','LA','P'): raise ValueError('PNG transparency is required; use RGBA')
  rgba = im.convert('RGBA')
  if rgba.getchannel('A').getextrema()[0] == 255: raise ValueError('Transparent background required for silhouette mode')
  if rgba.getchannel('A').getextrema()[1] < 128: raise ValueError('No visible subject in alpha channel')
  return rgba


def generate_mesh(png: Path, out: Path, max_side=96, thickness=0.12, threshold=128):
 """Create conforming front/back grid with perimeter walls; consistent vertex positions and winding."""
 rgba=validate_png(png)
 w,h=rgba.size
 scale=min(1.,max_side/max(w,h)); cols=max(2,round(w*scale)); rows=max(2,round(h*scale))
 # Resampling alpha via NEAREST prevents unexpected boundary topology.
 thumb=rgba.resize((cols,rows),Image.Resampling.NEAREST)
 alpha=np.asarray(thumb.getchannel('A'))
 mask=alpha>=threshold
 if not np.any(mask): raise ValueError('No opaque pixels at selected threshold')
 # Grid coordinates x right, y up, z front/back, normalized to 2 Blender units tall.
 cell=2./max(cols,rows)
 vertices=[]; uv=[]; index={}; faces=[]
 def vertex(x,y,side):
  key=(int(x),int(y),int(side))
  if key not in index:
   index[key]=len(vertices)
   vertices.append(((x-cols/2)*cell,(rows/2-y)*cell,thickness/2 if side==1 else -thickness/2))
   uv.append((x/cols,1-y/rows))
  return index[key]
 def face(a,b,c): faces.append([a,b,c])
 for y in range(rows):
  for x in range(cols):
   if not mask[y,x]: continue
   # front normals +Z; back normals -Z
   a=vertex(x,y,1); b=vertex(x+1,y,1); c=vertex(x+1,y+1,1); d=vertex(x,y+1,1)
   face(a,d,b);face(b,d,c)
   a2=vertex(x,y,0);b2=vertex(x+1,y,0);c2=vertex(x+1,y+1,0);d2=vertex(x,y+1,0)
   face(a2,b2,d2);face(b2,c2,d2)
   # perimeter outward normals
   if y==0 or not mask[y-1,x]:
    face(a,b,a2); face(b,b2,a2)
   if y==rows-1 or not mask[y+1,x]:
    face(d,d2,c); face(c,d2,c2)
   if x==0 or not mask[y,x-1]:
    face(a,a2,d); face(d,a2,d2)
   if x==cols-1 or not mask[y,x+1]:
    face(b,c,b2); face(c,c2,b2)
 vertices=np.asarray(vertices,dtype=np.float32)
 faces=np.asarray(faces,dtype=np.int64)
 # A colored material avoids accidental double multiplication of PNG colors and COLOR_0.
 m=trimesh.Trimesh(vertices=vertices,faces=faces,process=False,validate=False)
 if not m.is_watertight or not m.is_winding_consistent:
  raise ValueError('Mesh integrity failed: not watertight or winding inconsistent')
 if m.volume<=0: raise ValueError('Mesh winding volume is non-positive')
 components=len(trimesh.graph.connected_components(m.face_adjacency,nodes=np.arange(len(m.faces))))
 # Texture sourced from original PNG; UV corresponding to silhouette grid.
 mat=trimesh.visual.material.SimpleMaterial(image=rgba)
 m.visual=trimesh.visual.texture.TextureVisuals(uv=np.asarray(uv),material=mat)
 out.parent.mkdir(parents=True,exist_ok=True)
 scene=trimesh.Scene(); scene.add_geometry(m,node_name='AssetMesh',geom_name='AssetMesh')
 out.write_bytes(scene.export(file_type='glb'))
 check=trimesh.load(out,force='scene'); meshes=list(check.geometry.values())
 if not meshes or not all(x.is_watertight for x in meshes): raise ValueError('Export roundtrip invalid')
 return {'geometry_kind':'silhouette_extrusion_2_5D','full_3d_reconstruction':False,
         'mesh_count':len(meshes),'verts':len(m.vertices),'tris':len(m.faces),
         'connected_components':components,
         'watertight':bool(m.is_watertight),'winding_consistent':bool(m.is_winding_consistent),
         'volume':float(m.volume),'dimensions':list(map(float,m.extents)),
         'requires_human_approval':True,'limitations':'Rear/sides are inferred; not true multiview 3D'}
