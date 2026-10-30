"""Deterministic Blender PNG-frame renderer. Run in Blender 4.x background."""
import json, math, sys, random
from pathlib import Path
import bpy
from mathutils import Vector

def args():
 tail=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
 if len(tail)!=3:raise RuntimeError('Expected asset.glb manifest.json frames_directory')
 return Path(tail[0]).resolve(),Path(tail[1]).resolve(),Path(tail[2]).resolve()

def look_at(obj,target):
 direction=Vector(target)-obj.location
 obj.rotation_euler=direction.to_track_quat('-Z','Y').to_euler()

def mat(name,color,roughness=.85):
 m=bpy.data.materials.new(name);m.diffuse_color=(*color,1)
 m.use_nodes=True
 bs=m.node_tree.nodes.get('Principled BSDF')
 if bs: bs.inputs['Base Color'].default_value=(*color,1);bs.inputs['Roughness'].default_value=roughness
 return m

def make_world(location,lighting):
 scene=bpy.context.scene
 world=bpy.data.worlds.new('StudioWorld');scene.world=world;world.use_nodes=True
 world.node_tree.nodes['Background'].inputs['Color'].default_value=(.06,.08,.14,1)
 world.node_tree.nodes['Background'].inputs['Strength'].default_value=.75
 floor_mat=mat('Ground',(.18,.2,.25))
 bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,-.025))
 ground=bpy.context.object;ground.name='Ground';ground.data.materials.append(floor_mat)
 sun_data=bpy.data.lights.new('Sun','AREA');sun=bpy.data.objects.new('StudioSun',sun_data)
 bpy.context.collection.objects.link(sun);sun.location=(3,-4,8);sun_data.energy=900;sun_data.shape='DISK';sun_data.size=5
 if lighting in ('sunset','warm'):
  sun_data.color=(1,.65,.38);world.node_tree.nodes['Background'].inputs['Color'].default_value=(.24,.13,.15,1)
 elif lighting=='night':
  sun_data.color=(.4,.55,1);sun_data.energy=500
 if location=='arusia':
  random.seed(19)
  for side in (-1,1):
   for i in range(5):
    h=1+random.random()*2
    bpy.ops.mesh.primitive_cube_add(size=1,location=(side*(3+i*.45),2.8+i*.15,h/2-.01))
    o=bpy.context.object;o.name=f'ARUSIA_building_{side}_{i}'
    o.dimensions=(.55,.55,h)
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    o.data.materials.append(mat('Building',(.21+.05*i,.22,.35)))
 elif location=='forest':
  random.seed(7)
  green=mat('ForestGreen',(.08,.3,.15))
  for i in range(12):
   x=random.choice([-1,1])*(2+random.random()*4)
   y=2+random.random()*3
   bpy.ops.mesh.primitive_cone_add(vertices=6,radius1=.45,depth=2.2,location=(x,y,1.15))
   bpy.context.object.data.materials.append(green)

def render(src,manifest_path,frames):
 manifest=json.loads(manifest_path.read_text())
 shots=manifest['shots'];fps=manifest['fps']
 # Hard safety bounds even when renderer executed directly.
 if fps not in (24,30,60):raise RuntimeError('Invalid FPS')
 if (manifest['width'],manifest['height']) not in ((640,360),(1280,720),(1920,1080)):
  raise RuntimeError('Invalid resolution')
 if sum(s['duration'] for s in shots)>15:raise RuntimeError('Duration limit')
 if manifest.get('approval')!='approved':raise RuntimeError('Unapproved manifest')
 bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
 bpy.ops.import_scene.gltf(filepath=str(src))
 rigs=[o for o in bpy.context.scene.objects if o.type=='ARMATURE']
 if len(rigs)!=1:raise RuntimeError('Expected exactly one rigged armature')
 rig=rigs[0]
 meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
 if not meshes:raise RuntimeError('No skinned meshes')
 def bounds_min_z():return min((mesh.matrix_world@v.co).z for mesh in meshes for v in mesh.data.vertices)
 origin_z=-bounds_min_z()
 rig.location.z+=origin_z
 scene=bpy.context.scene
 scene.render.engine='BLENDER_EEVEE_NEXT' if bpy.app.version >= (4,2,0) else 'BLENDER_EEVEE'
 scene.render.resolution_x=manifest['width'];scene.render.resolution_y=manifest['height']
 scene.render.resolution_percentage=100
 scene.render.image_settings.file_format='PNG';scene.render.film_transparent=False
 scene.render.fps=fps
 scene.view_settings.view_transform='Standard'
 scene.render.filepath=str(frames)
 frames.mkdir(parents=True,exist_ok=True)
 camera_data=bpy.data.cameras.new('Camera');camera=bpy.data.objects.new('Camera',camera_data)
 bpy.context.collection.objects.link(camera);scene.camera=camera
 camera_data.type='ORTHO';camera_data.ortho_scale=3.1
 frame_no=0
 base=rig.location.copy();path_x=base.x
 for shot in shots:
  # Reuse a single environment only for same location; isolate shots when differing environments.
  for old in [o for o in scene.objects if o.name=='Ground' or o.name=='StudioSun' or o.name.startswith('ARUSIA_building_')]:
   bpy.data.objects.remove(old,do_unlink=True)
  make_world(shot['location'],shot['lighting'])
  action=shot['action'];cam=shot['camera'];shot_frames=round(shot['duration']*fps)
  for f in range(shot_frames):
   seconds=f/fps;phase=seconds*2*math.pi*1.4
   # Explicitly reset all pose transforms to prevent leakage between shots.
   for bone in rig.pose.bones:
    bone.rotation_mode='XYZ';bone.rotation_euler=(0,0,0)
    bone.location=(0,0,0);bone.scale=(1,1,1)
   rig.location=base.copy();rig.location.x=path_x
   if action=='walk':
    stride=.55;rig.location.x=path_x+seconds*stride
    for name,sgn in [('UpperLeg_L',1),('UpperLeg_R',-1)]:
     if name in rig.pose.bones:rig.pose.bones[name].rotation_euler.x=sgn*.45*math.sin(phase)
    for name,sgn in [('UpperArm_L',-1),('UpperArm_R',1)]:
     if name in rig.pose.bones:rig.pose.bones[name].rotation_euler.x=sgn*.3*math.sin(phase)
    rig.location.z=base.z+abs(math.sin(phase))*.015
   elif action=='wave':
    if 'UpperArm_R' in rig.pose.bones:
     rig.pose.bones['UpperArm_R'].rotation_euler.y=-.8
     rig.pose.bones['UpperArm_R'].rotation_euler.x=.3*math.sin(phase)
   elif action=='jump':
    t=f/max(1,shot_frames-1)
    rig.location.z=base.z+.45*max(0,math.sin(math.pi*t))
   else:
    if 'Chest' in rig.pose.bones:rig.pose.bones['Chest'].scale.z=1+.015*math.sin(seconds*math.pi*2)
   if cam=='orbit':
    angle=2*math.pi*f/max(1,shot_frames)
    camera.location=(4.5*math.sin(angle),-4.5*math.cos(angle),1.3)
   else:
    camera.location=(0,-5,1.3)
   camera_data.ortho_scale=2.25 if cam=='closeup' else 3.1
   look_at(camera,(rig.location.x,0,1.0))
   scene.frame_set(frame_no+1)
   scene.render.filepath=str(frames / f'frame_{frame_no:06d}.png')
   bpy.ops.render.render(write_still=True)
   frame_no+=1
  if action=='walk':path_x+=shot_frames/fps*.55
  rig.location=base.copy();rig.location.x=path_x
 return frame_no

if __name__=='__main__': render(*args())
