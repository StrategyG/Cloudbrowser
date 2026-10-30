"""Blender CLI pose-review generator for *existing* compatible skinned GLB assets.

Usage: blender -b --python workers/review_existing_rig.py -- mesh.glb qa.json
Never alters/re-exports the uploaded GLB. Non-standard bones fail closed.
"""
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

REQUIRED = ("UpperArm_L", "UpperArm_R", "UpperLeg_L", "UpperLeg_R")


def review(source: Path, report: Path) -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=str(source))
    meshes = [item for item in bpy.context.scene.objects if item.type == "MESH"]
    bound = [(mesh, modifier.object) for mesh in meshes for modifier in mesh.modifiers
             if modifier.type == "ARMATURE" and modifier.object is not None
             and modifier.object.type == "ARMATURE"]
    # GLB importer may create additional *unbound* skeleton/helper objects.
    # Only one real skin binding is valid for this one-character pipeline.
    if len(bound) != 1:
        raise ValueError("Expected one skinned mesh-to-armature binding; "
                         f"found {len(bound)} (mesh objects={len(meshes)}, "
                         f"armatures={len([o for o in bpy.context.scene.objects if o.type == 'ARMATURE'])})")
    mesh, arm = bound[0]
    missing = [bone for bone in REQUIRED if bone not in arm.pose.bones]
    if missing:
        raise ValueError("Rig has incompatible bone names: " + ", ".join(missing))
    deform = {bone.name for bone in arm.data.bones if bone.use_deform}
    group_map = {group.index: group.name for group in mesh.vertex_groups}
    unweighted = 0
    for vertex in mesh.data.vertices:
        if not any(g.weight > 1e-6 and group_map.get(g.group) in deform
                   for g in vertex.groups):
            unweighted += 1
    if unweighted:
        raise ValueError(f"Unweighted mesh vertices: {unweighted}")

    points = [mesh.matrix_world @ Vector(corner) for corner in mesh.bound_box]
    low = Vector(tuple(min(v[i] for v in points) for i in range(3)))
    high = Vector(tuple(max(v[i] for v in points) for i in range(3)))
    span = max((high-low).length, 0.1)
    center = (low + high) / 2
    camera_data = bpy.data.cameras.new("ImportedRigReviewCamera")
    camera = bpy.data.objects.new("ImportedRigReviewCamera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = span * 1.5
    # Blender Z-up. A fixed frontal camera is a review reference, not canonical 3D accuracy.
    camera.location = center + Vector((0, -span*2, span*0.15))
    camera.rotation_euler = (center-camera.location).to_track_quat("-Z", "Y").to_euler()
    scene = bpy.context.scene
    scene.camera = camera
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.render.resolution_x = 480
    scene.render.resolution_y = 640
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"

    previous = {bone.name: (bone.rotation_mode, bone.rotation_quaternion.copy(),
                             bone.rotation_euler.copy())
                for bone in arm.pose.bones}
    poses = {
        "rest": {},
        "arms": {"UpperArm_L": (0, 0, 0.5), "UpperArm_R": (0, 0, -0.5)},
        "legs": {"UpperLeg_L": (0.4, 0, 0), "UpperLeg_R": (-0.4, 0, 0)},
        "combo": {"UpperArm_L": (0, 0, 0.7), "UpperArm_R": (0, 0, -0.7),
                  "UpperLeg_L": (0.35, 0, 0), "UpperLeg_R": (-0.35, 0, 0)},
    }
    for label, rotations in poses.items():
        for bone in arm.pose.bones:
            bone.rotation_mode = "XYZ"
            bone.rotation_euler = (0.0, 0.0, 0.0)
        for name, rotation in rotations.items():
            arm.pose.bones[name].rotation_euler = rotation
        bpy.context.view_layer.update()
        scene.render.filepath = str(source.parent / f"rig_pose_{label}.png")
        bpy.ops.render.render(write_still=True)
    for bone in arm.pose.bones:
        mode, quat, euler = previous[bone.name]
        bone.rotation_mode = mode
        if mode == "QUATERNION":
            bone.rotation_quaternion = quat
        else:
            bone.rotation_euler = euler
    report.write_text(json.dumps({
        "rig_type": "imported_skinned_glb",
        "joint_count": len(arm.data.bones),
        "mesh_vertices": len(mesh.data.vertices),
        "unweighted_vertices": 0,
        "pose_previews": [f"rig_pose_{pose}.png" for pose in poses],
        "status": "review_required",
        "notes": "Existing skin preserved. Check each pose and Godot bone compatibility before approval.",
    }, indent=2))


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
    if len(argv) != 2:
        raise SystemExit("Expected source.glb qa.json")
    review(Path(argv[0]).resolve(), Path(argv[1]).resolve())
