"""Strict external GLB import gate: single watertight character, embedded resources only.

Validation is structural and geometric, not animation/rig-quality certification.
"""
from pathlib import Path

import trimesh

from .gltf_qa import inspect, read_glb

MAX_GLB_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_GLTF_VERTICES = 600_000
MAX_GLTF_NODES = 4096
MAX_GLTF_TRIANGLES = 1_000_000
# Blender template and offline Godot runner currently handle one character mesh.
SUPPORTED_SKIN_EXTENSIONS = {"KHR_materials_unlit", "KHR_texture_transform",
                             "KHR_materials_pbrSpecularGlossiness"}


def validate_imported_glb(path: Path) -> dict:
    path = Path(path)
    size = path.stat().st_size
    if not 20 <= size <= MAX_GLB_UPLOAD_BYTES:
        raise ValueError("GLB exceeds 50 MiB or is empty")
    doc, _ = read_glb(path)
    if doc.get("extensionsRequired"):
        raise ValueError("Required glTF extensions cannot be validated by the Studio import gate")
    if len(doc.get("nodes", [])) > MAX_GLTF_NODES:
        raise ValueError("Too many scene nodes")
    for buffer in doc.get("buffers", []):
        if "uri" in buffer:
            raise ValueError("External/data URI buffers are not supported")
    for image in doc.get("images", []):
        if "uri" in image:
            raise ValueError("External/data URI images are not supported; embed textures in GLB")
    gltf = inspect(path)
    if (gltf["meshes"] != 1 or gltf["primitives"] != 1 or
            not 0 < gltf["vertex_count"] <= MAX_GLTF_VERTICES or
            gltf["nodes"] > MAX_GLTF_NODES):
        raise ValueError("Import requires one mesh primitive with at most 600,000 vertices")
    prim = doc["meshes"][0]["primitives"][0]
    if prim.get("mode", 4) != 4:
        raise ValueError("Mesh primitive must be triangles")
    count = doc["accessors"][prim["indices"]]["count"] if "indices" in prim else gltf["vertex_count"]
    if count > MAX_GLTF_TRIANGLES * 3:
        raise ValueError("Too many triangles")
    if gltf["animations"]:
        raise ValueError("Embedded GLB animations are not supported by the procedural Godot runner")
    if gltf["skins"] > 1:
        raise ValueError("Only a single skin is supported")
    if gltf["skins"]:
        gltf = inspect(path, require_skin=True)

    # Unlike structural GLB inspection, this checks topology and surface orientation.
    scene = trimesh.load(path, file_type="glb", force="scene", process=False)
    meshes = list(scene.geometry.values())
    if len(meshes) != 1 or not isinstance(meshes[0], trimesh.Trimesh):
        raise ValueError("Exactly one triangle mesh is required")
    mesh = meshes[0]
    if not len(mesh.vertices) or not len(mesh.faces):
        raise ValueError("Empty geometry")
    if not mesh.is_watertight or not mesh.is_winding_consistent:
        raise ValueError("Mesh must be watertight with consistent winding")
    if mesh.volume <= 0:
        raise ValueError("Mesh winding must have positive volume")
    components = len(mesh.split(only_watertight=False))
    if components != 1:
        raise ValueError("Single connected character mesh required")
    if not all(float(value) > 0 for value in mesh.extents):
        raise ValueError("Degenerate mesh dimensions")
    return {
        "geometry_kind": "imported_glb_3d",
        "source_type": "external_glb",
        "full_3d_reconstruction": False,
        "mesh_count": 1,
        "connected_components": components,
        "watertight": True,
        "winding_consistent": True,
        "volume": float(mesh.volume),
        "dimensions": list(map(float, mesh.extents)),
        "verts": len(mesh.vertices),
        "tris": len(mesh.faces),
        "preexisting_skin": bool(gltf["skins"]),
        "gltf": gltf,
        "requires_human_approval": True,
        "limitations": "Structural/topology QA only; rig motion and visual quality require separate review",
    }
