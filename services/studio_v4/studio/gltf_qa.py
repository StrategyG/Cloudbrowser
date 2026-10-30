"""glTF 2.0/GLB structural QA. This is NOT a substitute for the Khronos glTF Validator."""
import json
import struct
from pathlib import Path

_COMPONENT={5120:('b',1),5121:('B',1),5122:('h',2),5123:('H',2),5125:('I',4),5126:('f',4)}
_SHAPES={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16}

def read_glb(path):
 data=Path(path).read_bytes()
 if len(data)<20 or data[:4]!=b'glTF': raise ValueError('Not a GLB')
 magic,version,total=struct.unpack_from('<III',data,0)
 if version!=2 or total!=len(data): raise ValueError('Invalid GLB header')
 pos=12; chunks=[]
 while pos<len(data):
  if pos+8>len(data): raise ValueError('Invalid GLB chunk header')
  length,kind=struct.unpack_from('<II',data,pos);pos+=8
  if length%4 or pos+length>len(data): raise ValueError('Invalid GLB chunk length')
  chunks.append((kind,data[pos:pos+length]));pos+=length
 if not chunks or chunks[0][0]!=0x4E4F534A: raise ValueError('Missing JSON chunk')
 doc=json.loads(chunks[0][1].decode('utf-8').strip())
 binary=next((body for kind,body in chunks[1:] if kind==0x004E4942),b'')
 return doc,binary

def accessor(doc,buffer,idx):
 a=doc['accessors'][idx]
 if 'sparse' in a: raise ValueError('Sparse accessors require external validator')
 view=doc['bufferViews'][a['bufferView']]
 if view.get('buffer',0)!=0: raise ValueError('Only single buffer GLB supported')
 typ,nbytes=_COMPONENT[a['componentType']];dim=_SHAPES[a['type']]
 start=view.get('byteOffset',0)+a.get('byteOffset',0)
 stride=view.get('byteStride',dim*nbytes)
 if stride<dim*nbytes or stride%nbytes: raise ValueError('Bad accessor stride')
 end=start+(a['count']-1)*stride+dim*nbytes if a['count'] else start
 if end>len(buffer) or end>view.get('byteOffset',0)+view['byteLength']:
  raise ValueError('Accessor out of bounds')
 return [struct.unpack_from('<'+typ*dim,buffer,start+i*stride) for i in range(a['count'])]

def inspect(path, require_skin=False):
 doc,bin_data=read_glb(path)
 if doc.get('asset',{}).get('version')!='2.0': raise ValueError('glTF 2.0 required')
 nodes=doc.get('nodes',[]); meshes=doc.get('meshes',[]); skins=doc.get('skins',[])
 if not meshes: raise ValueError('No meshes')
 # Enforce references for all scene nodes and avoid hierarchy cycles.
 for n in nodes:
  for c in n.get('children',[]):
   if not isinstance(c,int) or c<0 or c>=len(nodes): raise ValueError('Invalid child node reference')
  if 'mesh' in n and not 0<=n['mesh']<len(meshes): raise ValueError('Invalid mesh reference')
  if 'skin' in n and not 0<=n['skin']<len(skins): raise ValueError('Invalid skin reference')
 visited=set();active=set()
 def walk(idx):
  if idx in active: raise ValueError('Cyclic node graph')
  if idx in visited: return
  active.add(idx)
  for child in nodes[idx].get('children',[]): walk(child)
  active.remove(idx);visited.add(idx)
 for i in range(len(nodes)): walk(i)
 for s in skins:
  if not s.get('joints'): raise ValueError('Skin without joints')
  if len(set(s['joints']))!=len(s['joints']): raise ValueError('Duplicate joints')
  if any(j<0 or j>=len(nodes) for j in s['joints']): raise ValueError('Skin joint out of range')
  if 'inverseBindMatrices' in s and len(accessor(doc,bin_data,s['inverseBindMatrices']))!=len(s['joints']):
   raise ValueError('Inverse-bind count mismatch')
 if require_skin and not skins: raise ValueError('Missing skin')
 vertex_count=0; primitives=0; skinned_primitive_count=0
 mesh_skin_lengths={}
 for node in nodes:
  if 'mesh' in node and 'skin' in node:
   mesh_skin_lengths.setdefault(node['mesh'],set()).add(len(skins[node['skin']]['joints']))
 for mesh_index,mesh in enumerate(meshes):
  for prim in mesh.get('primitives',[]):
   primitives+=1; att=prim.get('attributes',{})
   if 'POSITION' not in att: raise ValueError('Missing POSITION')
   count=doc['accessors'][att['POSITION']]['count'];vertex_count+=count
   if 'JOINTS_0' in att or 'WEIGHTS_0' in att:
    if 'JOINTS_0' not in att or 'WEIGHTS_0' not in att: raise ValueError('Incomplete skin vertex attributes')
    joints=accessor(doc,bin_data,att['JOINTS_0']);weights=accessor(doc,bin_data,att['WEIGHTS_0'])
    if len(joints)!=count or len(weights)!=count: raise ValueError('Skin vertex attribute count mismatch')
    lengths=mesh_skin_lengths.get(mesh_index)
    if not lengths: raise ValueError('Vertex joints present but no skin bound to mesh node')
    if any(any(j<0 or any(j>=length for length in lengths) for j in row) for row in joints):
     raise ValueError('Vertex joint index out of bound skin range')
    if any(abs(sum(row)-1)>0.015 or any(w<0 for w in row) for row in weights):
     raise ValueError('Non-normalized or negative skin weights')
    skinned_primitive_count+=1
   if 'indices' in prim:
    ind=accessor(doc,bin_data,prim['indices'])
    if any(row[0]>=count for row in ind): raise ValueError('Index out of range')
 if require_skin and not skinned_primitive_count: raise ValueError('No JOINTS_0/WEIGHTS_0')
 return {'valid_structure':True,'nodes':len(nodes),'meshes':len(meshes),
         'skins':len(skins),'primitives':primitives,'skinned_primitives':skinned_primitive_count,
         'vertex_count':vertex_count,'animations':len(doc.get('animations',[])),
         'validator':'internal_structural_only','human_review_required':True}
