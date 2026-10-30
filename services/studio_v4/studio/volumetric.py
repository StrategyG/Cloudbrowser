"""CPU-only single-view volumetric draft. Hidden geometry is inferred, not recovered."""
from pathlib import Path
import numpy as np
from PIL import Image
import trimesh
from .mesh import validate_png


def generate_volumetric_draft(png: Path, out: Path, *, max_side: int = 96,
                              radial_segments: int = 24) -> dict:
    """Create real 3D volume from inferred elliptical cross-sections of PNG rows.

    NOT faithful image-to-3D reconstruction: the depth, back, and occluded limbs
    are invented. Requires owner visual acceptance before rig/render.
    """
    if not 16 <= radial_segments <= 64 or radial_segments % 2:
        raise ValueError("Radial segments must be even, between 16 and 64")
    if not 16 <= max_side <= 128:
        raise ValueError("Invalid mesh size")
    rgba = validate_png(png)
    width, height = rgba.size
    scale = min(1.0, max_side / max(width, height))
    cols, rows = max(2, round(width*scale)), max(2, round(height*scale))
    sampled = rgba.resize((cols, rows), Image.Resampling.NEAREST)
    opaque = np.asarray(sampled.getchannel("A")) >= 128
    active = np.flatnonzero(np.any(opaque, axis=1))
    if len(active) < 4:
        raise ValueError("PNG silhouette requires at least four visible rows")
    cell = 2.0 / max(cols, rows)
    rings, uv = [], []
    for y in active:
        x = np.flatnonzero(opaque[y])
        centre = (float(x[0]) + float(x[-1]) + 1.0) / 2.0
        half_width = max(0.75, (float(x[-1]) - float(x[0]) + 1.0) / 2.0)
        half_depth = max(1.25, min(half_width*0.65, max(cols,rows)*0.23))
        ring = []
        for j in range(radial_segments):
            angle = 2*np.pi*j/radial_segments
            x_img = centre + half_width*float(np.cos(angle))
            z = half_depth*float(np.sin(angle))
            ring.append(((x_img-cols/2.0)*cell,
                         (rows/2.0-(float(y)+0.5))*cell, z*cell))
            uv.append((max(0.0,min(1.0,x_img/cols)),
                       1.0-(float(y)+0.5)/rows))
        rings.append(ring)
    vertices = [vertex for ring in rings for vertex in ring]
    faces = []
    for i in range(len(rings)-1):
        for j in range(radial_segments):
            k = (j+1)%radial_segments
            a,b = i*radial_segments+j,i*radial_segments+k
            c,d = (i+1)*radial_segments+j,(i+1)*radial_segments+k
            faces.extend(((a,b,c),(b,d,c)))
    for ring_index in (0,len(rings)-1):
        ring = np.asarray(rings[ring_index])
        center = tuple(float(v) for v in ring.mean(axis=0))
        idx = len(vertices)
        vertices.append(center)
        uv.append((max(0.0,min(1.0,center[0]/(cols*cell)+0.5)),
                   1.0-(float(active[ring_index])+0.5)/rows))
        for j in range(radial_segments):
            a = ring_index*radial_segments+j
            b = ring_index*radial_segments+(j+1)%radial_segments
            faces.append((idx,b,a) if ring_index == 0 else (idx,a,b))
    mesh = trimesh.Trimesh(vertices=np.asarray(vertices,dtype=np.float32),
                           faces=np.asarray(faces,dtype=np.int64),process=False)
    # Topology is one connected manifold with known winding; avoid SciPy-only repair.
    if mesh.volume < 0:
        mesh.invert()
    if not mesh.is_watertight or not mesh.is_winding_consistent or mesh.volume <= 0:
        raise ValueError("Inferred 3D draft failed topology checks")
    material = trimesh.visual.material.SimpleMaterial(image=rgba)
    mesh.visual = trimesh.visual.texture.TextureVisuals(
        uv=np.asarray(uv,dtype=np.float32),material=material)
    out.parent.mkdir(parents=True,exist_ok=True)
    scene = trimesh.Scene()
    scene.add_geometry(mesh,node_name="VolumetricDraft",geom_name="VolumetricDraft")
    out.write_bytes(scene.export(file_type="glb"))
    loaded = trimesh.load(out,force="scene")
    if len(loaded.geometry)!=1 or not next(iter(loaded.geometry.values())).is_watertight:
        out.unlink(missing_ok=True)
        raise ValueError("Exported volumetric draft is not watertight")
    return {
        "geometry_kind":"single_view_volumetric_loft_draft",
        "volumetric_mesh":True,"full_3d_reconstruction":False,
        "source_views":1,"hidden_surface_provenance":"inferred_elliptical_depth",
        "mesh_count":1,"connected_components":1,"verts":len(mesh.vertices),
        "tris":len(mesh.faces),"watertight":True,"winding_consistent":True,
        "volume":float(mesh.volume),
        "dimensions":[float(v) for v in mesh.extents],
        "requires_human_approval":True,
        "limitations":"Single-image 3D draft; estimated back/sides; no anatomy, identity or retopology guarantee",
    }
