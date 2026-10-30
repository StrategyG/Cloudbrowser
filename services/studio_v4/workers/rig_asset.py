"""Run: blender -b --python workers/rig_asset.py -- source.glb rigged.glb report.json
Humanoid *template*, not semantic body-part reconstruction. Always needs visual approval.
"""
import json, sys, math
from pathlib import Path
import bpy
from mathutils import Vector

def args():
 tail=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
 if len(tail)!=3: raise RuntimeError('Expected input.glb output.glb qa.json')
 return [Path(p).resolve() for p in tail]

def dist_point_segment(p,a,b):
 ab=b-a; s=max(0.,min(1.,(p-a).dot(ab)/max(ab.length_squared,1e-10)))
 return (p-(a+s*ab)).length

def rig(src,out,report):
 bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
 bpy.ops.import_scene.gltf(filepath=str(src))
 meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
 if len(meshes)!=1: raise RuntimeError('Rig template requires exactly one mesh')
 mesh=meshes[0]
 # Bake imported transform before binding to keep all coordinates in one reference space.
 bpy.context.view_layer.objects.active=mesh
 bpy.ops.object.select_all(action='DESELECT');mesh.select_set(True)
 bpy.ops.object.transform_apply(location=False,rotation=True,scale=True)
 verts=[mesh.matrix_world @ v.co for v in mesh.data.vertices]
 if not verts: raise RuntimeError('Empty mesh')
 lo=Vector(tuple(min(v[i] for v in verts) for i in range(3)))
 hi=Vector(tuple(max(v[i] for v in verts) for i in range(3)))
 sx=max(hi.x-lo.x,1e-4);sz=max(hi.z-lo.z,1e-4);cy=(hi.y+lo.y)/2
 # Blender is Z-up; glTF importer converts the original 2D Y-up plane to Blender Z-up.
 def pt(x,y,depth=0):return Vector((lo.x+x*sx,cy+depth*sx,lo.z+y*sz))
 # Each entry: name, parent, bone head, bone tail in normalized silhouette space.
 bones=[
 ('Root',None,(.5,.02),(.5,.38)),
 ('Hips','Root',(.5,.38),(.5,.48)),
 ('Spine','Hips',(.5,.48),(.5,.62)),
 ('Chest','Spine',(.5,.62),(.5,.77)),
 ('Neck','Chest',(.5,.77),(.5,.85)),
 ('Head','Neck',(.5,.85),(.5,.98)),
 ('UpperArm_L','Chest',(.35,.73),(.21,.64)),
 ('LowerArm_L','UpperArm_L',(.21,.64),(.08,.53)),
 ('Hand_L','LowerArm_L',(.08,.53),(.03,.49)),
 ('UpperArm_R','Chest',(.65,.73),(.79,.64)),
 ('LowerArm_R','UpperArm_R',(.79,.64),(.92,.53)),
 ('Hand_R','LowerArm_R',(.92,.53),(.97,.49)),
 ('UpperLeg_L','Hips',(.43,.38),(.42,.22)),
 ('LowerLeg_L','UpperLeg_L',(.42,.22),(.42,.07)),
 ('Foot_L','LowerLeg_L',(.42,.07),(.40,.025)),
 ('UpperLeg_R','Hips',(.57,.38),(.58,.22)),
 ('LowerLeg_R','UpperLeg_R',(.58,.22),(.58,.07)),
 ('Foot_R','LowerLeg_R',(.58,.07),(.60,.025)),
 ]
 arm_data=bpy.data.armatures.new('StudioHumanoidArmature')
 arm=bpy.data.objects.new('StudioHumanoidRig',arm_data)
 bpy.context.collection.objects.link(arm)
 bpy.context.view_layer.objects.active=arm;arm.select_set(True)
 bpy.ops.object.mode_set(mode='EDIT')
 for name,parent,a,b in bones:
  eb=arm_data.edit_bones.new(name)
  eb.head=pt(*a);eb.tail=pt(*b)
  if name=='Root': eb.use_deform=False
  if parent: eb.parent=arm_data.edit_bones[parent]
 bpy.ops.object.mode_set(mode='OBJECT')
 for vg in mesh.vertex_groups: mesh.vertex_groups.remove(vg)
 names=[name for name,_,_,_ in bones if name!='Root']
 groups={name:mesh.vertex_groups.new(name=name) for name in names}
 # Guided spatial weighting: not an ML understanding of anatomy.
 bad=0
 for v in mesh.data.vertices:
  world=mesh.matrix_world @ v.co
  uvx=(world.x-lo.x)/sx;uvy=(world.z-lo.z)/sz
  def allowed(name):
   if name.startswith(('UpperArm','LowerArm','Hand')):
    side='L' if uvx<.5 else 'R'
    return name.endswith(side) and uvy>.42 and (uvx<.34 if side=='L' else uvx>.66)
   if name.startswith(('UpperLeg','LowerLeg','Foot')):
    side='L' if uvx<.5 else 'R'
    return name.endswith(side) and uvy<.47
   return True
  distances=[]
  for name,_,a,b in bones:
   if name=='Root' or not allowed(name): continue
   distance=dist_point_segment(world,pt(*a),pt(*b))
   # Restrict torso influences to the torso to protect arms/legs.
   if name in ('Hips','Spine','Chest','Neck','Head') and uvy<.40 and name!='Hips': distance+=sz*.4
   distances.append((distance,name))
  distances.sort(key=lambda x:x[0])
  chosen=distances[:4]
  if not chosen: bad+=1;continue
  sigma=max(sx,sz)*.16
  ws=[math.exp(-d*d/(2*sigma*sigma)) for d,_ in chosen]
  total=sum(ws)
  if total<1e-9: ws=[1.]+[0.]*(len(chosen)-1);total=1.
  for weight,(_,name) in zip(ws,chosen):
   if weight>1e-6:groups[name].add([v.index],weight/total,'REPLACE')
 mesh.parent=arm
 mod=mesh.modifiers.new('Skinning','ARMATURE');mod.object=arm
 # Export only the single skinned mesh and armature; avoid accidental objects.
 bpy.ops.object.select_all(action='DESELECT')
 arm.select_set(True);mesh.select_set(True);bpy.context.view_layer.objects.active=arm
 out.parent.mkdir(parents=True,exist_ok=True)
 bpy.ops.export_scene.gltf(filepath=str(out),export_format='GLB',use_selection=True,
                          export_skins=True,export_animations=False,export_apply=False)
 data={'rig_type':'humanoid_template_v1','joint_count':len(bones),'mesh_vertices':len(mesh.data.vertices),
       'unweighted_vertices':bad,'weights_algorithm':'bone_segment_gaussian_top4',
       'status':'review_required','notes':'Template fit may not match PNG anatomy. Inspect deformation before approval.'}
 # Render a mandatory four-pose QA contact set to support human approval.
 camera_data=bpy.data.cameras.new('RigPreviewCam')
 camera=bpy.data.objects.new('RigPreviewCam',camera_data)
 bpy.context.collection.objects.link(camera)
 scene=bpy.context.scene;scene.camera=camera
 camera_data.type='ORTHO';camera_data.ortho_scale=max(sx,sz)*1.45
 camera.location=(lo.x+sx*.5, cy-max(sx,sz)*3, lo.z+sz*.5)
 direction=Vector((lo.x+sx*.5,cy,lo.z+sz*.5))-camera.location
 camera.rotation_euler=direction.to_track_quat('-Z','Y').to_euler()
 scene.render.engine='BLENDER_WORKBENCH'
 scene.display.shading.light='STUDIO'
 scene.display.shading.color_type='MATERIAL'
 scene.render.resolution_x=480;scene.render.resolution_y=640
 scene.render.resolution_percentage=100
 scene.render.image_settings.file_format='PNG'
 # Fully deterministic preview with the same armature used in export.
 poses={
  'rest':{},'arms':{'UpperArm_L':(.5,0,0),'UpperArm_R':(-.5,0,0)},
  'legs':{'UpperLeg_L':(.4,0,0),'UpperLeg_R':(-.4,0,0)},
  'combo':{'UpperArm_L':(.7,0,0),'UpperArm_R':(-.7,0,0),
           'UpperLeg_L':(.35,0,0),'UpperLeg_R':(-.35,0,0)}
 }
 for label,rotations in poses.items():
  for pb in arm.pose.bones:
   pb.rotation_mode='XYZ';pb.rotation_euler=(0,0,0)
  for name,rotation in rotations.items():
   if name in arm.pose.bones:arm.pose.bones[name].rotation_euler=rotation
  bpy.context.view_layer.update()
  scene.render.filepath=str(out.parent/f'rig_pose_{label}.png')
  bpy.ops.render.render(write_still=True)
 data['pose_previews']=[f'rig_pose_{label}.png' for label in poses]
 report.write_text(json.dumps(data,indent=2))
 if bad: raise RuntimeError(f'{bad} unweighted vertices')

if __name__=='__main__':
 try: rig(*args())
 except Exception as exc:
  print('RIG_FAILED:',exc,file=sys.stderr);raise
